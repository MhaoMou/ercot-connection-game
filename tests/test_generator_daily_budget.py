"""Daily run-hour budget of team generators (generator_daily_energy_hours)."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

pytest.importorskip("highspy")

from ercot_game.batch_evaluation import (
    BatchScoringRules,
    _fair_continuous_projection,
    generator_energy_mwh_by_day,
    load_scoring_rules,
)
from ercot_game.models import ConnectionPlan, GeneratorPlan, TeamPlan
from tools.activsg2000.dcopf import (
    Branch,
    Bus,
    DCOPFInfeasible,
    Generator,
    clear_prepared_artifact_cache,
    solve_dcopf_horizon,
)
from tools.activsg2000.plan_adapter import evaluate_plans_with_prepared_dcopf

REPO_ROOT = Path(__file__).resolve().parents[1]
DAYS = 2
HORIZON = 24 * DAYS
PERIODS = tuple(range(HORIZON))


def _toy_artifact(root: Path, base_load_at_site_bus) -> Path:
    """Two buses joined by one 100 MW line; the site sits at bus 2.

    ``base_load_at_site_bus(t)`` is the non-team demand at bus 2, so the
    hosting capacity of bus 2 is 100 MW minus that demand.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "bus.csv").write_text("bus_id,type\n1,3\n2,1\n", encoding="utf-8")
    (root / "bus_load_base.csv").write_text(
        "bus_id,base_load_mw\n1,0.0\n2,0.0\n", encoding="utf-8"
    )
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
        f"{period},0.0,{float(base_load_at_site_bus(period))}" for period in PERIODS
    ]
    (root / "demand_bus.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    clear_prepared_artifact_cache()
    return root


def _dip_artifact(tmp_path: Path) -> Path:
    # Hosting capacity dips to 75 MW for two evening hours a day.
    return _toy_artifact(tmp_path / "dip", lambda t: 25.0 if t % 24 in (18, 19) else 0.0)


def _always_artifact(tmp_path: Path) -> Path:
    # Hosting capacity is 70 MW in every hour.
    return _toy_artifact(tmp_path / "always", lambda t: 30.0)


def _plan(connection_mw: float, generator_mw: float, team_id: str = "team-a") -> TeamPlan:
    generators = (
        (GeneratorPlan("gen-1", "site-1", generator_mw, 0.0),) if generator_mw > 0 else ()
    )
    return TeamPlan(
        team_id=team_id,
        connections=(ConnectionPlan("site-1", "2", connection_mw, (1.0,) * HORIZON),),
        generators=generators,
    )


def _daily_generation(dispatch, team_id="team-a", generator_id="gen-1"):
    return generator_energy_mwh_by_day(dispatch, team_id)[generator_id]


def test_horizon_energy_limit_caps_a_cheap_generator() -> None:
    # A cheap generator would run every period; the energy limit stops it.
    buses = (Bus("a", 10.0, reference=True),)
    generators = (
        Generator("grid", "a", 0.0, 100.0, 50.0),
        Generator("team", "a", 0.0, 10.0, 1.0),
    )
    periods = ((buses, generators, ()),) * 24
    unlimited = solve_dcopf_horizon(periods=periods)
    assert sum(p.generation_mw["team"] for p in unlimited.periods) == pytest.approx(240.0)
    limited = solve_dcopf_horizon(
        periods=periods,
        generator_energy_limits_mwh={"team": (("team",), 20.0)},
    )
    assert sum(p.generation_mw["team"] for p in limited.periods) == pytest.approx(20.0)


def test_budget_is_enforced_every_day(tmp_path) -> None:
    artifact = _dip_artifact(tmp_path)
    plan = _plan(100.0, 30.0)
    # The site needs 25 MW of private generation in two hours a day (50 MWh).
    dispatch = evaluate_plans_with_prepared_dcopf(
        artifact, (plan,), period_indices=PERIODS, generator_daily_energy_hours=2.0
    )
    daily = _daily_generation(dispatch)
    assert len(daily) == DAYS
    for energy in daily:
        assert 50.0 - 1e-6 <= energy <= 2.0 * 30.0 + 1e-6
    # One run hour a day (30 MWh) cannot cover the 50 MWh shortfall.
    with pytest.raises(DCOPFInfeasible):
        evaluate_plans_with_prepared_dcopf(
            artifact, (plan,), period_indices=PERIODS, generator_daily_energy_hours=1.0
        )
    # Without a budget the same plan is feasible hour by hour.
    unbudgeted = evaluate_plans_with_prepared_dcopf(artifact, (plan,), period_indices=PERIODS)
    assert len(unbudgeted.periods) == HORIZON


def test_null_budget_reproduces_hourly_dispatch_exactly(tmp_path) -> None:
    artifact = _dip_artifact(tmp_path)
    plan = _plan(100.0, 30.0)
    default = evaluate_plans_with_prepared_dcopf(artifact, (plan,), period_indices=PERIODS)
    explicit_none = evaluate_plans_with_prepared_dcopf(
        artifact, (plan,), period_indices=PERIODS, generator_daily_energy_hours=None
    )
    assert explicit_none == default
    # A non-binding 24 h budget goes through the daily LP and finds the same dispatch.
    loose = evaluate_plans_with_prepared_dcopf(
        artifact, (plan,), period_indices=PERIODS, generator_daily_energy_hours=24.0
    )
    for left, right in zip(default.periods, loose.periods):
        assert left.submitted_load_mw_by_team == right.submitted_load_mw_by_team
        assert left.generator_dispatch_mw_by_team["team-a"]["gen-1"] == pytest.approx(
            right.generator_dispatch_mw_by_team["team-a"]["gen-1"], abs=1e-6
        )


def _alpha(artifact: Path, plan: TeamPlan, hours: float | None) -> float:
    result = _fair_continuous_projection(
        artifact,
        (plan,),
        PERIODS,
        PERIODS,
        generator_daily_energy_hours=hours,
    )
    assert result is not None
    return result.service_fraction_by_team[plan.team_id]


def test_projection_uses_the_budget_dip_site_keeps_its_generator_benefit(tmp_path) -> None:
    artifact = _dip_artifact(tmp_path)
    no_generator = _alpha(artifact, _plan(100.0, 0.0), None)
    budgeted = _alpha(artifact, _plan(100.0, 30.0), 2.0)
    assert no_generator == pytest.approx(0.75, abs=1e-3)
    # Two short dips fit in the 2 h/day budget: the site is served in full.
    assert budgeted == pytest.approx(1.0, abs=1e-6)


def test_projection_uses_the_budget_always_limited_site_gets_at_most_h_over_24(tmp_path) -> None:
    artifact = _always_artifact(tmp_path)
    hours = 2.0
    no_generator = _alpha(artifact, _plan(100.0, 0.0), None)
    unbudgeted = _alpha(artifact, _plan(100.0, 30.0), None)
    budgeted = _alpha(artifact, _plan(100.0, 30.0), hours)
    assert no_generator == pytest.approx(0.70, abs=1e-3)
    assert unbudgeted == pytest.approx(1.0, abs=1e-3)
    benefit = unbudgeted - no_generator
    budgeted_benefit = budgeted - no_generator
    assert budgeted_benefit > 0.0
    assert budgeted_benefit <= hours / 24.0 * benefit + 2e-3


def test_rules_field_is_optional_and_validated(tmp_path) -> None:
    assert BatchScoringRules(rules_version="x").generator_daily_energy_hours is None
    with pytest.raises(ValueError):
        BatchScoringRules(rules_version="x", generator_daily_energy_hours=-1.0)
    with pytest.raises(ValueError):
        BatchScoringRules(rules_version="x", generator_daily_energy_hours=25.0)
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"rules_version": "x"}), encoding="utf-8")
    assert load_scoring_rules(path).generator_daily_energy_hours is None
    path.write_text(
        json.dumps({"rules_version": "x", "generator_daily_energy_hours": None}),
        encoding="utf-8",
    )
    assert load_scoring_rules(path).generator_daily_energy_hours is None
    path.write_text(
        json.dumps({"rules_version": "x", "generator_daily_energy_hours": 2}),
        encoding="utf-8",
    )
    assert load_scoring_rules(path).generator_daily_energy_hours == 2.0


def test_released_rules_set_a_two_hour_budget_and_new_capital_cost() -> None:
    for name in (
        "dispatch_scoring_rules_representative_v1.json",
        "dispatch_scoring_rules_ieee14_demo_representative_v1.json",
    ):
        payload = json.loads((REPO_ROOT / "data" / "teaching" / name).read_text(encoding="utf-8"))
        assert payload["generator_daily_energy_hours"] == 2.0
        assert payload["generator_capital_cost_per_mw"] == 2_000_000.0
        assert payload["max_generator_to_connection_ratio"] == 0.5
        provenance = payload["generator_provenance"]
        assert "SB 6" in provenance["max_generator_to_connection_ratio_basis"]
        assert "730 h/yr" in provenance["daily_energy_basis"]


def test_student_preview_respects_the_budget(tmp_path) -> None:
    from ercot_game.student_preview import preview_plans

    artifact = _dip_artifact(tmp_path)
    rules = BatchScoringRules(
        rules_version="x",
        it_value_per_mwh=(1000.0,) * HORIZON,
        energy_price_per_mwh=(0.0,) * HORIZON,
        generator_daily_energy_hours=2.0,
    )
    plan = _plan(70.0, 30.0)
    exact = preview_plans(
        (plan,), artifact_dir=artifact, horizon=HORIZON, rules=rules,
        submission_number=1, preview_stride=1,
    )
    assert exact.generator_dispatch_policy == "daily_budget_2h_exact"
    assert max(_daily_generation(exact.dispatch)) <= 60.0 + 1e-6
    sampled = preview_plans(
        (plan,), artifact_dir=artifact, horizon=HORIZON, rules=rules,
        submission_number=1, preview_stride=6,
    )
    assert "derated" in sampled.generator_dispatch_policy
    for period in sampled.dispatch.periods:
        assert period.generator_dispatch_mw_by_team["team-a"]["gen-1"] <= 30.0 * 2.0 / 24.0 + 1e-6
    unbudgeted = preview_plans(
        (plan,), artifact_dir=artifact, horizon=HORIZON,
        rules=replace(rules, generator_daily_energy_hours=None),
        submission_number=1, preview_stride=1,
    )
    assert unbudgeted.generator_dispatch_policy == "no_daily_budget"


def _monolithic(artifact, plans, **kwargs):
    return evaluate_plans_with_prepared_dcopf(
        artifact, plans, period_indices=PERIODS, storage_solver="monolithic", **kwargs
    )


def _assert_dispatch_matches(benders, monolithic) -> None:
    for left, right in zip(benders.periods, monolithic.periods):
        assert left.submitted_load_mw_by_team == right.submitted_load_mw_by_team
    for team_id in benders.team_ids:
        for generator_id, daily in generator_energy_mwh_by_day(benders, team_id).items():
            reference = generator_energy_mwh_by_day(monolithic, team_id)[generator_id]
            assert daily == pytest.approx(reference, abs=1e-6)
    total = sum(period.dcopf.objective_cost for period in benders.periods)
    reference = sum(period.dcopf.objective_cost for period in monolithic.periods)
    assert total == pytest.approx(reference, rel=1e-7)


def test_benders_budget_route_matches_monolithic_daily_lps(tmp_path) -> None:
    from ercot_game.models import StoragePlan

    artifact = _dip_artifact(tmp_path)
    plans = (
        _plan(70.0, 30.0, "team-a"),
        replace(
            _plan(20.0, 10.0, "team-b"),
            storages=(StoragePlan("battery", "site-1", 10.0, 40.0),),
        ),
    )
    benders = evaluate_plans_with_prepared_dcopf(
        artifact, plans, period_indices=PERIODS, generator_daily_energy_hours=2.0,
        storage_boundary_mode="daily_exact_cycle", storage_solver_backend="highs",
    )
    assert benders.solver_diagnostics.route == "benders_budgeted_generators"
    monolithic = _monolithic(
        artifact, plans, generator_daily_energy_hours=2.0, storage_boundary_mode="daily_exact_cycle"
    )
    _assert_dispatch_matches(benders, monolithic)


def test_benders_budget_route_proves_infeasibility_with_feasibility_cuts(tmp_path) -> None:
    artifact = _dip_artifact(tmp_path)
    plans = (_plan(100.0, 30.0, "team-a"), _plan(60.0, 10.0, "team-b"))
    with pytest.raises(DCOPFInfeasible):
        _monolithic(artifact, plans, generator_daily_energy_hours=1.0)
    with pytest.raises(DCOPFInfeasible):
        evaluate_plans_with_prepared_dcopf(
            artifact, plans, period_indices=PERIODS, generator_daily_energy_hours=1.0,
            storage_solver_backend="highs",
        )
