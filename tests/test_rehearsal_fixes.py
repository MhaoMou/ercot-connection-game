"""Regressions from the 25-team Week 3 dress rehearsal.

Submission 2 base-load validation at the feasibility boundary, the standalone
``base-load`` command, reproducible parallel fair projection, the classroom
leaderboard and salted team folders, and the roster check.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("highspy")

from ercot_game import batch_cli
from ercot_game.base_load import (
    SITE_NET_WITHDRAWAL_FIELDS,
    BaseLoadValidationError,
    materialize_base_load_artifact,
)
from ercot_game.batch_evaluation import (
    classroom_team_folder,
    evaluate_csv_batch,
    load_scoring_rules,
)
from ercot_game.csv_submission import CANONICAL_CSV_COLUMNS
from ercot_game.scenario_package import require_validated_block
from tools.activsg2000.dcopf import (
    _prepared_period_inputs,
    clear_prepared_artifact_cache,
    load_prepared_artifact,
    minimum_demand_adjustment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO = REPO_ROOT / "data" / "teaching" / "ieee14_demo_representative"
DEMO_RULES = REPO_ROOT / "data" / "teaching" / "dispatch_scoring_rules_ieee14_demo_representative_v1.json"
HORIZON = 120
BUS = "13"
PERIOD = 0


def _hosting_limit_mw(period: int = PERIOD, bus: str = BUS) -> float:
    """Largest extra demand at ``bus`` in ``period`` that the demo network serves."""
    clear_prepared_artifact_cache()
    artifact = load_prepared_artifact(str(DEMO.resolve()))
    huge = 10_000.0
    buses, generators, branches, fixed = _prepared_period_inputs(
        DEMO, artifact, period_index=period, additional_demand_mw_by_bus={bus: huge}
    )
    changes = minimum_demand_adjustment(
        buses=buses,
        generators=generators,
        branches=branches,
        adjustable_bus_ids=(bus,),
        fixed_injection_mw_by_bus=fixed,
        base_mva=100.0,
    )
    assert changes is not None and changes[bus] < 0.0
    return huge + changes[bus]


def _withdrawal(extra_at_period: float) -> dict[str, list[float]]:
    values = [1.0] * HORIZON
    values[PERIOD] = extra_at_period
    return {BUS: values}


# ----------------------------------------------------------- base-load validation
def test_minimum_demand_adjustment_is_empty_for_a_feasible_point():
    clear_prepared_artifact_cache()
    artifact = load_prepared_artifact(str(DEMO.resolve()))
    buses, generators, branches, fixed = _prepared_period_inputs(DEMO, artifact, period_index=0)
    assert minimum_demand_adjustment(
        buses=buses, generators=generators, branches=branches,
        adjustable_bus_ids=(BUS,), fixed_injection_mw_by_bus=fixed, base_mva=100.0,
    ) == {}


def test_base_load_just_past_the_boundary_is_adjusted_within_tolerance_and_recorded(tmp_path):
    # Submission 1 projected a team exactly to the boundary: the carried
    # withdrawal overshoots by solver noise and the strict solve fails.
    limit = _hosting_limit_mw()
    manifest = materialize_base_load_artifact(DEMO, _withdrawal(limit + 2e-5), tmp_path / "derived")
    assert manifest["validation_status"] == "passed"
    validation = manifest["validation"]
    assert validation["passed_period_count"] == HORIZON
    assert validation["tolerance_adjusted_period_count"] == 1
    (adjustment,) = validation["tolerance_adjustments"]
    assert adjustment["period_index"] == PERIOD and adjustment["bus_id"] == BUS
    assert -1e-3 < adjustment["change_mw"] < 0.0
    assert require_validated_block(tmp_path / "derived")["validation_status"] == "passed"
    # The written demand carries the (tiny) adjustment; other hours are untouched.
    with (tmp_path / "derived" / "demand_bus.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with (DEMO / "demand_bus.csv").open(newline="", encoding="utf-8") as handle:
        base = list(csv.DictReader(handle))
    assert float(rows[PERIOD][BUS]) == pytest.approx(float(base[PERIOD][BUS]) + limit, abs=1e-3)
    assert float(rows[1][BUS]) == pytest.approx(float(base[1][BUS]) + 1.0, abs=1e-6)
    manifest_hash = manifest["network"]["sha256"]["demand_bus.csv"]
    from ercot_game.scenario_package import sha256_file

    assert manifest_hash == sha256_file(tmp_path / "derived" / "demand_bus.csv")


def test_truly_infeasible_base_load_names_the_step_and_periods(tmp_path):
    limit = _hosting_limit_mw()
    with pytest.raises(BaseLoadValidationError) as caught:
        materialize_base_load_artifact(DEMO, _withdrawal(limit + 1.0), tmp_path / "derived")
    message = str(caught.value)
    assert "Submission 2 base-load validation failed" in message
    assert f"periods [{PERIOD}]" in message and "tolerance" in message
    assert caught.value.periods == (PERIOD,)
    manifest = json.loads((tmp_path / "derived" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "failed"  # never left "pending"
    assert manifest["validation"]["failed_periods"][0]["period_index"] == PERIOD
    assert manifest["validation"]["tolerance_adjustments"] == []


def test_clean_base_load_needs_no_adjustment(tmp_path):
    manifest = materialize_base_load_artifact(DEMO, _withdrawal(1.0), tmp_path / "derived")
    assert manifest["validation_status"] == "passed"
    assert manifest["validation"]["tolerance_adjustments"] == []


def _write_withdrawal_output(root: Path, mw_by_period: list[float]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "site_net_withdrawal.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(SITE_NET_WITHDRAWAL_FIELDS)
        for period, mw in enumerate(mw_by_period):
            writer.writerow((period, "team-a", "site-a1", BUS, mw, 0.0, 0.0, 0.0, mw))
    return root


def test_base_load_command_builds_and_validates_release_data(tmp_path, capsys):
    s1_out = _write_withdrawal_output(tmp_path / "s1_out", [2.0] * HORIZON)
    out = tmp_path / "release"
    assert batch_cli.main(
        [
            "base-load", "--base-load-from", str(s1_out), "--output-dir", str(out),
            "--artifact-dir", str(DEMO),
        ]
    ) == 0
    printed = capsys.readouterr().out
    assert "submission 2 base load validation: passed 120 periods" in printed
    assert require_validated_block(out)["submission_2_base_load"]["submission_1_output"] == str(s1_out)
    # The released artifact can be used directly; nothing else was evaluated.
    assert not (out / "evaluation.json").exists()


def test_base_load_command_reports_infeasible_periods(tmp_path, capsys):
    limit = _hosting_limit_mw()
    values = [1.0] * HORIZON
    values[PERIOD] = limit + 5.0
    s1_out = _write_withdrawal_output(tmp_path / "s1_out", values)
    assert batch_cli.main(
        [
            "base-load", "--base-load-from", str(s1_out), "--output-dir", str(tmp_path / "release"),
            "--artifact-dir", str(DEMO),
        ]
    ) == 2
    err = capsys.readouterr().err
    assert "Submission 2 base-load validation failed" in err and f"periods [{PERIOD}]" in err


# ----------------------------------------------------------- parallel projection
def _write_plan(path: Path, team_id: str, sites) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CANONICAL_CSV_COLUMNS)
        for site in sites:
            writer.writerow((team_id, *site))


def test_parallel_projection_matches_serial_with_budgeted_generators_and_storage(tmp_path):
    subs = tmp_path / "subs"
    subs.mkdir()
    _write_plan(subs / "team-a.csv", "team-a", [("a1", "13", 30, 10, 5, 20)])
    _write_plan(subs / "team-b.csv", "team-b", [("b1", "14", 30, 0, 0, 0)])
    _write_plan(subs / "team-c.csv", "team-c", [("c1", "13", 12, 6, 0, 0), ("c2", "9", 10, 0, 0, 0)])
    _write_plan(subs / "team-d.csv", "team-d", [("d1", "14", 8, 4, 2, 8)])
    rules = load_scoring_rules(DEMO_RULES, artifact_dir=DEMO, horizon=HORIZON)
    results = [
        evaluate_csv_batch(
            subs,
            artifact_dir=DEMO,
            horizon=HORIZON,
            rules=rules,
            dispatch_workers=workers,
            submission_number=1,
            energy_cost_enabled=True,
        )
        for workers in (1, 3)
    ]
    serial, parallel = results
    assert serial.competition_scope == parallel.competition_scope == "joint_projection"
    assert serial.projection_diagnostics.service_fraction_by_team == (
        parallel.projection_diagnostics.service_fraction_by_team
    )
    assert [(s.team_id, s.score) for s in serial.team_scores] == [
        (s.team_id, s.score) for s in parallel.team_scores
    ]
    fractions = serial.projection_diagnostics.service_fraction_by_team
    assert 0.5 < fractions["team-a"] < 1.0 and fractions["team-d"] == 1.0


# ----------------------------------------------------------- classroom
_ROUNDS = (
    "week-1-submission-1",
    "week-1-submission-2",
    "week-2-submission-1",
    "week-2-submission-2",
    "week-3-submission-1",
    "week-3-submission-2",
)


def _classroom_manifest(tmp_path: Path, artifact: str) -> Path:
    path = tmp_path / "classroom.json"
    path.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "round_key": key,
                        "submissions_dir": "subs",
                        "artifact_dir": artifact,
                        "rules": str(DEMO_RULES),
                    }
                    for key in _ROUNDS
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_classroom_reports_a_missing_artifact_dir_clearly(tmp_path, capsys):
    manifest = _classroom_manifest(tmp_path, str(tmp_path / "no-such-package"))
    assert batch_cli.main(
        ["classroom", "--manifest", str(manifest), "--output-dir", str(tmp_path / "out")]
    ) == 2
    err = capsys.readouterr().err
    assert "artifact_dir does not exist" in err and "no-such-package" in err
    assert "must provide horizon" not in err


def _score(team_id: str, score: float, *, valid: bool = True):
    return SimpleNamespace(team_id=team_id, valid=valid, feasible=valid, score=score, failure_reason=None)


def test_classroom_writes_final_leaderboard_salted_folders_and_passes_workers(
    tmp_path, monkeypatch, capsys
):
    manifest = _classroom_manifest(tmp_path, str(DEMO))
    scores = {
        "week-1-submission-1": [_score("team-a", 99.0)],
        "week-1-submission-2": [],
        "week-2-submission-1": [_score("team-a", 1.0), _score("team-b", 2.0)],
        "week-2-submission-2": [_score("team-a", 10.0)],
        "week-3-submission-1": [_score("team-a", 100.0), _score("team-b", 300.0)],
        "week-3-submission-2": [_score("team-b", 1000.0, valid=False)],
    }
    seen = {}

    def fake_evaluate_classroom(*, rounds, evaluator_kwargs=None, **_kwargs):
        seen["kwargs"] = evaluator_kwargs
        submissions = tuple(
            SimpleNamespace(
                round_key=key,
                week_id=key[:6],
                submission_number=int(key[-1]),
                feedback_only=key.startswith("week-1"),
                scored=not key.startswith("week-1"),
                evaluation=SimpleNamespace(
                    dispatch=SimpleNamespace(periods=()),
                    source_period_indices=(),
                    team_scores=tuple(scores[key]),
                ),
            )
            for key in _ROUNDS
        )
        return SimpleNamespace(
            submissions=submissions,
            to_public_dict=lambda: {"submissions": [], "weekly_rankings": {}, "final_rankings": []},
        )

    written = []

    def fake_writer(evaluation, output_dir, *, team_folder_key=None, **_kwargs):
        folders = {s.team_id: classroom_team_folder(s.team_id, team_folder_key) for s in evaluation.team_scores}
        written.append(folders)
        return folders

    monkeypatch.setattr(batch_cli, "evaluate_classroom", fake_evaluate_classroom)
    monkeypatch.setattr(batch_cli, "write_classroom_outputs", fake_writer)
    out = tmp_path / "out"
    assert batch_cli.main(
        ["classroom", "--manifest", str(manifest), "--output-dir", str(out), "--workers", "4"]
    ) == 0
    assert seen["kwargs"] == {"dispatch_workers": 4}
    assert "final leaderboard (instructor-only)" in capsys.readouterr().out

    secret = (out / "instructor" / "team_folder_secret.txt").read_text(encoding="utf-8").strip()
    assert len(secret) >= 32
    folder_a = written[2]["team-a"]
    assert folder_a == classroom_team_folder("team-a", secret.encode("utf-8"))
    assert folder_a != classroom_team_folder("team-a")  # not the unsalted team-ID hash

    with (out / "instructor" / "final_leaderboard.csv").open(newline="", encoding="utf-8") as handle:
        rows = {row["team_id"]: row for row in csv.DictReader(handle)}
    assert float(rows["team-b"]["total"]) == pytest.approx(2.0 + 300.0 + 1000.0)
    assert float(rows["team-a"]["total"]) == pytest.approx(1.0 + 10.0 + 100.0)  # week 1 not graded
    assert float(rows["team-a"]["week3_s2"]) == 0.0 and float(rows["team-b"]["week2_s2"]) == 0.0
    assert rows["team-b"]["rank"] == "1" and rows["team-a"]["team_folder"] == folder_a

    # A resumed run reuses the secret, so folder names stay stable.
    assert batch_cli.main(
        ["classroom", "--manifest", str(manifest), "--output-dir", str(out)]
    ) == 0
    assert written[-4]["team-a"] == folder_a


# ----------------------------------------------------------- roster
def test_run_roster_lists_missing_teams(tmp_path, monkeypatch, capsys):
    subs = tmp_path / "subs"
    subs.mkdir()
    roster = tmp_path / "roster.csv"
    roster.write_text("team_id,name\nteam-a,A\nteam-b,B\nteam-c,C\n", encoding="utf-8")

    def fake_evaluate(*_args, **_kwargs):
        return SimpleNamespace(
            team_scores=(_score("team-a", 1.0), _score("team-x", 0.0, valid=False)),
            competition_scope="joint",
            source_period_indices=(),
            rejected_submissions=(),
        )

    monkeypatch.setattr(batch_cli, "evaluate_csv_batch", fake_evaluate)
    monkeypatch.setattr(batch_cli, "write_batch_outputs", lambda *_a, **_k: Path(_a[1]).mkdir(parents=True, exist_ok=True))
    out = tmp_path / "out"
    assert batch_cli.main(
        [
            "run", "--submissions-dir", str(subs), "--output-dir", str(out),
            "--artifact-dir", str(DEMO), "--rules", str(DEMO_RULES), "--week", "2", "--roster", str(roster),
        ]
    ) == 0
    printed = capsys.readouterr().out
    assert "roster: 1 of 3 teams submitted; missing: team-b, team-c; not on roster: team-x" in printed
    check = json.loads((out / "roster_check.json").read_text(encoding="utf-8"))
    assert check["missing_team_ids"] == ["team-b", "team-c"]


# ----------------------------------------------------------- solver robustness
def test_unresolved_highs_solve_is_retried_without_presolve():
    """A Benders master that HiGHS presolve leaves kUnknown once blocked team-01
    in the rehearsal (read as "infeasible" by the projection)."""
    from highspy import HighsModelStatus

    from tools.activsg2000.dcopf import _run_highs

    class FakeHighs:
        def __init__(self, statuses):
            self.statuses = list(statuses)
            self.options = {"presolve": "on", "simplex_strategy": 1}
            self.runs = []
            self.status = None

        def getOptionValue(self, name):
            return (None, self.options[name])

        def setOptionValue(self, name, value):
            self.options[name] = value

        def clearSolver(self):
            pass

        def run(self):
            self.runs.append(dict(self.options))
            self.status = self.statuses.pop(0)

        def getModelStatus(self):
            return self.status

    retried = FakeHighs([HighsModelStatus.kUnknown, HighsModelStatus.kOptimal])
    _run_highs(retried)
    assert retried.getModelStatus() == HighsModelStatus.kOptimal
    assert [run["presolve"] for run in retried.runs] == ["on", "off"]
    assert retried.options == {"presolve": "on", "simplex_strategy": 1}  # restored

    settled = FakeHighs([HighsModelStatus.kInfeasible])
    _run_highs(settled)
    assert len(settled.runs) == 1  # a decided solve is never repeated

    stubborn = FakeHighs([HighsModelStatus.kUnknown] * 3)
    _run_highs(stubborn)
    assert [(run["presolve"], run["simplex_strategy"]) for run in stubborn.runs] == [
        ("on", 1), ("off", 1), ("on", 4)
    ]
