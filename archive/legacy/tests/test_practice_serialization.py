import json
from pathlib import Path
from dataclasses import replace
from types import MappingProxyType

import pytest

from ercot_game.evaluator import evaluate_week
from ercot_game.io import plan_from_dict, scenario_from_dict
from ercot_game.practice_serialization import (
    _json_safe,
    error_response,
    evaluation_response,
    scenario_response,
)


PROJECT_ROOT = Path(__file__).parents[1]


def load_fixture_inputs():
    scenario = scenario_from_dict(
        json.loads((PROJECT_ROOT / "data/fixtures/ercot_small.json").read_text())
    )
    plans = tuple(
        plan_from_dict(payload)
        for payload in json.loads(
            (PROJECT_ROOT / "examples/week_01_submissions.json").read_text()
        )
    )
    return scenario, plans


def canonical_multi_site_payload():
    return {
        "team_id": "team-canonical",
        "connections": [
            {
                "connection_id": "site-z",
                "bus_id": "bus-panhandle-01",
                "path_corridors": [],
                "capacity_mw": 5.0,
                "profile": [0.5] * 6,
            },
            {
                "connection_id": "site-a",
                "bus_id": "bus-coast-01",
                "path_corridors": [],
                "capacity_mw": 5.0,
                "profile": [0.5] * 6,
            },
        ],
        "generators": [
            {
                "generator_id": "gen-z",
                "connection_id": "site-z",
                "capacity_mw": 1.0,
                "marginal_cost_per_mwh": 20.0,
            },
            {
                "generator_id": "gen-a",
                "connection_id": "site-a",
                "capacity_mw": 1.0,
                "marginal_cost_per_mwh": 10.0,
            },
        ],
        "intervention_budget_k": 0,
        "curtailment_depth_mu": 0.0,
        "flexibility_fee_per_mwh": 0.0,
    }


def test_scenario_response_contains_json_safe_practice_and_map_contract():
    scenario, _ = load_fixture_inputs()

    response = scenario_response(scenario)

    assert response["scenario_id"] == scenario.scenario_id
    assert response["evaluator_version"] == scenario.evaluator_version
    assert response["time_horizon"] == 6
    assert response["prices"] == {
        "energy_price_per_mwh": list(scenario.energy_price_per_mwh),
        "it_value_per_mwh": list(scenario.it_value_per_mwh),
    }
    assert response["rules"]["time_step_hours"] == scenario.time_step_hours
    assert response["map"]["footprint"]["type"] == "Polygon"
    assert response["map"]["locator"]["ercot_marker"] == [-99.0, 31.0]
    assert response["map"]["bus_coordinates"]["bus-central"]["latitude"] == 31.0
    assert response["map"]["bus_coordinates"]["bus-central"]["longitude"] == -99.0
    assert response["map"]["bus_coordinates"]["bus-central"]["zone"] == "Central"
    assert response["map"]["bus_coordinates"]["bus-central"]["resource_class"] == "unconstrained"
    assert response["map"]["corridor_paths"]["corridor-west-central"]
    assert response["buses"][0]["headroom_mw_by_time"] == [24.0, 27.0, 21.0, 19.0, 26.0, 29.0]
    json.dumps(response, allow_nan=False)


def test_scenario_response_exposes_canonical_resources_zones_period_and_tutorial():
    scenario, _ = load_fixture_inputs()

    response = scenario_response(scenario, selected_period=2)

    assert len(response["buses"]) == 32
    assert len(response["corridors"]) == 48
    assert response["zones"] == response["presentation"]["zone_labels"]
    assert response["tutorial_hints"] == response["presentation"]["tutorial_hints"]
    assert response["selected_period"] == {
        "index": 2,
        "label": "Period 3",
        "buses": [
            {"bus_id": bus.bus_id, "headroom_mw": bus.headroom_mw_by_time[2]}
            for bus in scenario.buses
        ],
        "corridors": [
            {
                "corridor_id": corridor.corridor_id,
                "capacity_mw": corridor.capacity_mw_by_time[2],
            }
            for corridor in scenario.corridors
        ],
    }
    assert response["map"]["zones"] == response["zones"]
    assert response["map"]["tutorial_hints"] == response["tutorial_hints"]
    json.dumps(response, allow_nan=False)


def test_evaluation_response_serializes_real_result_and_sorts_teams():
    scenario, plans = load_fixture_inputs()
    result = evaluate_week(scenario, None, plans)

    response = evaluation_response(result)

    assert response["evaluator_version"] == scenario.evaluator_version
    assert response["scenario_id"] == scenario.scenario_id
    assert response["input_hash"] == result.input_hash
    assert [team["team_id"] for team in response["team_results"]] == sorted(
        team["team_id"] for team in result.team_results
    )
    assert response["aggregate_diagnostics"]["team_count"] == len(plans)
    team = response["team_results"][0]
    assert {"allocation", "recourse", "generator_dispatch", "score_breakdown", "diagnostics"} <= team.keys()
    assert {"it_value", "energy_cost", "generator_cost", "flexibility_fee", "curtailment_cost", "unserved_penalty", "total"} <= team["score_breakdown"].keys()
    json.dumps(response, allow_nan=False)


def test_evaluation_response_exposes_canonical_multi_site_envelope_and_team_totals():
    scenario, _ = load_fixture_inputs()
    plan = plan_from_dict(canonical_multi_site_payload())
    result = evaluate_week(scenario, None, (plan,))

    response = evaluation_response(result)
    team = response["team_results"][0]

    assert [site["connection_id"] for site in team["connection_results"]] == [
        "site-a",
        "site-z",
    ]
    assert [item["generator_id"] for item in team["generator_dispatch_results"]] == [
        "gen-a",
        "gen-z",
    ]
    assert [item["connection_id"] for item in team["site_diagnostics"]] == [
        "site-a",
        "site-z",
    ]
    assert team["team_totals"] == {
        "team_id": "team-canonical",
        "feasible": True,
        "score_breakdown": team["score_breakdown"],
        "total": team["score_breakdown"]["total"],
    }
    assert [item["connection_id"] for item in response["connection_results"]] == [
        "site-a",
        "site-z",
    ]
    assert [item["generator_id"] for item in response["generator_dispatch"]] == [
        "gen-a",
        "gen-z",
    ]
    assert response["team_totals"] == [team["team_totals"]]
    json.dumps(response, allow_nan=False)


def test_nested_immutable_values_are_thawed_to_plain_json_containers():
    scenario, _ = load_fixture_inputs()

    response = scenario_response(scenario)

    assert isinstance(response["buses"], list)
    assert isinstance(response["buses"][0]["headroom_mw_by_time"], list)
    assert isinstance(response["map"]["footprint"]["coordinates"], list)
    assert isinstance(response["map"]["footprint"]["coordinates"][0], list)


def test_scenario_response_thaws_immutable_metadata_and_preserves_all_fields():
    scenario, _ = load_fixture_inputs()
    metadata = MappingProxyType(
        {
            "custom_rule": MappingProxyType({"windows": (1, 2), "enabled": True}),
            "nested": (MappingProxyType({"label": "practice"}),),
        }
    )
    presentation = MappingProxyType(
        {
            "footprint": scenario.presentation["footprint"],
            "locator": scenario.presentation["locator"],
            "custom_overlay": MappingProxyType(
                {"coordinates": ((-100.0, 30.0),), "label": "study area"}
            ),
        }
    )
    scenario = replace(scenario, metadata=metadata, presentation=presentation)

    response = scenario_response(scenario)

    assert response["metadata"] == {
        "custom_rule": {"windows": [1, 2], "enabled": True},
        "nested": [{"label": "practice"}],
    }
    assert response["presentation"]["custom_overlay"] == {
        "coordinates": [[-100.0, 30.0]],
        "label": "study area",
    }
    assert response["map"]["custom_overlay"] == response["presentation"]["custom_overlay"]
    json.dumps(response, allow_nan=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("time_step_hours", float("nan")),
        ("time_step_hours", float("inf")),
        ("base_load_mw_by_time", (float("nan"),)),
        ("base_load_mw_by_time", (float("-inf"),)),
    ],
)
def test_scenario_response_rejects_non_finite_rule_values_deterministically(field, value):
    scenario, _ = load_fixture_inputs()
    scenario = replace(scenario, **{field: value})

    with pytest.raises(TypeError, match="^JSON numbers must be finite$"):
        scenario_response(scenario)


def test_json_safe_rejects_sets_and_non_string_mapping_keys_deterministically():
    with pytest.raises(TypeError, match="unsupported JSON value: set"):
        _json_safe({"values": {1, 2}})

    with pytest.raises(TypeError, match="mapping keys must be strings"):
        _json_safe({1: "not a JSON object key"})


def test_error_response_is_stable_and_does_not_expose_tracebacks():
    response = error_response(
        "invalid_plan", "plan payload is malformed", evaluator_version="0.3.0"
    )

    assert response == {
        "error": {
            "code": "invalid_plan",
            "message": "plan payload is malformed",
            "evaluator_version": "0.3.0",
        }
    }
    assert "Traceback" not in json.dumps(response)
    assert "InternalError" not in json.dumps(response)
    json.dumps(response, allow_nan=False)
