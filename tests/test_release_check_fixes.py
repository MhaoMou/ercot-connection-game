"""Regressions from the release check: preview robustness, storage feasibility,
CSV rule agreement, CLI failure modes, and leaderboard visibility."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

pytest.importorskip("highspy")

from ercot_game import batch_cli, student_preview
from ercot_game.base_load import SITE_NET_WITHDRAWAL_FIELDS, read_site_net_withdrawal
from ercot_game.batch_evaluation import (
    BatchScoringRules,
    ProjectionDiagnostics,
    TeamScore,
    _fair_continuous_projection,
    _leaderboard_row,
    collect_csv_submissions,
)
from ercot_game.csv_submission import CANONICAL_CSV_COLUMNS, read_student_csv
from ercot_game.csv_validator import validate_csv_submission
from ercot_game.models import ConnectionPlan, SitePlan, StoragePlan, TeamPlan
from tools.activsg2000 import dcopf
from tools.activsg2000.dcopf import clear_prepared_artifact_cache
from tools.activsg2000.plan_adapter import evaluate_plans_with_prepared_dcopf

HEADER = ",".join(CANONICAL_CSV_COLUMNS)
DAYS = 2
HORIZON = 24 * DAYS
PERIODS = tuple(range(HORIZON))
DIP_HOURS = (18, 19)


# ---------------------------------------------------------------- toy network
def _dip_artifact(root: Path) -> Path:
    """Two buses, one 100 MW line; the site bus hosts 75 MW in two evening hours."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "bus.csv").write_text("bus_id,type\n1,3\n2,1\n", encoding="utf-8")
    (root / "bus_load_base.csv").write_text("bus_id,base_load_mw\n1,0.0\n2,0.0\n", encoding="utf-8")
    (root / "branch_limits.csv").write_text(
        "branch_id,from_bus_id,to_bus_id,reactance_pu,thermal_limit_mva,status\n"
        "br1,1,2,0.1,100.0,1\n",
        encoding="utf-8",
    )
    (root / "dcline.csv").write_text("status,from_bus_id,to_bus_id,Pt\n", encoding="utf-8")
    generators = (
        "generator_id,bus_id,p_min_mw,p_max_mw,marginal_cost_c1_per_mwh,status,profile_type\n"
        "g1,1,0.0,1000.0,20.0,1,thermal\n"
    )
    (root / "generator_catalog.csv").write_text(generators, encoding="utf-8")
    (root / "generator_limits.csv").write_text(generators, encoding="utf-8")
    rows = ["period,1,2"] + [
        f"{t},0.0,{25.0 if t % 24 in DIP_HOURS else 0.0}" for t in PERIODS
    ]
    (root / "demand_bus.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    clear_prepared_artifact_cache()
    return root


def _site_plan(team_id: str, connection_mw: float, power_mw: float = 0.0) -> TeamPlan:
    storages = (
        (StoragePlan(f"storage:{team_id}:s1", "s1", power_mw, 4.0 * power_mw),)
        if power_mw > 0
        else ()
    )
    return TeamPlan(
        team_id,
        connections=(ConnectionPlan("s1", "2", connection_mw, (1.0,) * HORIZON),),
        storages=storages,
        sites=(SitePlan("s1", "2", connection_mw, 0.0, power_mw, 4.0 * power_mw),),
    )


@pytest.fixture
def unknown_instead_of_infeasible(monkeypatch):
    """Make HiGHS report kUnknown (as on the 2,000-bus case) for infeasible hours."""
    original = dcopf.ReusableDCOPFModel.solve

    def solve(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        except dcopf.DCOPFInfeasible:
            raise dcopf.DCOPFUnresolved("DCOPF solver unresolved: HighsModelStatus.kUnknown") from None

    monkeypatch.setattr(dcopf.ReusableDCOPFModel, "solve", solve)


# ------------------------------------------------- #2 storage never hurts service
@pytest.mark.parametrize("teams", [1, 2])
def test_storage_benders_tightens_bounds_when_highs_reports_unknown(
    tmp_path, unknown_instead_of_infeasible, teams
) -> None:
    # 75 MW fits every hour; full-power charging in a dip hour does not.
    # The master must restrict charging there instead of aborting.
    artifact = _dip_artifact(tmp_path / "dip")
    plans = [_site_plan("team-a", 75.0, 10.0)]
    if teams == 2:
        plans = [_site_plan("team-a", 40.0, 10.0), _site_plan("team-b", 35.0, 5.0)]
    dispatch = evaluate_plans_with_prepared_dcopf(
        artifact, plans, period_indices=PERIODS, storage_boundary_mode="daily_exact_cycle"
    )
    for period in dispatch.periods:
        if period.period_index % 24 in DIP_HOURS:
            charge = sum(
                amount
                for by_storage in period.storage_charge_mw_by_team.values()
                for amount in by_storage.values()
            )
            assert charge <= 1e-6


def test_adding_a_battery_never_reduces_projected_service(
    tmp_path, unknown_instead_of_infeasible
) -> None:
    artifact = _dip_artifact(tmp_path / "dip")

    def alpha(plan: TeamPlan) -> float:
        result = _fair_continuous_projection(
            artifact, (plan,), PERIODS, PERIODS, storage_boundary_mode="daily_exact_cycle"
        )
        assert result is not None
        return result.service_fraction_by_team[plan.team_id]

    without = alpha(_site_plan("team-a", 75.0))
    with_battery = alpha(_site_plan("team-a", 75.0, 10.0))
    assert without == pytest.approx(1.0, abs=1e-6)
    assert with_battery >= without - 1e-6


# ------------------------------------------- #1 preview projects instead of crashing
def _preview_rules() -> BatchScoringRules:
    return BatchScoringRules(
        rules_version="x",
        it_value_per_mwh=(1000.0,) * HORIZON,
        energy_price_per_mwh=(0.0,) * HORIZON,
    )


@pytest.mark.parametrize(
    ("connection_mw", "expected_fraction"),
    [(100.0, 0.75), (50_000.0, 0.0)],
)
def test_preview_applies_fair_projection_above_hosting_capacity(
    tmp_path, connection_mw, expected_fraction
) -> None:
    artifact = _dip_artifact(tmp_path / "dip")
    result = student_preview.preview_plans(
        (_site_plan("team-a", connection_mw, 10.0),),
        artifact_dir=artifact,
        horizon=HORIZON,
        rules=_preview_rules(),
        submission_number=1,
        preview_stride=1,
        workers=2,
    )
    fraction = result.service_fraction_by_team["team-a"]
    assert fraction == pytest.approx(expected_fraction, abs=2e-3)
    assert result.projection is not None
    payload = json.loads(json.dumps(student_preview._result_payload(result)))
    score = payload["team_scores"][0]
    assert score["service_fraction"] == pytest.approx(expected_fraction, abs=2e-3)
    assert score["dropped"] is (expected_fraction == 0.0)
    assert payload["projection"]["applied"] is True
    assert score["served_load_mwh"] == pytest.approx(
        connection_mw * fraction * HORIZON, rel=1e-6, abs=1e-6
    )


def test_preview_within_hosting_capacity_reports_full_service(tmp_path) -> None:
    artifact = _dip_artifact(tmp_path / "dip")
    result = student_preview.preview_plans(
        (_site_plan("team-a", 70.0),),
        artifact_dir=artifact,
        horizon=HORIZON,
        rules=_preview_rules(),
        submission_number=1,
        preview_stride=1,
    )
    assert result.projection is None
    assert result.service_fraction_by_team == {"team-a": 1.0}


# ------------------------------------------------ #6-#9, #11 shared CSV rules
def _csv(tmp_path: Path, body: str, name: str = "team.csv", header: str = HEADER) -> Path:
    folder = tmp_path / "subs"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(header + "\n" + body + "\n", encoding="utf-8")
    return path


def _all_reasons(path: Path) -> tuple[str, str, str]:
    report = validate_csv_submission(path, bus_ids={"1001"}, max_generator_to_connection_ratio=0.5)
    checker = "\n".join(issue.message for issue in report.issues)
    try:
        read_student_csv(path, bus_ids={"1001"}, max_generator_to_connection_ratio=0.5)
    except ValueError as exc:
        reader = str(exc)
    else:
        reader = ""
    collection = collect_csv_submissions(
        path.parent,
        bus_ids={"1001"},
        horizon=1,
        default_generator_cost_per_mwh=0.0,
        max_generator_to_connection_ratio=0.5,
    )
    assert not collection.accepted
    evaluator = collection.rejected[0].failure_reason or ""
    return checker, reader, evaluator


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("team-a,s1,1001,0,0,10,40", "connection_capacity_mw is 0"),
        ("team-a,s1,1001,0,5,0,0", "connection_capacity_mw is 0"),
        ("team-a,s1,1001,0,0,0,0", "empty site"),
        ("team-a,s1,1001,1_000,0,0,0", "connection_capacity_mw must be a finite decimal"),
        ("team-a,s1,1001,100,0,1_0,40", "storage_power_mw must be a finite decimal"),
        ("team-a,s1,1001,100,50.00001,0,0", "(50.00001 MW > 50 MW"),
    ],
)
def test_checker_reader_and_evaluator_reject_alike(tmp_path, row, message) -> None:
    for reason in _all_reasons(_csv(tmp_path, row)):
        assert message in reason


def test_negative_connection_reports_only_non_negativity(tmp_path) -> None:
    checker, reader, evaluator = _all_reasons(_csv(tmp_path, "team-a,s1,1001,-10,5,0,0"))
    for reason in (checker, reader, evaluator):
        assert "must be non-negative" in reason
        assert "cannot exceed" not in reason


@pytest.mark.parametrize(
    ("header", "named"),
    [
        (HEADER.replace("storage_energy_mwh", "storage_energy"), "storage_energy_mwh"),
        (HEADER.replace("team_id,site_id", "site_id,team_id"), "team_id (position 2"),
        (HEADER + ",notes", "'notes'"),
    ],
)
def test_header_mismatch_names_the_column(tmp_path, header, named) -> None:
    body = "team-a,s1,1001,100,0,0,0" + (",x" if header.endswith("notes") else "")
    for reason in _all_reasons(_csv(tmp_path, body, header=header)):
        assert named in reason


def test_scientific_notation_is_still_accepted(tmp_path) -> None:
    path = _csv(tmp_path, "team-a,s1,1001,1e2,5E1,1.0e1,4e1")
    assert validate_csv_submission(path, bus_ids={"1001"}, max_generator_to_connection_ratio=0.5).valid


def test_evaluator_reports_non_utf8_like_the_checker(tmp_path) -> None:
    folder = tmp_path / "subs"
    folder.mkdir()
    (folder / "latin.csv").write_bytes(
        (HEADER + "\nteam-\xe9,s1,1001,100,0,0,0\n").encode("latin-1")
    )
    collection = collect_csv_submissions(
        folder, bus_ids={"1001"}, horizon=1, default_generator_cost_per_mwh=0.0
    )
    assert collection.rejected[0].failure_reason == "submission must be UTF-8 CSV"


# --------------------------------------------------- #3-#5 CLI failure modes
def test_missing_submissions_dir_fails_fast(tmp_path, capsys) -> None:
    missing = tmp_path / "nope"
    assert batch_cli.main(
        ["run", "--submissions-dir", str(missing), "--output-dir", str(tmp_path / "out"), "--week", "1"]
    ) == 2
    assert "submissions directory not found" in capsys.readouterr().err
    assert not (tmp_path / "out" / "leaderboard.csv").exists()
    assert student_preview.main(
        ["--submissions-dir", str(missing), "--week", "1", "--output", str(tmp_path / "p.json")]
    ) == 2
    assert "submissions directory not found" in capsys.readouterr().err


def test_missing_base_load_dir_says_not_found(tmp_path) -> None:
    with pytest.raises(ValueError, match="directory not found"):
        read_site_net_withdrawal(tmp_path / "does_not_exist")


def test_all_rejected_folder_prints_each_reason(tmp_path, capsys) -> None:
    _csv(tmp_path, "team-a,s1,1001,100,60,0,0", name="a.csv")
    _csv(tmp_path, "team-b,s1,1001,1_000,0,0,0", name="b.csv")
    folder = tmp_path / "subs"
    assert student_preview.main(
        ["--submissions-dir", str(folder), "--week", "1", "--output", str(tmp_path / "p.json")]
    ) == 1
    out = capsys.readouterr()
    assert "rejected a.csv (team team-a)" in out.out and "cannot exceed" in out.out
    assert "rejected b.csv (team team-b)" in out.out and "finite decimal" in out.out
    assert "no valid CSV submissions were found" in out.err
    assert batch_cli.main(
        ["run", "--submissions-dir", str(folder), "--output-dir", str(tmp_path / "out"), "--week", "1"]
    ) == 0
    out = capsys.readouterr().out
    assert "rejected a.csv (team team-a)" in out and "rejected b.csv (team team-b)" in out


def test_submission_2_preview_requires_base_load(tmp_path, capsys) -> None:
    _csv(tmp_path, "team-a,s2,1001,10,0,0,0")
    assert student_preview.main(
        [
            "--submissions-dir", str(tmp_path / "subs"), "--week", "2",
            "--submission-number", "2", "--output", str(tmp_path / "p.json"),
        ]
    ) == 2
    assert "--base-load-from" in capsys.readouterr().err


def test_submission_2_preview_uses_base_load_and_rejects_reused_sites(
    tmp_path, capsys, monkeypatch
) -> None:
    s1 = tmp_path / "s1_out"
    s1.mkdir()
    with (s1 / "site_net_withdrawal.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(SITE_NET_WITHDRAWAL_FIELDS)
        for period in range(120):
            writer.writerow([period, "team-a", "s1", "1001", 20, 0, 0, 0, 20])
    _csv(tmp_path, "team-a,s1,1001,10,0,0,0", name="reuse.csv")
    _csv(tmp_path, "team-b,s9,1001,10,0,0,0", name="new.csv")
    seen = {}

    def fake_preview(plans, *, artifact_dir, **kwargs):
        seen["artifact_dir"] = Path(artifact_dir)
        seen["teams"] = [plan.team_id for plan in plans]
        demand = (Path(artifact_dir) / "demand_bus.csv").read_text(encoding="utf-8")
        seen["demand_header"] = demand.splitlines()[0]
        seen["manifest"] = json.loads((Path(artifact_dir) / "manifest.json").read_text())
        raise student_preview.PreviewInfeasible("stop after inspection")

    monkeypatch.setattr(student_preview, "preview_plans", fake_preview)
    code = student_preview.main(
        [
            "--submissions-dir", str(tmp_path / "subs"), "--week", "2",
            "--base-load-from", str(s1), "--output", str(tmp_path / "p.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2 and "stop after inspection" in captured.err
    assert seen["teams"] == ["team-b"]
    assert "site_id already used in Submission 1: s1" in captured.out
    assert "submission_2_base_load" in seen["manifest"]


# --------------------------------------------------------- #10 leaderboard
def test_leaderboard_marks_service_fraction_and_dropped() -> None:
    score = TeamScore(
        team_id="team-a", rank=1, valid=True, feasible=True, score=-5.0,
        served_load_mwh=0.0, it_value=0.0, energy_cost=0.0,
        generator_operating_cost=0.0, generator_capital_cost=0.0,
        site_cost=5.0, competition_scope="joint_projection",
    )
    diagnostics = ProjectionDiagnostics(
        service_fraction_by_team={"team-a": 0.0},
        projected_capacity_mw_by_team={}, capped_request_capacity_mw_by_team={},
        requested_load_mwh_by_team={}, projected_load_mwh_by_team={},
        total_requested_load_mwh=0.0, total_projected_load_mwh=0.0,
        proportional_fair_utility=0.0, total_load_tolerance_mwh=0.0,
    )
    row = _leaderboard_row(score, diagnostics)
    assert row["service_fraction"] == "0" and row["dropped"] is True
    full = _leaderboard_row(score, None)
    assert full["service_fraction"] == "1" and full["dropped"] is False


def test_released_submission_2_artifact_needs_no_base_load_flag(tmp_path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"submission_2_base_load": {"withdrawal_bus_count": 1}}), encoding="utf-8"
    )
    assert student_preview._has_submission_2_base_load(tmp_path)
    assert not student_preview._has_submission_2_base_load(tmp_path / "missing")
