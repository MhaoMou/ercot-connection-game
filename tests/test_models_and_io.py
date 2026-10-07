from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
from typing import Mapping, get_type_hints

import pytest

import ercot_game
from ercot_game import (
    Bus,
    ConnectionPlan,
    Corridor,
    EvaluationConfig,
    EvaluationResult,
    GeneratorPlan,
    Scenario,
    TeamPlan,
)
from ercot_game.io import (
    canonical_hash,
    normalize_plan_payload,
    plan_from_dict,
    plan_to_dict,
    scenario_from_dict,
    scenario_to_dict,
)


def test_package_exports_public_types_and_version():
    assert ercot_game.__version__ == "0.3.0"
    assert set(ercot_game.__all__) == {
        "Bus",
        "ConnectionPlan",
        "Corridor",
        "EvaluationConfig",
        "EvaluationResult",
        "GeneratorPlan",
        "Scenario",
        "TeamPlan",
    }


def test_generator_plan_is_immutable_and_has_value_equality():
    first = GeneratorPlan("gen-1", "connection-1", 40.0, 22.5)
    second = GeneratorPlan("gen-1", "connection-1", 40.0, 22.5)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.capacity_mw = 41.0


def test_canonical_generator_rejects_numeric_connection_id_but_legacy_form_survives():
    with pytest.raises(TypeError, match="connection_id must be a string"):
        GeneratorPlan("gen-1", 7, 40.0, 22.5)

    legacy = GeneratorPlan("gen-legacy", 40.0, 22.5)

    assert legacy.connection_id == "connection-legacy"


def test_connection_and_generator_plans_are_canonical_and_immutable():
    connection = ConnectionPlan(
        "connection-1", "bus-a", ["corridor-1"], 100.0, [0.5, 1.0]
    )
    generator = GeneratorPlan("gen-1", "connection-1", 40.0, 22.5)

    assert connection.path_corridors == ("corridor-1",)
    assert connection.profile == (0.5, 1.0)
    assert generator.connection_id == "connection-1"
    with pytest.raises(FrozenInstanceError):
        connection.bus_id = "bus-b"
    with pytest.raises(FrozenInstanceError):
        connection.path_corridors += ("corridor-2",)


def test_canonical_team_plan_contains_immutable_connection_and_generator_tuples():
    connection = ConnectionPlan("connection-1", "bus-a", (), 100.0, (1.0,))
    generator = GeneratorPlan("gen-1", "connection-1", 40.0, 22.5)

    plan = TeamPlan(
        team_id="team-1",
        connections=[connection],
        generators=[generator],
        intervention_budget_k=1,
        curtailment_depth_mu=0.1,
        flexibility_fee_per_mwh=2.0,
    )

    assert plan.connections == (connection,)
    assert plan.generators == (generator,)
    with pytest.raises(FrozenInstanceError):
        plan.connections += (connection,)


def test_canonical_plan_constructor_does_not_alias_input_lists():
    path_corridors = ["corridor-1"]
    profile = [1.0]
    connections = [ConnectionPlan("connection-1", "bus-a", path_corridors, 100.0, profile)]
    generators = [GeneratorPlan("gen-1", "connection-1", 40.0, 22.5)]
    plan = TeamPlan(
        team_id="team-1",
        connections=connections,
        generators=generators,
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    path_corridors.append("corridor-2")
    profile[0] = 0.0
    connections.clear()
    generators.clear()

    assert plan.connections[0].path_corridors == ("corridor-1",)
    assert plan.connections[0].profile == (1.0,)
    assert plan.generators[0].generator_id == "gen-1"


def test_dataclass_replace_generator_none_updates_canonical_generator_tuple():
    plan = TeamPlan(
        team_id="team-1",
        connections=(ConnectionPlan("connection-1", "bus-a", (), 100.0, (1.0,)),),
        generators=(GeneratorPlan("gen-1", "connection-1", 40.0, 22.5),),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    replaced = replace(plan, generator=None)

    assert replaced.generators == ()
    assert replaced.generator is None


def test_dataclass_replace_canonical_sites_wins_over_copied_compatibility_fields():
    plan = TeamPlan(
        team_id="team-1",
        connections=(ConnectionPlan("connection-1", "bus-a", (), 100.0, (1.0,)),),
        generators=(GeneratorPlan("gen-1", "connection-1", 40.0, 22.5),),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )
    replacement_connection = ConnectionPlan("connection-2", "bus-b", (), 80.0, (0.5,))
    replacement_generator = GeneratorPlan("gen-2", "connection-2", 20.0, 30.0)

    replaced = replace(
        plan,
        connections=(replacement_connection,),
        generators=(replacement_generator,),
    )

    assert replaced.connections == (replacement_connection,)
    assert replaced.generators == (replacement_generator,)
    assert replaced.bus_id == "bus-b"
    assert replaced.generator == replacement_generator


def test_direct_mixed_team_plan_rejects_conflicting_legacy_fields():
    connection = ConnectionPlan("connection-1", "bus-a", (), 100.0, (1.0,))
    generator = GeneratorPlan("gen-1", "connection-1", 40.0, 22.5)

    with pytest.raises(ValueError, match="canonical and legacy TeamPlan fields"):
        TeamPlan(
            team_id="team-1",
            connections=(connection,),
            generators=(generator,),
            bus_id="bus-b",
            path_corridors=(),
            capacity_mw=100.0,
            profile=(1.0,),
            generator=generator,
            intervention_budget_k=0,
            curtailment_depth_mu=0.0,
            flexibility_fee_per_mwh=0.0,
        )


def test_team_plan_asdict_excludes_private_compatibility_snapshot():
    plan = TeamPlan(
        team_id="team-1",
        connections=(ConnectionPlan("connection-1", "bus-a", (), 100.0, (1.0,)),),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    serialized = asdict(plan)

    assert "_compat_source" not in serialized


def test_team_plan_keeps_path_and_profile_as_tuples_without_validation():
    plan = TeamPlan(
        team_id="team-1",
        bus_id="bus-a",
        path_corridors=("corridor-1",),
        capacity_mw=100.0,
        profile=(0.5, 1.0),
        generator=None,
        intervention_budget_k=1,
        curtailment_depth_mu=0.1,
        flexibility_fee_per_mwh=2.0,
    )

    assert plan.path_corridors == ("corridor-1",)
    assert plan.profile == (0.5, 1.0)
    assert TeamPlan("", "bus-a", (), 0.0, (), None, 0, 0.0, 0.0).team_id == ""


def test_network_and_scenario_models_have_explicit_tuple_series():
    bus = Bus("bus-a", (10.0, 12.0))
    corridor = Corridor("corridor-1", (20.0, 25.0))
    scenario = Scenario(
        scenario_id="scenario-1",
        evaluator_version="0.3.0",
        buses=(bus,),
        corridors=(corridor,),
        energy_price_per_mwh=(30.0, 31.0),
        it_value_per_mwh=(100.0, 100.0),
        time_step_hours=1.0,
    )

    assert bus.headroom_mw_by_time == (10.0, 12.0)
    assert corridor.capacity_mw_by_time == (20.0, 25.0)
    assert scenario.buses == (bus,)
    assert scenario.corridors == (corridor,)
    assert scenario.metadata == {}
    assert scenario.base_load_mw_by_time == ()


def test_network_and_scenario_sequence_inputs_are_detached_and_tupled():
    headroom = [10.0, 12.0]
    corridor_capacity = [20.0, 25.0]
    bus = Bus("bus-a", headroom)
    corridor = Corridor("corridor-1", corridor_capacity)
    buses = [bus]
    corridors = [corridor]
    prices = [30.0, 31.0]
    it_values = [100.0, 100.0]
    base_load = [12.0, 13.0]
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        buses,
        corridors,
        prices,
        it_values,
        1.0,
        base_load_mw_by_time=base_load,
    )

    headroom.append(14.0)
    corridor_capacity[0] = 99.0
    buses.clear()
    corridors.clear()
    prices[0] = 0.0
    it_values[0] = 0.0
    base_load[0] = 0.0

    assert bus.headroom_mw_by_time == (10.0, 12.0)
    assert corridor.capacity_mw_by_time == (20.0, 25.0)
    assert scenario.buses == (bus,)
    assert scenario.corridors == (corridor,)
    assert scenario.energy_price_per_mwh == (30.0, 31.0)
    assert scenario.it_value_per_mwh == (100.0, 100.0)
    assert scenario.base_load_mw_by_time == (12.0, 13.0)


def test_evaluation_result_detaches_and_freezes_nested_result_containers():
    team_results = [{"team_id": "team-1", "diagnostics": {"values": [1.0]}}]
    aggregate_diagnostics = {"nested": {"items": ["binding"]}}
    result = EvaluationResult(
        scenario_id="scenario-1",
        input_hash="abc123",
        team_results=team_results,
        aggregate_diagnostics=aggregate_diagnostics,
    )

    team_results[0]["diagnostics"]["values"].append(2.0)
    aggregate_diagnostics["nested"]["items"].append("other")

    assert result.team_results[0]["diagnostics"]["values"] == [1.0]
    assert result.aggregate_diagnostics["nested"]["items"] == ["binding"]
    with pytest.raises(TypeError):
        result.team_results[0]["diagnostics"]["values"].append(2.0)
    with pytest.raises(TypeError):
        result.aggregate_diagnostics["nested"]["items"].append("other")
    json.dumps(
        {
            "team_results": result.team_results,
            "aggregate_diagnostics": result.aggregate_diagnostics,
        }
    )


def test_scenario_metadata_is_deeply_immutable():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (),
        (),
        (30.0,),
        (100.0,),
        1.0,
        {"rules": {"windows": [1, 2]}},
    )

    with pytest.raises(TypeError):
        scenario.metadata["rules"]["windows"] = (3,)
    with pytest.raises(TypeError):
        scenario.metadata["rules"] = {}


def test_scenario_base_load_round_trip_is_auditable():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (),
        (),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
        {},
        (12.0, 13.0),
    )

    payload = scenario_to_dict(scenario)

    assert payload["base_load_mw_by_time"] == [12.0, 13.0]
    assert scenario_from_dict(payload) == scenario


def test_evaluation_config_and_result_store_structured_outputs():
    config = EvaluationConfig(5.0, 500.0, 80.0)
    result = EvaluationResult(
        scenario_id="scenario-1",
        input_hash="abc123",
        team_results=({"team_id": "team-1", "score": 10.0},),
        aggregate_diagnostics={"binding": "bus-a"},
    )

    assert config.emergency_energy_cost_per_mwh == 80.0
    assert result.team_results == ({"team_id": "team-1", "score": 10.0},)
    assert result.aggregate_diagnostics == {"binding": "bus-a"}


def test_evaluation_result_uses_parameterized_mapping_annotations():
    annotations = get_type_hints(EvaluationResult)

    assert annotations["team_results"] == tuple[dict[str, object], ...]
    assert annotations["aggregate_diagnostics"] == dict[str, object]


def test_scenario_dict_round_trip_preserves_value_equality():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", (10.0, 12.0)),),
        (Corridor("corridor-1", (20.0, 25.0)),),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )

    assert scenario_from_dict(scenario_to_dict(scenario)) == scenario


def test_scenario_metadata_round_trip_preserves_values_and_keys():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (),
        (),
        (30.0,),
        (100.0,),
        1.0,
        {
            "source_description": "illustrative",
            "data_version": "2026-09-28.1",
            "model_limitations": ["aggregate network"],
        },
    )

    payload = scenario_to_dict(scenario)

    assert payload["metadata"] == scenario.metadata
    assert scenario_from_dict(payload) == scenario


def test_teaching_fixture_serialization_and_semantic_hash_are_deterministic():
    fixture = Path(__file__).parents[1] / "data/fixtures/ercot_small.json"
    first_payload = json.loads(fixture.read_text(encoding="utf-8"))
    second_payload = json.loads(fixture.read_text(encoding="utf-8"))
    first_scenario = scenario_from_dict(first_payload)
    second_scenario = scenario_from_dict(second_payload)

    first_serialized = scenario_to_dict(first_scenario)
    second_serialized = scenario_to_dict(second_scenario)

    assert first_serialized == second_serialized
    assert canonical_hash(first_serialized) == canonical_hash(second_serialized)
    assert json.dumps(first_serialized, sort_keys=True, separators=(",", ":")) == json.dumps(
        second_serialized, sort_keys=True, separators=(",", ":")
    )


def test_scenario_from_dict_defaults_metadata_for_legacy_payload():
    scenario = scenario_from_dict(
        {
            "scenario_id": "scenario-1",
            "evaluator_version": "0.3.0",
            "buses": [],
            "corridors": [],
            "energy_price_per_mwh": [],
            "it_value_per_mwh": [],
            "time_step_hours": 1.0,
        }
    )

    assert scenario.metadata == {}


def test_plan_dict_round_trip_preserves_value_equality():
    plan = TeamPlan(
        "team-1",
        "bus-a",
        ("corridor-1", "corridor-2"),
        100.0,
        (0.5, 1.0),
        GeneratorPlan("gen-1", 40.0, 22.5),
        1,
        0.1,
        2.0,
    )

    assert plan_from_dict(plan_to_dict(plan)) == plan


def test_plan_to_dict_emits_canonical_arrays_and_one_site_compatibility_view():
    plan = TeamPlan(
        team_id="team-1",
        connections=(ConnectionPlan("connection-1", "bus-a", ("corridor-1",), 100.0, (0.5,)),),
        generators=(GeneratorPlan("gen-1", "connection-1", 40.0, 22.5),),
        intervention_budget_k=1,
        curtailment_depth_mu=0.1,
        flexibility_fee_per_mwh=2.0,
    )

    payload = plan_to_dict(plan)

    assert payload["connections"] == [
        {
            "connection_id": "connection-1",
            "bus_id": "bus-a",
            "path_corridors": ["corridor-1"],
            "capacity_mw": 100.0,
            "profile": [0.5],
        }
    ]
    assert payload["generators"] == [
        {
            "generator_id": "gen-1",
            "connection_id": "connection-1",
            "capacity_mw": 40.0,
            "marginal_cost_per_mwh": 22.5,
        }
    ]
    assert payload["bus_id"] == "bus-a"
    assert payload["generator"] == {
        "generator_id": "gen-1",
        "capacity_mw": 40.0,
        "marginal_cost_per_mwh": 22.5,
    }
    assert plan_from_dict(payload) == plan


def test_plan_to_dict_round_trip_uses_normalized_canonical_path_order():
    plan = TeamPlan(
        team_id="team-1",
        connections=(
            ConnectionPlan(
                "connection-1",
                "bus-a",
                ("corridor-b", "corridor-a"),
                100.0,
                (0.5,),
            ),
        ),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    payload = plan_to_dict(plan)

    assert plan.connections[0].path_corridors == ("corridor-a", "corridor-b")
    assert payload["connections"][0]["path_corridors"] == [
        "corridor-a",
        "corridor-b",
    ]
    assert plan_from_dict(payload) == plan


def test_normalize_plan_payload_assigns_stable_legacy_connection_and_generator_ids():
    normalized = normalize_plan_payload(
        {
            "team_id": "team-1",
            "bus_id": "bus-a",
            "path_corridors": ["corridor-1"],
            "capacity_mw": 100.0,
            "profile": [0.5],
            "generator": {
                "generator_id": "gen-legacy",
                "capacity_mw": 40.0,
                "marginal_cost_per_mwh": 22.5,
            },
            "intervention_budget_k": 1,
            "curtailment_depth_mu": 0.1,
            "flexibility_fee_per_mwh": 2.0,
        }
    )

    assert normalized["connections"] == [
        {
            "connection_id": "connection-legacy",
            "bus_id": "bus-a",
            "path_corridors": ["corridor-1"],
            "capacity_mw": 100.0,
            "profile": [0.5],
        }
    ]
    assert normalized["generators"] == [
        {
            "generator_id": "gen-legacy",
            "connection_id": "connection-legacy",
            "capacity_mw": 40.0,
            "marginal_cost_per_mwh": 22.5,
        }
    ]
    assert plan_from_dict(normalized).connections[0].connection_id == "connection-legacy"


def test_normalize_legacy_generator_without_id_assigns_stable_generator_id():
    normalized = normalize_plan_payload(
        {
            "team_id": "team-1",
            "bus_id": "bus-a",
            "path_corridors": [],
            "capacity_mw": 100.0,
            "profile": [1.0],
            "generator": {
                "capacity_mw": 40.0,
                "marginal_cost_per_mwh": 22.5,
            },
            "intervention_budget_k": 0,
            "curtailment_depth_mu": 0.0,
            "flexibility_fee_per_mwh": 0.0,
        }
    )

    assert normalized["generators"] == [
        {
            "generator_id": "generator-legacy",
            "connection_id": "connection-legacy",
            "capacity_mw": 40.0,
            "marginal_cost_per_mwh": 22.5,
        }
    ]
    assert plan_from_dict(normalized).generators[0].generator_id == "generator-legacy"


def test_normalize_plan_payload_rejects_conflicting_legacy_and_canonical_values():
    with pytest.raises(ValueError, match="conflicting legacy and canonical connection"):
        normalize_plan_payload(
            {
                "team_id": "team-1",
                "connections": [
                    {
                        "connection_id": "connection-1",
                        "bus_id": "bus-a",
                        "path_corridors": [],
                        "capacity_mw": 100.0,
                        "profile": [1.0],
                    }
                ],
                "generators": [],
                "bus_id": "bus-b",
                "path_corridors": [],
                "capacity_mw": 100.0,
                "profile": [1.0],
                "generator": None,
                "intervention_budget_k": 0,
                "curtailment_depth_mu": 0.0,
                "flexibility_fee_per_mwh": 0.0,
            }
        )


def test_normalize_plan_payload_rejects_conflicting_legacy_generator_connection_id():
    with pytest.raises(ValueError, match="conflicting legacy and canonical generator"):
        normalize_plan_payload(
            {
                "team_id": "team-1",
                "connections": [
                    {
                        "connection_id": "connection-1",
                        "bus_id": "bus-a",
                        "path_corridors": [],
                        "capacity_mw": 100.0,
                        "profile": [1.0],
                    }
                ],
                "generators": [
                    {
                        "generator_id": "generator-1",
                        "connection_id": "connection-1",
                        "capacity_mw": 40.0,
                        "marginal_cost_per_mwh": 22.5,
                    }
                ],
                "bus_id": "bus-a",
                "path_corridors": [],
                "capacity_mw": 100.0,
                "profile": [1.0],
                "generator": {
                    "generator_id": "generator-1",
                    "connection_id": "connection-2",
                    "capacity_mw": 40.0,
                    "marginal_cost_per_mwh": 22.5,
                },
                "intervention_budget_k": 0,
                "curtailment_depth_mu": 0.0,
                "flexibility_fee_per_mwh": 0.0,
            }
        )


def test_normalize_plan_payload_rejects_generator_for_unknown_connection():
    with pytest.raises(ValueError, match="unknown connection_id: connection-missing"):
        normalize_plan_payload(
            {
                "team_id": "team-1",
                "connections": [
                    {
                        "connection_id": "connection-1",
                        "bus_id": "bus-a",
                        "path_corridors": [],
                        "capacity_mw": 100.0,
                        "profile": [1.0],
                    }
                ],
                "generators": [
                    {
                        "generator_id": "generator-1",
                        "connection_id": "connection-missing",
                        "capacity_mw": 40.0,
                        "marginal_cost_per_mwh": 22.5,
                    }
                ],
                "intervention_budget_k": 0,
                "curtailment_depth_mu": 0.0,
                "flexibility_fee_per_mwh": 0.0,
            }
        )


def test_normalize_plan_payload_rejects_malformed_site_arrays():
    with pytest.raises(ValueError, match="connections must be a sequence"):
        normalize_plan_payload(
            {
                "team_id": "team-1",
                "connections": "not-an-array",
                "generators": [],
                "intervention_budget_k": 0,
                "curtailment_depth_mu": 0.0,
                "flexibility_fee_per_mwh": 0.0,
            }
        )


def test_plan_dict_round_trip_preserves_none_generator_and_does_not_alias_tuples():
    plan = TeamPlan("team-1", "bus-a", ("corridor-1",), 100.0, (0.5,), None, 0, 0.1, 2.0)

    payload = plan_to_dict(plan)
    payload["path_corridors"].append("corridor-2")
    payload["profile"].append(1.0)

    assert plan.generator is None
    assert plan.path_corridors == ("corridor-1",)
    assert plan.profile == (0.5,)
    assert plan_from_dict(plan_to_dict(plan)).generator is None


def test_canonical_hash_is_stable_under_dictionary_key_reordering():
    first = {"b": {"y": 2, "x": 1}, "a": [3, 4]}
    second = {"a": [3, 4], "b": {"x": 1, "y": 2}}

    assert canonical_hash(first) == canonical_hash(second)


def test_canonical_hash_has_exact_stable_json_representation():
    assert canonical_hash({"b": 1, "a": [2, 3]}) == (
        "2aae3bfa906be39530e7d7a4aa90a7e6d4f29c33e3ac80e1c3b05598c5953c04"
    )


def test_canonical_hash_rejects_non_finite_numbers():
    with pytest.raises(ValueError):
        canonical_hash({"value": float("nan")})


def test_io_dict_signatures_are_mapping_compatible():
    assert get_type_hints(plan_from_dict)["payload"] == Mapping[str, object]
    assert get_type_hints(scenario_from_dict)["payload"] == Mapping[str, object]
