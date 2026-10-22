"""The ten-year representative-day release: package, rules, scoring and Submission 2."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ercot_game import batch_cli, csv_validator
from ercot_game.base_load import (
    materialize_base_load_artifact,
    net_withdrawal_by_bus,
    read_site_net_withdrawal,
    site_ids_by_team,
    site_net_withdrawal_rows,
)
from ercot_game.batch_evaluation import (
    BatchScoringRules,
    _score_team,
    evaluate_csv_batch,
    load_scoring_rules,
)
from ercot_game.csv_submission import CANONICAL_CSV_COLUMNS, read_student_csv
from ercot_game.models import ConnectionPlan, GeneratorPlan, SitePlan, StoragePlan, TeamPlan
from ercot_game.scenario_package import (
    REPRESENTATIVE_PACKAGE_VERSION,
    ScenarioPackageError,
    load_scenario_manifest,
    representative_day_weights,
    require_validated_block,
)
from ercot_game.scenario_profiles import hourly_state
from tools.activsg2000.build_representative_package import (
    k_medoids,
    select_representative_days,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "data" / "processed" / "activsg2000_representative_v1"
SOURCE = REPO_ROOT / "data" / "processed" / "activsg2000_scenarios_v1"
RULES = REPO_ROOT / "data" / "teaching" / "dispatch_scoring_rules_representative_v1.json"
DEMO = REPO_ROOT / "data" / "teaching" / "ieee14_demo_representative"
DEMO_RULES = REPO_ROOT / "data" / "teaching" / "dispatch_scoring_rules_ieee14_demo_representative_v1.json"
ANNUITY = sum(1.07 ** -year for year in range(1, 11))


def _write_plan(path: Path, team_id: str, rows: list[tuple[str, str, float, float, float, float]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CANONICAL_CSV_COLUMNS)
        for row in rows:
            writer.writerow((team_id, *row))
    return path


def _demand_rows(artifact: Path) -> list[dict[str, str]]:
    with (artifact / "demand_bus.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# --- package -----------------------------------------------------------------


def test_representative_package_is_validated_with_five_weighted_days():
    manifest = load_scenario_manifest(PACKAGE)
    assert manifest["package_version"] == REPRESENTATIVE_PACKAGE_VERSION
    assert manifest["validation_status"] == "passed"
    assert manifest["horizon"] == 120 and manifest["time_step_hours"] == 1 and manifest["days"] == 5
    assert manifest["validation"]["passed_period_count"] == 120
    assert all(period["solver_status"] == "optimal" for period in manifest["validation"]["periods"])
    weights = representative_day_weights(PACKAGE)
    assert sum(weights) == pytest.approx(365.0)
    days = manifest["representative_days"]
    assert [day["first_period"] for day in days] == [0, 24, 48, 72, 96]
    assert sum(day["represented_days"] for day in days) == 366
    peak = [day for day in days if day["is_peak_day"]]
    assert len(peak) == 1 and peak[0]["represented_days"] == 1
    assert peak[0]["weight"] == 1.0
    assert peak[0]["peak_load_mw"] == pytest.approx(manifest["selection"]["annual_peak_hourly_load_mw"])
    assert manifest["period_day_weights"] == [weight for weight in weights for _ in range(24)]
    rows = _demand_rows(PACKAGE)
    assert len(rows) == 120
    assert len(rows[0]) == 2001


def test_representative_demand_matches_the_source_hourly_state():
    manifest = require_validated_block(PACKAGE)
    rows = _demand_rows(PACKAGE)
    for day in manifest["representative_days"]:
        for hour in (0, 13):
            demand, _ = hourly_state(
                SOURCE / "2028" / day["source_block"],
                year=2028,
                calendar_block=day["source_block"],
                period_index=day["source_period_start"] + hour,
            )
            row = rows[day["first_period"] + hour]
            assert {bus: float(row[bus]) for bus in demand} == pytest.approx(demand, abs=1e-6)


def test_representative_manifest_rejects_wrong_weights(tmp_path):
    payload = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    payload["day_weights"] = [73.0] * 4 + [70.0]
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScenarioPackageError, match="sum to 365"):
        require_validated_block(tmp_path)
    payload["day_weights"] = [73.0] * 5
    payload["horizon"] = 168
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScenarioPackageError, match="representative block"):
        require_validated_block(tmp_path)


def test_k_medoids_is_deterministic_and_separates_clear_clusters():
    rng = np.random.default_rng(0)
    centers = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    points = np.vstack([center + rng.normal(scale=0.3, size=(20, 2)) for center in centers])
    medoids, labels = k_medoids(points, 3)
    again = k_medoids(points, 3)
    assert np.array_equal(medoids, again[0]) and np.array_equal(labels, again[1])
    groups = {tuple(sorted(np.flatnonzero(labels == position) // 20)) for position in range(3)}
    assert groups == {tuple([group] * 20) for group in range(3)}


def test_peak_day_is_removed_from_its_cluster_and_weights_sum_to_365():
    days = np.array([[1.0] * 24] * 10 + [[2.0] * 24] * 10 + [[3.0] * 24] * 10 + [[4.0] * 24] * 9 + [[4.2] * 24])
    records = select_representative_days(days, clusters=4, days_per_year=39)
    assert [record["represented_days"] for record in records] == [10, 10, 10, 9, 1]
    assert records[-1]["is_peak_day"] and records[-1]["day_row"] == 39
    assert records[-1]["weight"] == 1.0
    assert sum(record["weight"] for record in records) == pytest.approx(39.0)


def test_builder_reproduces_the_committed_tables_byte_for_byte(tmp_path):
    from tools.activsg2000.build_representative_package import build_package

    manifest = build_package(SOURCE, tmp_path, validate=False)
    assert manifest["validation_status"] == "pending"
    for name in ("demand_bus.csv", "representative_days.csv", "bus.csv", "branch_limits.csv", "generator_limits.csv"):
        assert (tmp_path / name).read_bytes() == (PACKAGE / name).read_bytes(), name


# --- rules and weighted scoring ---------------------------------------------------


def test_rules_store_the_present_value_weights_and_unchanged_capital_costs():
    payload = json.loads(RULES.read_text(encoding="utf-8"))
    weights = representative_day_weights(PACKAGE)
    assert payload["discount_rate"] == 0.07 and payload["planning_years"] == 10
    assert payload["present_value_annuity_factor"] == pytest.approx(ANNUITY)
    assert payload["present_value_annuity_factor"] == pytest.approx(7.0236, abs=1e-4)
    assert payload["day_weights"] == pytest.approx(list(weights))
    assert payload["period_weight_hours"] == pytest.approx([w * ANNUITY for w in weights for _ in range(24)])
    assert sum(payload["period_day_weights"]) == pytest.approx(8760.0)
    assert payload["it_value_per_mwh"] == [1000.0] * 120
    assert payload["site_cost_per_mw"] == 25e6
    assert payload["generator_capital_cost_per_mw"] == 2.0e6
    assert payload["generator_daily_energy_hours"] == 2.0
    assert payload["storage_capital_cost_per_mw"] == 4e5
    assert payload["storage_capital_cost_per_mwh"] == 2.5e5
    assert payload["storage_boundary_mode"] == "daily_exact_cycle"
    assert payload["max_generator_to_connection_ratio"] == 0.5
    assert payload["it_value_provenance"]["break_even_served_fraction"] == pytest.approx(
        25e6 / (1000 * 8760 * ANNUITY), abs=1e-4
    )
    rules = load_scoring_rules(RULES, artifact_dir=PACKAGE, horizon=120)
    assert rules.weight_for(0) == pytest.approx(weights[0] * ANNUITY)
    assert rules.present_value_factor == pytest.approx(ANNUITY)
    assert rules.max_generator_to_connection_ratio == 0.5


def _tiny_dispatch():
    # (load MW, generator MW, LMP $/MWh) per period at bus b1.
    values = ((10.0, 3.0, 20.0), (8.0, 0.0, 30.0), (10.0, 4.0, 200.0))
    periods = tuple(
        SimpleNamespace(
            period_index=index,
            submitted_load_mw_by_team={"team-a": load},
            generator_dispatch_mw_by_team={"team-a": {"gen-a": generation}},
            grid_purchase_mw_by_team={"team-a": load - generation},
            grid_purchase_mw_by_team_by_bus={"team-a": {"b1": load - generation}},
            dcopf=SimpleNamespace(balance_dual_by_bus={"b1": lmp}),
        )
        for index, (load, generation, lmp) in enumerate(values)
    )
    return SimpleNamespace(periods=periods), values


def _tiny_plan() -> TeamPlan:
    return TeamPlan(
        "team-a",
        connections=(ConnectionPlan("s1", "b1", 10.0, (1.0, 1.0, 1.0)),),
        generators=(GeneratorPlan("gen-a", "s1", 4.0, 100.0),),
        sites=(SitePlan("s1", "b1", 10.0, 4.0),),
    )


def test_per_period_weights_reproduce_a_hand_calculation():
    dispatch, values = _tiny_dispatch()
    weights = (100.0 * ANNUITY, 200.0 * ANNUITY, 65.0 * ANNUITY)
    rules = BatchScoringRules(
        rules_version="hand",
        it_value_per_mwh=(1000.0,) * 3,
        time_step_hours=1.0,
        period_weight_hours=weights,
        present_value_factor=ANNUITY,
        site_cost_per_mw=25e6,
        generator_capital_cost_per_mw=1.5e6,
    )
    # Generator curve: 25% of 4 MW at 80, 50% at 150, 25% at 250 $/MWh.
    generator_cost_per_hour = (1 * 80 + 2 * 150, 0.0, 1 * 80 + 2 * 150 + 1 * 250)
    score = _score_team(_tiny_plan(), dispatch, rules, energy_cost_enabled=True)
    it_value = sum(load * 1000.0 * w for (load, _, _), w in zip(values, weights))
    energy = sum((load - gen) * lmp * w for (load, gen, lmp), w in zip(values, weights))
    generator = sum(cost * w for cost, w in zip(generator_cost_per_hour, weights))
    assert score.it_value == pytest.approx(it_value)
    assert score.energy_cost == pytest.approx(energy)
    assert score.generator_operating_cost == pytest.approx(generator)
    assert score.served_load_mwh == pytest.approx(10 * 100 + 8 * 200 + 10 * 65)
    assert score.site_cost == pytest.approx(10 * 25e6)
    assert score.generator_capital_cost == pytest.approx(4 * 1.5e6)
    assert score.score == pytest.approx(it_value - energy - generator - 10 * 25e6 - 4 * 1.5e6)


def test_default_weights_keep_the_half_year_time_step_scoring():
    dispatch, values = _tiny_dispatch()
    rules = BatchScoringRules(rules_version="6h", it_value_per_mwh=(1000.0,) * 3, time_step_hours=6.0)
    score = _score_team(_tiny_plan(), dispatch, rules, submission_number=2)
    assert score.it_value == pytest.approx(sum(load for load, _, _ in values) * 1000.0 * 6.0)
    assert score.served_load_mwh == pytest.approx(28.0 * 6.0)


@pytest.mark.parametrize(
    ("submission_number", "energy_cost_enabled", "charged"),
    ((1, None, False), (2, None, True), (2, False, False), (1, True, True), (None, False, False)),
)
def test_energy_switch_is_independent_of_the_submission_number(submission_number, energy_cost_enabled, charged):
    dispatch, _values = _tiny_dispatch()
    rules = BatchScoringRules(rules_version="t", it_value_per_mwh=(1000.0,) * 3, energy_price_per_mwh=(1.0,) * 3)
    score = _score_team(
        _tiny_plan(),
        dispatch,
        rules,
        submission_number=submission_number,
        energy_cost_enabled=energy_cost_enabled,
    )
    assert (score.energy_cost > 0) is charged


# --- generator cap ------------------------------------------------------------------


def test_generator_cap_is_half_the_connection_in_the_release(tmp_path, capsys):
    ok = _write_plan(tmp_path / "ok.csv", "team-a", [("s1", "1001", 40, 20, 0, 0)])
    over = _write_plan(tmp_path / "over.csv", "team-a", [("s1", "1001", 40, 21, 0, 0)])
    assert read_student_csv(ok, max_generator_to_connection_ratio=0.5).plan.sites[0].generator_capacity_mw == 20
    with pytest.raises(ValueError, match=r"0.5 x connection capacity \(21 MW > 20 MW\)"):
        read_student_csv(over, max_generator_to_connection_ratio=0.5)
    assert read_student_csv(over).plan.sites[0].generator_capacity_mw == 21

    assert csv_validator.main(["--file", str(over), "--artifact-dir", str(PACKAGE)]) == 1
    assert "0.5 x connection capacity" in capsys.readouterr().out
    assert csv_validator.main(["--file", str(ok), "--artifact-dir", str(PACKAGE)]) == 0
    capsys.readouterr()
    assert csv_validator.main(["--file", str(over), "--release", "half-year-6h"]) == 0


def test_batch_rejects_a_team_above_the_cap_and_scores_the_rest(tmp_path, monkeypatch):
    submissions = tmp_path / "subs"
    submissions.mkdir()
    _write_plan(submissions / "a.csv", "team-a", [("s1", "1001", 40, 30, 0, 0)])
    _write_plan(submissions / "b.csv", "team-b", [("s1", "1002", 40, 20, 0, 0)])
    rules = load_scoring_rules(RULES, artifact_dir=PACKAGE, horizon=120)
    seen = []

    def fake_dispatch(artifact_dir, plans, period_indices, **kwargs):
        seen.extend(plan.team_id for plan in plans)
        raise RuntimeError("stop after collection")

    monkeypatch.setattr("ercot_game.batch_evaluation._dispatch_plans", fake_dispatch)
    with pytest.raises(RuntimeError, match="stop after collection"):
        evaluate_csv_batch(submissions, artifact_dir=PACKAGE, horizon=120, rules=rules, energy_cost_enabled=False)
    assert seen == ["team-b"]


# --- Submission 2 base load ------------------------------------------------------


def test_site_net_withdrawal_is_load_minus_generation_and_battery_output():
    plan = TeamPlan(
        "team-a",
        connections=(ConnectionPlan("s1", "b1", 30.0, (1.0,) * 2), ConnectionPlan("s2", "b2", 10.0, (1.0,) * 2)),
        generators=(GeneratorPlan("g1", "s1", 10.0, 0.0),),
        storages=(StoragePlan("st1", "s1", 5.0, 20.0),),
    )
    periods = (
        SimpleNamespace(
            period_index=0,
            submitted_load_mw_by_team={"team-a": 20.0},  # projected to half
            generator_dispatch_mw_by_team={"team-a": {"g1": 4.0}},
            storage_discharge_mw_by_team={"team-a": {"st1": 2.0}},
            storage_charge_mw_by_team={"team-a": {"st1": 0.0}},
        ),
        SimpleNamespace(
            period_index=1,
            submitted_load_mw_by_team={"team-a": 20.0},
            generator_dispatch_mw_by_team={"team-a": {"g1": 0.0}},
            storage_discharge_mw_by_team={"team-a": {"st1": 0.0}},
            storage_charge_mw_by_team={"team-a": {"st1": 3.0}},
        ),
    )
    dispatch = SimpleNamespace(team_ids=("team-a",), periods=periods)
    evaluation = SimpleNamespace(
        team_scores=(SimpleNamespace(team_id="team-a", valid=True, feasible=True),),
        dispatch_records=(SimpleNamespace(status="feasible", dispatch=dispatch, attempted_team_ids=("team-a",)),),
        dispatch=dispatch,
        evaluated_plans=(plan,),
    )
    rows = site_net_withdrawal_rows(evaluation)
    by_key = {(row["site_id"], row["period_index"]): row["net_withdrawal_mw"] for row in rows}
    assert by_key == pytest.approx({("s1", 0): 15 - 4 - 2, ("s1", 1): 15 + 3, ("s2", 0): 5.0, ("s2", 1): 5.0})
    assert net_withdrawal_by_bus(rows, 2) == {"b1": pytest.approx([9.0, 18.0]), "b2": pytest.approx([5.0, 5.0])}
    assert site_ids_by_team(rows) == {"team-a": frozenset({"s1", "s2"})}


def test_derived_artifact_adds_withdrawal_and_floors_exports(tmp_path):
    pytest.importorskip("highspy")
    withdrawal = {"13": [5.0] * 120, "1": [-1.0] * 120}
    manifest = materialize_base_load_artifact(DEMO, withdrawal, tmp_path / "derived")
    assert manifest["validation_status"] == "passed"
    assert require_validated_block(tmp_path / "derived")["validation_status"] == "passed"
    base, derived = _demand_rows(DEMO), _demand_rows(tmp_path / "derived")
    assert [float(row["13"]) for row in derived] == pytest.approx([float(row["13"]) + 5.0 for row in base])
    assert [float(row["4"]) for row in derived] == pytest.approx([float(row["4"]) for row in base])
    # Bus 1 has no base load: the -1 MW export is floored at zero and recorded.
    assert all(float(row["1"]) == 0.0 for row in derived)
    assert len(manifest["submission_2_base_load"]["floored_points"]) == 120


def test_submission_two_runs_on_base_load_plus_submission_one_withdrawal(tmp_path, capsys):
    pytest.importorskip("highspy")
    s1 = tmp_path / "s1"
    s1.mkdir()
    _write_plan(s1 / "team-a.csv", "team-a", [("site-a1", "13", 20, 8, 2, 8)])
    s1_out = tmp_path / "s1_out"
    common = ["--artifact-dir", str(DEMO), "--rules", str(DEMO_RULES), "--horizon", "120"]
    assert batch_cli.main(
        ["run", "--submissions-dir", str(s1), "--output-dir", str(s1_out), "--submission-number", "1", "--energy-cost", "on", *common]
    ) == 0
    rows = read_site_net_withdrawal(s1_out)
    assert {row["site_id"] for row in rows} == {"site-a1"} and len(rows) == 120
    for row in rows:
        assert row["net_withdrawal_mw"] == pytest.approx(
            row["load_mw"] - row["generation_mw"] - row["storage_discharge_mw"] + row["storage_charge_mw"]
        )
    assert any(row["generation_mw"] > 0 or row["storage_discharge_mw"] > 0 for row in rows)

    s2 = tmp_path / "s2"
    s2.mkdir()
    _write_plan(s2 / "team-a.csv", "team-a", [("site-a1", "14", 10, 0, 0, 0)])  # reuses an S1 id
    _write_plan(s2 / "team-b.csv", "team-b", [("site-b1", "14", 10, 0, 0, 0)])
    s2_out = tmp_path / "s2_out"
    assert batch_cli.main(
        [
            "run", "--submissions-dir", str(s2), "--output-dir", str(s2_out), "--submission-number", "2",
            "--energy-cost", "on", "--base-load-from", str(s1_out), *common,
        ]
    ) == 0
    capsys.readouterr()
    derived = s2_out / "base_load_artifact"
    base = _demand_rows(DEMO)
    expected = {row["period_index"]: row["net_withdrawal_mw"] for row in rows}
    assert [float(row["13"]) for row in _demand_rows(derived)] == pytest.approx(
        [float(base[period]["13"]) + expected[period] for period in range(120)], abs=1e-5
    )
    evaluation = json.loads((s2_out / "evaluation.json").read_text(encoding="utf-8"))
    scores = {score["team_id"]: score for score in evaluation["team_scores"]}
    assert scores["team-b"]["feasible"] and scores["team-b"]["energy_cost"] > 0
    assert not scores["team-a"]["valid"]
    assert "already used in Submission 1: site-a1" in scores["team-a"]["failure_reason"]
    assert evaluation["rules"]["energy_cost_enabled"] is True


# --- CLI defaults ---------------------------------------------------------------------


def test_batch_cli_defaults_to_the_release_and_requires_an_energy_setting(tmp_path, monkeypatch, capsys):
    submissions = tmp_path / "subs"
    submissions.mkdir()
    _write_plan(submissions / "a.csv", "team-a", [("s1", "1001", 40, 20, 0, 0)])
    seen = []

    def fake_evaluate(*_args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(team_scores=(), competition_scope="test", source_period_indices=())

    monkeypatch.setattr(batch_cli, "evaluate_csv_batch", fake_evaluate)
    monkeypatch.setattr(batch_cli, "write_batch_outputs", lambda *_args, **_kwargs: None)
    base = ["run", "--submissions-dir", str(submissions), "--output-dir", str(tmp_path / "out")]
    assert batch_cli.main(base) == 2
    assert "--energy-cost on|off or --week" in capsys.readouterr().err
    assert batch_cli.main([*base, "--week", "2"]) == 0
    assert batch_cli.main([*base, "--week", "3"]) == 0
    assert batch_cli.main([*base, "--energy-cost", "off", "--week", "3"]) == 2
    capsys.readouterr()
    # Submission 2 must be scored on top of Submission 1's connected load.
    assert batch_cli.main([*base, "--week", "3", "--submission-number", "2"]) == 2
    assert "needs --base-load-from" in capsys.readouterr().err
    first, second = seen
    assert first["artifact_dir"].resolve() == PACKAGE.resolve()
    assert first["horizon"] == 120 and first["rules"].rules_version == "dispatch-scoring-representative-v1"
    assert (first["submission_number"], first["energy_cost_enabled"]) == (1, False)
    assert (second["submission_number"], second["energy_cost_enabled"]) == (1, True)


# --- week / submission structure ------------------------------------------------------


def _round_evaluator(calls: list[dict]):
    from ercot_game.batch_evaluation import _collect_evaluation_inputs, _expand_plans_for_horizon

    def evaluator(submissions, *, artifact_dir, horizon, rules, **kwargs):
        calls.append({"artifact_dir": Path(artifact_dir), **kwargs})
        collection = _collect_evaluation_inputs(
            submissions,
            horizon=horizon,
            default_generator_cost_per_mwh=100.0,
            reserved_site_ids_by_team=kwargs.get("reserved_site_ids_by_team"),
        )
        plans = _expand_plans_for_horizon([record.submission.plan for record in collection.accepted], horizon)
        periods = tuple(
            SimpleNamespace(
                period_index=index,
                submitted_load_mw_by_team={plan.team_id: sum(c.capacity_mw for c in plan.connections) for plan in plans},
                generator_dispatch_mw_by_team={plan.team_id: {} for plan in plans},
            )
            for index in range(horizon)
        )
        dispatch = SimpleNamespace(team_ids=tuple(plan.team_id for plan in plans), periods=periods)
        return SimpleNamespace(
            team_scores=tuple(SimpleNamespace(team_id=plan.team_id, valid=True, feasible=True) for plan in plans),
            dispatch_records=(SimpleNamespace(status="feasible", dispatch=dispatch, attempted_team_ids=dispatch.team_ids),),
            dispatch=dispatch,
            evaluated_plans=plans,
            projection_diagnostics=None,
        )

    return evaluator


def test_weeks_reset_and_submission_two_sees_submission_one_as_base_load(tmp_path):
    pytest.importorskip("highspy")
    from ercot_game.round_coordinator import evaluate_round

    rules = load_scoring_rules(DEMO_RULES, artifact_dir=DEMO, horizon=120)
    state_path = tmp_path / "state" / "game_state.json"
    calls: list[dict] = []
    evaluator = _round_evaluator(calls)

    def run(round_key: str, rows: dict[str, list[tuple]]):
        folder = tmp_path / round_key
        folder.mkdir()
        for team_id, sites in rows.items():
            _write_plan(folder / f"{team_id}.csv", team_id, sites)
        return evaluate_round(
            state_path=state_path,
            round_key=round_key,
            submissions=folder,
            artifact_dir=DEMO,
            horizon=120,
            rules=rules,
            evaluator=evaluator,
        )

    first = run("week-1-submission-1", {"team-a": [("s1", "13", 10, 0, 0, 0)]})
    assert first.state.carried_base_load_mw_by_bus == {"13": (10.0,) * 120}
    assert calls[-1]["energy_cost_enabled"] is False and calls[-1]["submission_number"] == 1
    assert calls[-1]["artifact_dir"] == DEMO

    second = run(
        "week-1-submission-2",
        {"team-a": [("s1", "14", 5, 0, 0, 0)], "team-b": [("s2", "14", 5, 0, 0, 0)]},
    )
    derived = calls[-1]["artifact_dir"]
    assert derived == state_path.parent / "base_load" / "week-1-submission-2"
    assert calls[-1]["reserved_site_ids_by_team"] == {"team-a": frozenset({"s1"})}
    base = _demand_rows(DEMO)
    assert [float(row["13"]) for row in _demand_rows(derived)] == pytest.approx(
        [float(row["13"]) + 10.0 for row in base]
    )
    # The colliding team-a file never enters the ledger; team-b's new site does.
    assert set(second.state.asset_ledger.team("team-a").sites) == {"s1"}
    assert set(second.state.asset_ledger.team("team-b").sites) == {"s2"}
    assert second.submission_number == 2 and second.week_id == "week-1"

    third = run("week-2-submission-1", {"team-a": [("s9", "4", 1, 0, 0, 0)]})
    assert third.ledger_reset
    assert calls[-1]["energy_cost_enabled"] is False
    assert third.state.carried_base_load_mw_by_bus == {"4": (1.0,) * 120}
    assert third.state.asset_ledger.team_ids() == ("team-a",)
    run("week-2-submission-2", {"team-a": [("s10", "4", 1, 0, 0, 0)]})
    run("week-3-submission-1", {"team-a": [("s1", "4", 1, 0, 0, 0)]})
    assert calls[-1]["energy_cost_enabled"] is True and calls[-1]["artifact_dir"] == DEMO


def test_classroom_final_score_sums_the_four_graded_submissions(tmp_path):
    pytest.importorskip("highspy")

    from ercot_game.batch_evaluation import TeamScore
    from ercot_game.round_coordinator import ClassroomRoundInput, evaluate_classroom

    rules = load_scoring_rules(DEMO_RULES, artifact_dir=DEMO, horizon=120)
    calls: list[dict] = []
    inner = _round_evaluator(calls)
    points = iter([1.0, 2.0, 10.0, 20.0, 100.0, 200.0])

    def evaluator(submissions, **kwargs):
        evaluation = inner(submissions, **kwargs)
        value = next(points)
        evaluation.team_scores = tuple(
            TeamScore(
                team_id=score.team_id, rank=0, valid=True, feasible=True, score=value,
                served_load_mwh=0.0, it_value=value, energy_cost=0.0, generator_operating_cost=0.0,
                generator_capital_cost=0.0, site_cost=0.0, competition_scope="joint",
            )
            for score in evaluation.team_scores
        )
        return evaluation

    rounds = []
    for week in (1, 2, 3):
        for submission in (1, 2):
            key = f"week-{week}-submission-{submission}"
            folder = tmp_path / key
            folder.mkdir()
            _write_plan(folder / "team-a.csv", "team-a", [(f"w{week}s{submission}", "13", 2, 0, 0, 0)])
            rounds.append(ClassroomRoundInput(key, folder, DEMO, 120, rules))
    result = evaluate_classroom(state_path=tmp_path / "state.json", rounds=rounds, evaluator=evaluator)

    assert [call["energy_cost_enabled"] for call in calls] == [False, False, False, False, True, True]
    assert [ranking.feedback_only for ranking in result.weekly_rankings] == [True, False, False]
    assert result.final_rankings[0].score == pytest.approx(10 + 20 + 100 + 200)
    assert result.state.next_round_key is None


def test_classroom_manifest_reads_the_horizon_from_the_representative_package(tmp_path):
    rounds = [
        {
            "round_key": f"week-{week}-submission-{submission}",
            "artifact_dir": str(PACKAGE),
            "rules": str(RULES),
            "submissions_dir": f"w{week}s{submission}",
        }
        for week in (1, 2, 3)
        for submission in (1, 2)
    ]
    manifest = tmp_path / "classroom.json"
    manifest.write_text(json.dumps({"rounds": rounds}), encoding="utf-8")
    inputs = batch_cli._classroom_round_inputs(manifest)
    assert [item.horizon for item in inputs] == [120] * 6
    assert inputs[0].rules.rules_version == "dispatch-scoring-representative-v1"
