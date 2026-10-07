import json
from pathlib import Path

import pytest

from ercot_game.cli import _load_scenario
from ercot_game.evaluator import evaluate_week, resolve_evaluation_config
from ercot_game.io import plan_from_dict


ROOT = Path(__file__).parents[1]
SCENARIO_PATH = ROOT / "data/teaching/ercot_connection_scenario_v2.json"
MODEL_PATH = ROOT / "data/processed/ercot_planning_model_v1.json"


@pytest.fixture(scope="module")
def scenario():
    return _load_scenario(SCENARIO_PATH)


def make_plan(region, capacity=20.0, interfaces=(), generator=False):
    generators = []
    if generator:
        generators.append({"generator_id": "gen-1", "connection_id": "site-1", "capacity_mw": 8.0, "marginal_cost_per_mwh": 80.0})
    return plan_from_dict({
        "team_id": "qa-team",
        "connections": [{"connection_id": "site-1", "bus_id": region, "path_corridors": list(interfaces), "capacity_mw": capacity, "profile": [1.0] * 6}],
        "generators": generators,
        "intervention_budget_k": 0,
        "curtailment_depth_mu": 0.1,
        "flexibility_fee_per_mwh": 0.0,
    })


def result_for(scenario, plan):
    result = evaluate_week(scenario, resolve_evaluation_config(scenario), (plan,))
    return result.team_results[0]


def test_representative_feasible_plan_is_deterministic(scenario):
    plan = make_plan("SOUTH_TEXAS", capacity=20)
    first = result_for(scenario, plan)
    second = result_for(scenario, plan)
    assert first == second
    assert first["diagnostics"]["feasible"] is True
    assert first["score_breakdown"]["total"] > 0


def test_region_headroom_binding_has_specific_resource(scenario):
    result = result_for(scenario, make_plan("NORTHWEST", capacity=50))
    assert result["diagnostics"]["feasible"] is False
    binding = result["connection_results"][0]["allocation"]["binding_resources"]
    assert binding and binding[0] == "bus:NORTHWEST"


def test_interface_binding_has_specific_resource(scenario):
    result = result_for(scenario, make_plan("HIGH_PLAINS", capacity=40, interfaces=("HIGH_PLAINS__PERMIAN",)))
    assert result["diagnostics"]["feasible"] is False
    binding = result["connection_results"][0]["allocation"]["binding_resources"]
    assert binding and binding[0] == "corridor:HIGH_PLAINS__PERMIAN"


def test_multiple_project_and_generator_plan_is_supported(scenario):
    plan = plan_from_dict({
        "team_id": "qa-team",
        "connections": [
            {"connection_id": "site-1", "bus_id": "SOUTH_TEXAS", "path_corridors": [], "capacity_mw": 10, "profile": [1] * 6},
            {"connection_id": "site-2", "bus_id": "NORTH", "path_corridors": [], "capacity_mw": 10, "profile": [0.8] * 6},
        ],
        "generators": [{"generator_id": "gen-1", "connection_id": "site-1", "capacity_mw": 8, "marginal_cost_per_mwh": 80}],
        "intervention_budget_k": 1,
        "curtailment_depth_mu": 0.1,
        "flexibility_fee_per_mwh": 2,
    })
    result = result_for(scenario, plan)
    assert len(result["connection_results"]) == 2
    assert len(result["generator_dispatch_results"]) == 1


def test_planning_aliases_require_matching_versions_and_legacy_fixture_is_distinct(scenario):
    payload = {
        "team_id": "qa-team",
        "plan_schema_version": "planning-plan.v1",
        "planning_model_version": "9.9.9",
        "connections": [{"connection_id": "site-1", "connection_region_id": "SOUTH_TEXAS", "planning_interface_ids": [], "capacity_mw": 10, "profile": [1] * 6}],
        "generators": [],
        "intervention_budget_k": 0,
        "curtailment_depth_mu": 0.1,
        "flexibility_fee_per_mwh": 0,
    }
    plan = plan_from_dict(payload)
    assert plan.connections[0].bus_id == "SOUTH_TEXAS"
    legacy = _load_scenario(ROOT / "data/fixtures/ercot_small.json")
    assert legacy.scenario_id != scenario.scenario_id
    assert not {bus.bus_id for bus in legacy.buses} & {bus.bus_id for bus in scenario.buses}


def test_all_binding_resource_ids_are_typed_and_exist(scenario):
    plan = make_plan("HIGH_PLAINS", capacity=40, interfaces=("HIGH_PLAINS__PERMIAN",))
    result = result_for(scenario, plan)
    known_buses = {bus.bus_id for bus in scenario.buses}
    known_corridors = {corridor.corridor_id for corridor in scenario.corridors}
    for resource_id in result["connection_results"][0]["allocation"]["binding_resources"]:
        kind, value = resource_id.split(":", 1)
        assert (kind == "bus" and value in known_buses) or (kind == "corridor" and value in known_corridors)
