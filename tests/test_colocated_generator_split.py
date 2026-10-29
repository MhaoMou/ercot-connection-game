"""Deterministic split of private generation among co-located team generators."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("highspy")

from ercot_game.batch_evaluation import generator_energy_mwh_by_day
from ercot_game.csv_submission import TEAM_GENERATOR_COST_CURVE
from ercot_game.models import ConnectionPlan, GeneratorPlan, TeamPlan
from tools.activsg2000 import plan_adapter
from tools.activsg2000.dcopf import clear_prepared_artifact_cache
from tools.activsg2000.plan_adapter import evaluate_plans_with_prepared_dcopf

DAYS = 2
HORIZON = 24 * DAYS
PERIODS = tuple(range(HORIZON))


def _artifact(root: Path) -> Path:
    """Bus 1 (cheap grid) -- 100 MW line -- bus 2 (sites); hosting dips to 75 MW at 18-19h."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "bus.csv").write_text("bus_id,type\n1,3\n2,1\n", encoding="utf-8")
    (root / "bus_load_base.csv").write_text("bus_id,base_load_mw\n1,0.0\n2,0.0\n", encoding="utf-8")
    (root / "branch_limits.csv").write_text(
        "branch_id,from_bus_id,to_bus_id,reactance_pu,thermal_limit_mva,status\nbr1,1,2,0.1,100.0,1\n",
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
        f"{t},0.0,{25.0 if t % 24 in (18, 19) else 0.0}" for t in PERIODS
    ]
    (root / "demand_bus.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    clear_prepared_artifact_cache()
    return root


def _plan(team_id: str, connection_mw: float, generator_mw: float, bus_id: str = "2") -> TeamPlan:
    return TeamPlan(
        team_id=team_id,
        connections=(ConnectionPlan("site-1", bus_id, connection_mw, (1.0,) * HORIZON),),
        generators=(GeneratorPlan("gen-1", "site-1", generator_mw, 0.0),),
    )


def _fuel(amount: float, capacity: float) -> float:
    cost, remaining = 0.0, amount
    for fraction, price in TEAM_GENERATOR_COST_CURVE:
        take = min(remaining, fraction * capacity)
        cost += take * price
        remaining -= take
    return cost


def _team_metrics(dispatch, plan: TeamPlan) -> dict[str, float]:
    capacity = plan.generators[0].capacity_mw
    fuel = energy_cost = generation = 0.0
    for period in dispatch.periods:
        amount = period.generator_dispatch_mw_by_team[plan.team_id]["gen-1"]
        generation += amount
        fuel += _fuel(amount, capacity)
        lmp = period.dcopf.balance_dual_by_bus
        energy_cost += sum(
            mw * max(0.0, lmp[bus]) for bus, mw in period.grid_purchase_mw_by_team_by_bus[plan.team_id].items()
        )
    return {"fuel": fuel, "energy_cost": energy_cost, "generation": generation}


def _bus_total(period, bus_id="2") -> float:
    return sum(
        mw for generator_id, mw in period.dcopf.generation_mw.items() if generator_id.startswith("student:")
    )


ROUTES = (pytest.param({}, id="hourly"),)


@pytest.mark.parametrize("kwargs", ROUTES)
def test_identical_colocated_teams_get_identical_outcomes(tmp_path, monkeypatch, kwargs) -> None:
    artifact = _artifact(tmp_path / "toy")
    plans = (_plan("team-a", 50.0, 30.0), _plan("team-b", 50.0, 30.0))
    solved = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS, **kwargs)

    # Reference: the solver's own (degenerate) split.
    monkeypatch.setattr(
        plan_adapter, "_colocated_generator_tie_break", lambda dcopfs, *a, **k: (tuple(dcopfs), ())
    )
    raw = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS, **kwargs)
    raw_a, raw_b = (_team_metrics(raw, plan) for plan in plans)
    # The split is degenerate: only the bus total is pinned down.
    assert raw_a["generation"] + raw_b["generation"] == pytest.approx(50.0 * DAYS)

    a, b = (_team_metrics(solved, plan) for plan in plans)
    assert a == pytest.approx(b, abs=1e-6)
    assert a["generation"] == pytest.approx(25.0 * DAYS)
    assert solved.generator_split_fallbacks == ()
    # Bus totals, LMPs, flows and the objective are unchanged by the tie-break.
    for new, old in zip(solved.periods, raw.periods):
        assert _bus_total(new) == pytest.approx(_bus_total(old), abs=1e-9)
        assert new.dcopf.balance_dual_by_bus == old.dcopf.balance_dual_by_bus
        assert new.dcopf.flow_mw_by_branch == old.dcopf.flow_mw_by_branch
        assert new.dcopf.objective_cost == old.dcopf.objective_cost
        new_cost = sum(_fuel(new.generator_dispatch_mw_by_team[p.team_id]["gen-1"], 30.0) for p in plans)
        old_cost = sum(_fuel(old.generator_dispatch_mw_by_team[p.team_id]["gen-1"], 30.0) for p in plans)
        assert new_cost == pytest.approx(old_cost, abs=1e-6)
    for plan in plans:
        assert generator_energy_mwh_by_day(solved, plan.team_id)["gen-1"] == pytest.approx([25.0] * DAYS)


@pytest.mark.parametrize("kwargs", ROUTES)
def test_unequal_capacities_get_proportional_shares(tmp_path, kwargs) -> None:
    artifact = _artifact(tmp_path / "toy")
    plans = (_plan("team-a", 50.0, 40.0), _plan("team-b", 50.0, 20.0))
    dispatch = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS, **kwargs)
    for period in dispatch.periods:
        a = period.generator_dispatch_mw_by_team["team-a"]["gen-1"]
        b = period.generator_dispatch_mw_by_team["team-b"]["gen-1"]
        assert a == pytest.approx(2.0 * b, abs=1e-9)
        assert a + b == pytest.approx(25.0 if period.period_index % 24 in (18, 19) else 0.0, abs=1e-6)


def test_own_load_cap_redistributes_to_the_other_generator(tmp_path) -> None:
    # team-a's site is only 10 MW, so its generator may serve at most 10 MW;
    # proportional shares (25 x 30/60 = 12.5 each) are water-filled to 10/15.
    artifact = _artifact(tmp_path / "toy")
    plans = (_plan("team-a", 10.0, 30.0), _plan("team-b", 90.0, 30.0))
    dispatch = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS)
    assert dispatch.generator_split_fallbacks == ()
    for period in dispatch.periods:
        a = period.generator_dispatch_mw_by_team["team-a"]["gen-1"]
        b = period.generator_dispatch_mw_by_team["team-b"]["gen-1"]
        if period.period_index % 24 in (18, 19):
            assert (a, b) == pytest.approx((10.0, 15.0), abs=1e-6)
        else:
            assert a + b == pytest.approx(0.0, abs=1e-9)
        assert a <= 10.0 + 1e-9
