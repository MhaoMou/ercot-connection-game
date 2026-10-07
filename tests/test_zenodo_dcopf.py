from __future__ import annotations

import csv

import pytest

highspy = pytest.importorskip("highspy")

from tools.zenodo_texas.dcopf import (  # noqa: E402
    DCOPFInfeasible,
    DCOPFUnresolved,
    Branch,
    Bus,
    DCOPFResult,
    Generator,
    PreparedArtifact,
    _cached_network_index,
    load_prepared_artifact,
    solve_dcopf,
    solve_prepared_period,
)
import tools.zenodo_texas.dcopf as dcopf_module  # noqa: E402
from tools.zenodo_texas.plan_adapter import evaluate_plan_with_prepared_dcopf  # noqa: E402
from tools.zenodo_texas.plan_adapter import evaluate_plans_with_prepared_dcopf  # noqa: E402
from ercot_game.models import ConnectionPlan, GeneratorPlan, TeamPlan  # noqa: E402


def test_dcopf_dispatches_around_a_binding_branch():
    result = solve_dcopf(
        buses=(Bus("source", 0.0, reference=True), Bus("load", 80.0)),
        generators=(
            Generator("cheap", "source", 0.0, 80.0, 10.0),
            Generator("local", "load", 0.0, 80.0, 30.0),
        ),
        branches=(Branch("source-load", "source", "load", 0.01, 40.0),),
        base_mva=100.0,
    )

    assert result.status == "optimal"
    assert result.generation_mw == {"cheap": 40.0, "local": 40.0}
    assert result.flow_mw_by_branch["source-load"] == 40.0


def test_prepared_dispatch_uses_nameplate_capacity_for_renewables(monkeypatch):
    artifact = PreparedArtifact(
        buses_raw=(
            {"bus_id": "ref", "type": "3"},
            {"bus_id": "load", "type": "1"},
        ),
        demand_rows=({"ref": "0", "load": "1"},),
        generators_raw=(
            {
                "generator_id": "solar-1",
                "bus_id": "ref",
                "p_min_mw": "0",
                "p_max_mw": "10",
                "marginal_cost_c1_per_mwh": "0",
                "technology": "solar",
                "status": "1",
            },
        ),
        branches_raw=(),
        dcline_raw=(),
        renewable_profile_mw_by_generator={"solar-1": (0.0,)},
    )
    captured = {}

    def fake_load(_root):
        return artifact

    def fake_solve(**kwargs):
        captured["generators"] = kwargs["generators"]
        return DCOPFResult("optimal", 0.0, {}, {"ref": 0.0, "load": 0.0}, {}, {"ref": 0.0, "load": 0.0})

    monkeypatch.setattr(dcopf_module, "load_prepared_artifact", fake_load)
    monkeypatch.setattr(dcopf_module, "solve_dcopf", fake_solve)
    solve_prepared_period("unused", period_index=0)

    assert captured["generators"][0].p_max_mw == 10.0


def test_network_index_is_cached_for_repeated_static_topology():
    branches = (Branch("source-load", "source", "load", 0.01, 40.0),)
    first = _cached_network_index(branches, (Generator("g", "source", 0.0, 1.0, 1.0),))
    second = _cached_network_index(branches, (Generator("g", "source", 0.0, 1.0, 1.0),))

    assert first is second


def test_dcopf_raises_when_fixed_load_exceeds_available_supply():
    with pytest.raises(DCOPFInfeasible, match="infeasible"):
        solve_dcopf(
            buses=(Bus("source", 0.0, reference=True), Bus("load", 80.0)),
            generators=(Generator("small", "source", 0.0, 20.0, 10.0),),
            branches=(Branch("source-load", "source", "load", 1.0, 100.0),),
        )


def test_dcopf_accepts_fixed_boundary_imports():
    result = solve_dcopf(
        buses=(Bus("boundary", 0.0, reference=True), Bus("load", 80.0)),
        generators=(),
        branches=(Branch("boundary-load", "boundary", "load", 1.0, 100.0),),
        fixed_injection_mw_by_bus={"boundary": 80.0},
    )

    assert result.status == "optimal"
    assert result.objective_cost == 0.0
    assert result.flow_mw_by_branch["boundary-load"] == 80.0


def test_dcopf_computes_flows_before_rounding_angles():
    result = solve_dcopf(
        buses=(Bus("source", 0.0, reference=True), Bus("load", 1.0)),
        generators=(Generator("source-gen", "source", 0.0, 1.0, 10.0),),
        branches=(Branch("source-load", "source", "load", 3_000_000_000.0, 1.0),),
        base_mva=1.0,
    )

    assert result.flow_mw_by_branch["source-load"] == pytest.approx(1.0)


def test_dcopf_reports_a_feasible_empty_model_separately():
    result = solve_dcopf(
        buses=(Bus("empty", 0.0, reference=True),),
        generators=(),
        branches=(),
    )

    assert result.status == "empty"
    assert result.objective_cost == 0.0
    assert result.generation_mw == {}
    assert result.flow_mw_by_branch == {}


def test_dcopf_reports_unresolved_solver_status_separately(monkeypatch):
    class FakeStatus:
        kOptimal = object()
        kModelEmpty = object()
        kInfeasible = object()
        kSolveError = object()

    class FakeVariable:
        index = 0

    class FakeHighs:
        def setOptionValue(self, *_args):
            return None

        def addVariable(self, **_kwargs):
            return FakeVariable()

        def addRow(self, *_args):
            return None

        def run(self):
            return None

        def getModelStatus(self):
            return FakeStatus.kSolveError

    monkeypatch.setattr(
        dcopf_module,
        "_highs",
        lambda: (FakeHighs, FakeStatus, 1.0e100),
    )

    with pytest.raises(DCOPFUnresolved, match="unresolved"):
        solve_dcopf(
            buses=(Bus("empty", 0.0, reference=True),),
            generators=(),
            branches=(),
        )


def test_dcopf_does_not_create_load_shedding_variables():
    with pytest.raises(DCOPFInfeasible, match="infeasible"):
        solve_dcopf(
            buses=(Bus("source", 0.0, reference=True), Bus("load", 80.0)),
            generators=(Generator("small", "source", 0.0, 20.0, 10.0),),
            branches=(Branch("source-load", "source", "load", 1.0, 100.0),),
        )


def test_plan_adapter_adds_submitted_load_and_candidate_generator():
    plan = TeamPlan(
        "team-1",
        connections=(ConnectionPlan("site-1", "3002054", (), 2.0, (1.0,)),),
        generators=(GeneratorPlan("gen-1", "site-1", 1.0, 5.0),),
    )

    result = evaluate_plan_with_prepared_dcopf(
        "data/processed/texas_dispatch_source_v1",
        plan,
        period_indices=(0,),
    )

    assert result.team_id == "team-1"
    assert result.periods[0].submitted_load_mw == 2.0
    assert result.total_submitted_load_mwh == 2.0
    assert "student:5:gen-1" in result.periods[0].dcopf.generation_mw


def test_batch_adapter_solves_teams_jointly():
    plans = tuple(
        TeamPlan(
            team_id,
            connections=(ConnectionPlan(f"site-{team_id}", "3002054", (), 2.0, (1.0,)),),
            generators=(),
        )
        for team_id in ("team-1", "team-2")
    )

    result = evaluate_plans_with_prepared_dcopf(
        "data/processed/texas_dispatch_source_v1",
        plans,
        period_indices=(0,),
    )

    assert result.team_ids == ("team-1", "team-2")
    assert result.periods[0].submitted_load_mw_by_team == {"team-1": 2.0, "team-2": 2.0}


def _batch_plan(team_id: str, generator_ids: tuple[str, ...]) -> TeamPlan:
    return TeamPlan(
        team_id,
        connections=(ConnectionPlan(f"site-{team_id}", "3002054", (), 2.0, (1.0,)),),
        generators=tuple(
            GeneratorPlan(generator_id, f"site-{team_id}", 1.0, 5.0)
            for generator_id in generator_ids
        ),
    )


def test_batch_adapter_is_invariant_to_plan_and_generator_input_order(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        calls.append(
            (
                period_index,
                dict(additional_demand_mw_by_bus),
                tuple(generator.generator_id for generator in additional_generators),
            )
        )
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={
                generator.generator_id: float(index)
                for index, generator in enumerate(additional_generators)
            },
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plans = (
        _batch_plan("team-b", ("gen-z", "gen-a")),
        _batch_plan("team-a", ("gen-z", "gen-a")),
    )

    forward = evaluate_plans_with_prepared_dcopf("unused", plans, period_indices=(0,))
    forward_calls = calls[:]
    calls.clear()
    reversed_input = evaluate_plans_with_prepared_dcopf(
        "unused",
        tuple(
            _batch_plan(plan.team_id, tuple(reversed(tuple(generator.generator_id for generator in plan.generators))))
            for plan in reversed(plans)
        ),
        period_indices=(0,),
    )

    assert reversed_input == forward
    assert calls == forward_calls


def test_batch_adapter_uses_collision_safe_deterministic_ids_for_colon_names(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        generator_ids = tuple(generator.generator_id for generator in additional_generators)
        assert len(generator_ids) == len(set(generator_ids))
        calls.append(generator_ids)
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={generator_id: 1.0 for generator_id in generator_ids},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plans = (
        _batch_plan("team", ("alpha:gen",)),
        _batch_plan("team:alpha", ("gen",)),
    )

    result = evaluate_plans_with_prepared_dcopf("unused", plans, period_indices=(0,))
    reversed_result = evaluate_plans_with_prepared_dcopf(
        "unused", tuple(reversed(plans)), period_indices=(0,)
    )

    assert result == reversed_result
    assert calls[0] == calls[1]
    assert len(calls[0]) == 2


def test_real_solver_uses_solar_nameplate_when_profile_is_zero(tmp_path):
    def write_table(name, fieldnames, rows):
        with (tmp_path / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    write_table(
        "bus.csv",
        ["bus_id", "type"],
        [{"bus_id": "b1", "type": "3"}],
    )
    write_table(
        "demand_bus.csv",
        ["UTC Time", "b1"],
        [{"UTC Time": "2016-01-01 00:00:00", "b1": "1"}],
    )
    generator_fields = [
        "generator_id", "bus_id", "p_min_mw", "p_max_mw", "status", "technology",
        "marginal_cost_c1_per_mwh",
    ]
    write_table(
        "generator_limits.csv",
        generator_fields,
        [
            {"generator_id": "solar-1", "bus_id": "b1", "p_min_mw": "0", "p_max_mw": "50", "status": "1", "technology": "solar", "marginal_cost_c1_per_mwh": "0"},
            {"generator_id": "gas-1", "bus_id": "b1", "p_min_mw": "0", "p_max_mw": "2", "status": "1", "technology": "ng", "marginal_cost_c1_per_mwh": "10"},
        ],
    )
    write_table(
        "branch_limits.csv",
        ["branch_id", "from_bus_id", "to_bus_id", "thermal_limit_mva", "status", "reactance_pu"],
        [],
    )
    write_table("dcline.csv", ["status", "to_bus_id", "Pt"], [])
    write_table(
        "solar.csv",
        ["UTC", "solar-1"],
        [{"UTC": "2016-01-01 00:00:00", "solar-1": "0"}],
    )

    result = solve_prepared_period(tmp_path, period_index=0)

    assert result.generation_mw["solar-1"] == 1.0


def _write_minimal_prepared_artifact(root, demand: str = "0"):
    def write_table(name, fieldnames, rows):
        with (root / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    write_table("bus.csv", ["bus_id", "type"], [{"bus_id": "b1", "type": "3"}])
    write_table(
        "demand_bus.csv",
        ["UTC Time", "b1"],
        [{"UTC Time": "2016-01-01 00:00:00", "b1": demand}],
    )
    write_table(
        "generator_limits.csv",
        [
            "generator_id",
            "bus_id",
            "p_min_mw",
            "p_max_mw",
            "status",
            "technology",
            "marginal_cost_c1_per_mwh",
        ],
        [],
    )
    write_table(
        "branch_limits.csv",
        ["branch_id", "from_bus_id", "to_bus_id", "thermal_limit_mva", "status", "reactance_pu"],
        [],
    )
    write_table("dcline.csv", ["status", "to_bus_id", "Pt"], [])


def test_prepared_artifact_rows_and_profiles_cannot_be_mutated(tmp_path):
    _write_minimal_prepared_artifact(tmp_path)

    artifact = load_prepared_artifact(tmp_path)

    with pytest.raises(TypeError):
        artifact.demand_rows[0]["b1"] = "99"
    with pytest.raises(TypeError):
        artifact.renewable_profile_mw_by_generator["solar-1"] = (0.0,)


def test_prepared_artifact_cache_reloads_when_same_path_is_replaced(tmp_path):
    _write_minimal_prepared_artifact(tmp_path, demand="0")
    first = load_prepared_artifact(tmp_path)

    _write_minimal_prepared_artifact(tmp_path, demand="2")
    second = load_prepared_artifact(tmp_path)

    assert second is not first
    assert second.demand_rows[0]["b1"] == "2"
