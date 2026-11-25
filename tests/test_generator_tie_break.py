"""Pro-rata split of team generation across buses, independent of site IDs."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("highspy")

from ercot_game.csv_submission import TEAM_GENERATOR_COST_CURVE
from ercot_game.models import ConnectionPlan, GeneratorPlan, StoragePlan, TeamPlan
from tools.activsg2000.dcopf import clear_prepared_artifact_cache
from tools.activsg2000.plan_adapter import evaluate_plans_with_prepared_dcopf

DAYS = 1
HORIZON = 24 * DAYS
PERIODS = tuple(range(HORIZON))
GRID_MW = 75.0
LINE_MW = 1000.0


def _artifact(root: Path, line_13_mw: float = LINE_MW) -> Path:
    """Bus 1 (grid, 75 MW) feeds buses 2 and 3, where the sites are."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "bus.csv").write_text("bus_id,type\n1,3\n2,1\n3,1\n", encoding="utf-8")
    (root / "bus_load_base.csv").write_text("bus_id,base_load_mw\n1,0.0\n2,0.0\n3,0.0\n", encoding="utf-8")
    (root / "branch_limits.csv").write_text(
        "branch_id,from_bus_id,to_bus_id,reactance_pu,thermal_limit_mva,status\n"
        f"br12,1,2,0.1,{LINE_MW},1\nbr13,1,3,0.1,{line_13_mw},1\n",
        encoding="utf-8",
    )
    (root / "dcline.csv").write_text("status,from_bus_id,to_bus_id,Pt\n", encoding="utf-8")
    generators = (
        "generator_id,bus_id,p_min_mw,p_max_mw,marginal_cost_c1_per_mwh,status,profile_type\n"
        f"g1,1,0.0,{GRID_MW},20.0,1,thermal\n"
    )
    (root / "generator_catalog.csv").write_text(generators, encoding="utf-8")
    (root / "generator_limits.csv").write_text(generators, encoding="utf-8")
    rows = ["period,1,2,3"] + [f"{t},0.0,0.0,0.0" for t in PERIODS]
    (root / "demand_bus.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    clear_prepared_artifact_cache()
    return root


def _site(site_id: str, bus_id: str, connection_mw: float, generator_mw: float, generator_id: str):
    return (
        ConnectionPlan(site_id, bus_id, connection_mw, (1.0,) * HORIZON),
        GeneratorPlan(generator_id, site_id, generator_mw, 0.0),
    )


def _plan(team_id: str, *sites, storages=()) -> TeamPlan:
    return TeamPlan(
        team_id=team_id,
        connections=tuple(site[0] for site in sites),
        generators=tuple(site[1] for site in sites),
        storages=tuple(storages),
    )


def _fuel(amount: float, capacity: float) -> float:
    cost, remaining = 0.0, amount
    for fraction, price in TEAM_GENERATOR_COST_CURVE:
        take = min(remaining, fraction * capacity)
        cost += take * price
        remaining -= take
    return cost


def _outputs_by_bus(dispatch, plans) -> list[dict[tuple[str, str], float]]:
    """Per period: {(team, bus): generator output}, keyed by bus, not by ID."""
    bus_of = {
        (plan.team_id, generator.generator_id): next(
            c.bus_id for c in plan.connections if c.connection_id == generator.connection_id
        )
        for plan in plans
        for generator in plan.generators
    }
    return [
        {
            (team_id, bus_of[(team_id, generator_id)]): amount
            for team_id, outputs in period.generator_dispatch_mw_by_team.items()
            for generator_id, amount in outputs.items()
        }
        for period in dispatch.periods
    ]


def test_equal_generators_at_different_buses_share_equally(tmp_path) -> None:
    artifact = _artifact(tmp_path / "toy")
    plans = (
        _plan("team-a", _site("s", "2", 50.0, 30.0, "g")),
        _plan("team-b", _site("s", "3", 50.0, 30.0, "g")),
    )
    dispatch = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS)
    assert dispatch.generator_split_fallbacks == ()
    for period in dispatch.periods:
        a = period.generator_dispatch_mw_by_team["team-a"]["g"]
        b = period.generator_dispatch_mw_by_team["team-b"]["g"]
        # 100 MW of load, 75 MW of grid: the 25 MW gap is split evenly.
        assert (a, b) == pytest.approx((12.5, 12.5), abs=1e-6)


def test_unequal_capacities_at_different_buses_split_pro_rata(tmp_path) -> None:
    artifact = _artifact(tmp_path / "toy")
    plans = (
        _plan("team-a", _site("s", "2", 50.0, 40.0, "g")),
        _plan("team-b", _site("s", "3", 50.0, 20.0, "g")),
    )
    dispatch = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS)
    for period in dispatch.periods:
        a = period.generator_dispatch_mw_by_team["team-a"]["g"]
        b = period.generator_dispatch_mw_by_team["team-b"]["g"]
        assert a == pytest.approx(2.0 * b, abs=1e-6)
        assert a + b == pytest.approx(25.0, abs=1e-6)


def test_split_keeps_cost_and_line_limits(tmp_path) -> None:
    # Bus 3's line carries at most 35 MW, so team-b must cover at least 15 MW
    # itself: the even split (12.5 each) is not feasible, and the closest
    # feasible split is 10 / 15.  The cost stays at the LP optimum.
    artifact = _artifact(tmp_path / "toy", line_13_mw=35.0)
    plans = (
        _plan("team-a", _site("s", "2", 50.0, 30.0, "g")),
        _plan("team-b", _site("s", "3", 50.0, 30.0, "g")),
    )
    dispatch = evaluate_plans_with_prepared_dcopf(artifact, plans, period_indices=PERIODS)
    for period in dispatch.periods:
        a = period.generator_dispatch_mw_by_team["team-a"]["g"]
        b = period.generator_dispatch_mw_by_team["team-b"]["g"]
        assert a + b == pytest.approx(25.0, abs=1e-6)
        assert (a, b) == pytest.approx((10.0, 15.0), abs=1e-6)
        assert abs(period.dcopf.flow_mw_by_branch["br13"]) <= 35.0 + 1e-6
        # Both 80 $/MWh segments (7.5 MW each) are full; 10 MW comes from the 150 $/MWh ones.
        assert _fuel(a, 30.0) + _fuel(b, 30.0) == pytest.approx(15.0 * 80.0 + 10.0 * 150.0, abs=1e-4)


@pytest.mark.parametrize(
    "kwargs",
    (
        pytest.param({}, id="hourly"),
        pytest.param(
            {"storage_solver": "monolithic", "storage_boundary_mode": "daily_exact_cycle"}, id="storage"
        ),
    ),
)
def test_relabelling_sites_does_not_change_any_outcome(tmp_path, kwargs) -> None:
    artifact = _artifact(tmp_path / "toy")
    storages = ()
    if kwargs:
        storages = (StoragePlan("bat", "x-site", 5.0, 20.0, 10.0),)  # re-attached below

    def plans(first: str, second: str):
        # team-a has two sites; swapping their IDs reorders its generators
        # in the LP without changing any bus or capacity.
        a = _plan(
            "team-a",
            _site(first, "2", 30.0, 20.0, f"gen-{first}"),
            _site(second, "3", 30.0, 10.0, f"gen-{second}"),
            storages=tuple(
                StoragePlan(s.storage_id, first, s.power_mw, s.energy_mwh, s.initial_state_of_charge_mwh)
                for s in storages
            ),
        )
        b = _plan("team-b", _site("s", "3", 40.0, 30.0, "g"))
        return (a, b)

    one = plans("x-site", "y-site")
    two = plans("y-site", "x-site")  # same buses and sizes, labels swapped
    first = evaluate_plans_with_prepared_dcopf(artifact, one, period_indices=PERIODS, **kwargs)
    second = evaluate_plans_with_prepared_dcopf(artifact, two, period_indices=PERIODS, **kwargs)
    # Compare horizon totals per (team, bus): with storage, the battery's
    # schedule is itself cost-neutral between hours, but each team's
    # generation and grid purchase over the horizon are what the score uses.
    def totals(dispatch, plans):
        out: dict[tuple[str, str], float] = {}
        for period in _outputs_by_bus(dispatch, plans):
            for key, amount in period.items():
                out[key] = out.get(key, 0.0) + amount
        for period in dispatch.periods:
            for team_id, amount in period.grid_purchase_mw_by_team.items():
                out[(team_id, "grid")] = out.get((team_id, "grid"), 0.0) + amount
        return out

    x, y = totals(first, one), totals(second, two)
    assert x.keys() == y.keys()
    for key in x:
        assert x[key] == pytest.approx(y[key], abs=1e-6), key
