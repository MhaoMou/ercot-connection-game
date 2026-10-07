import json
import math
from pathlib import Path

import pytest

from ercot_game import Bus, ConnectionPlan, Corridor, GeneratorPlan, Scenario, TeamPlan
from ercot_game.io import plan_from_dict, scenario_from_dict
from ercot_game.validate import validate_plan, validate_scenario


PROJECT_ROOT = Path(__file__).parents[1]


def make_scenario() -> Scenario:
    return Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", (10.0, 12.0)),),
        (Corridor("corridor-1", (20.0, 25.0)),),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )


def make_plan(**overrides: object) -> TeamPlan:
    values: dict[str, object] = {
        "team_id": "team-1",
        "bus_id": "bus-a",
        "path_corridors": ("corridor-1",),
        "capacity_mw": 100.0,
        "profile": (0.5, 1.0),
        "generator": None,
        "intervention_budget_k": 1,
        "curtailment_depth_mu": 0.1,
        "flexibility_fee_per_mwh": 2.0,
    }
    values.update(overrides)
    return TeamPlan(**values)  # type: ignore[arg-type]


def test_validate_plan_returns_no_errors_for_valid_plan():
    assert validate_plan(make_plan(), make_scenario()) == []


def test_validate_plan_reports_errors_in_deterministic_order():
    plan = make_plan(
        team_id="",
        bus_id="missing-bus",
        path_corridors=("missing-corridor",),
        capacity_mw=-1.0,
        profile=(1.1,),
        generator=GeneratorPlan("gen-1", -2.0, 22.5),
        intervention_budget_k=3,
        curtailment_depth_mu=-0.1,
    )

    assert validate_plan(plan, make_scenario()) == [
        "team_id must not be empty",
        "unknown bus_id: missing-bus",
        "unknown corridor_id: missing-corridor",
        "capacity_mw must be finite and non-negative",
        "profile values must be finite and within [0, 1]",
        "profile length must match scenario time horizon (2)",
        "generator capacity_mw must be finite and non-negative",
        "intervention_budget_k must not exceed scenario time horizon (2)",
        "curtailment_depth_mu must be finite and within [0, 1]",
    ]


def test_validate_plan_rejects_negative_intervention_budget():
    assert validate_plan(make_plan(intervention_budget_k=-1), make_scenario()) == [
        "intervention_budget_k must be non-negative"
    ]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_validate_plan_rejects_non_finite_numeric_values(value: float):
    plan = make_plan(
        capacity_mw=value,
        profile=(value, 0.5),
        generator=GeneratorPlan("gen-1", value, value),
        curtailment_depth_mu=value,
        flexibility_fee_per_mwh=value,
    )

    assert validate_plan(plan, make_scenario()) == [
        "capacity_mw must be finite and non-negative",
        "profile values must be finite and within [0, 1]",
        "generator capacity_mw must be finite and non-negative",
        "generator marginal_cost_per_mwh must be finite",
        "curtailment_depth_mu must be finite and within [0, 1]",
        "flexibility_fee_per_mwh must be finite",
    ]


def test_validate_scenario_reports_inconsistent_time_series_lengths():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", (10.0,)),),
        (Corridor("corridor-1", (20.0, 25.0)),),
        (30.0, 31.0),
        (100.0,),
        1.0,
    )

    assert validate_scenario(scenario) == [
        "bus bus-a headroom_mw_by_time length must match scenario time horizon (2)",
        "it_value_per_mwh length must match scenario time horizon (2)",
    ]


def test_validate_scenario_reports_invalid_base_load_series():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (),
        (),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
        {},
        (10.0,),
    )

    assert validate_scenario(scenario) == [
        "base_load_mw_by_time length must match scenario time horizon (2)"
    ]


def test_validate_scenario_rejects_invalid_time_step_hours():
    scenario = Scenario(
        "scenario-1", "0.3.0", (), (), (), (), 0.0
    )

    assert validate_scenario(scenario) == ["time_step_hours must be finite and greater than 0"]


def test_validate_scenario_rejects_non_finite_numeric_series():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", (math.nan, 12.0)),),
        (Corridor("corridor-1", (20.0, math.inf)),),
        (30.0, -math.inf),
        (math.nan, 100.0),
        math.inf,
    )

    assert validate_scenario(scenario) == [
        "bus bus-a headroom_mw_by_time values must be finite",
        "corridor corridor-1 capacity_mw_by_time values must be finite",
        "energy_price_per_mwh values must be finite",
        "it_value_per_mwh values must be finite",
        "time_step_hours must be finite and greater than 0",
    ]


def test_validate_scenario_rejects_negative_resource_capacity_series():
    scenario = Scenario(
        "scenario-negative-resources",
        "0.3.0",
        (Bus("bus-a", (10.0, -1.0)),),
        (Corridor("corridor-1", (20.0, -2.0)),),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )

    assert validate_scenario(scenario) == [
        "bus bus-a headroom_mw_by_time values must be non-negative",
        "corridor corridor-1 capacity_mw_by_time values must be non-negative",
    ]


def test_educational_fixture_loads_and_validates():
    with (PROJECT_ROOT / "data/fixtures/ercot_small.json").open() as fixture_file:
        scenario = scenario_from_dict(json.load(fixture_file))

    assert scenario.scenario_id == "ercot-small-week-01"
    assert scenario.evaluator_version == "0.3.0"
    assert 24 <= len(scenario.buses) <= 36
    assert 40 <= len(scenario.corridors) <= 60
    assert len(scenario.energy_price_per_mwh) == 6
    assert scenario.metadata == {
        "source_description": (
            "Educational ERCOT-derived abstraction for classroom exercises; "
            "values are illustrative, schematic, and not operational data."
        ),
        "data_version": "2026-09-29.1",
        "model_limitations": [
            "Thirty-two schematic buses and forty-eight representative corridors are teaching abstractions, not official ERCOT topology or geographic/substation data.",
            "Six-period headroom, corridor capacities, prices, and IT value are illustrative rather than forecasts, market settlements, or operating limits.",
            "The model uses linear capacity limits, simplified generator dispatch, and bounded deterministic curtailment recourse; it does not represent AC power flow, losses, contingencies, or unit commitment.",
        ],
        "evaluation_config": {
            "curtailment_cost_per_mwh": 5.0,
            "unserved_penalty_per_mwh": 500.0,
            "emergency_energy_cost_per_mwh": 80.0,
        },
    }
    assert scenario.base_load_mw_by_time == (12.0, 13.0, 14.0, 15.0, 14.0, 12.0)
    assert validate_scenario(scenario) == []


def test_example_submissions_are_distinct_shared_and_valid():
    with (PROJECT_ROOT / "data/fixtures/ercot_small.json").open() as fixture_file:
        scenario = scenario_from_dict(json.load(fixture_file))
    with (PROJECT_ROOT / "examples/week_01_submissions.json").open() as submissions_file:
        submissions = json.load(submissions_file)

    plans = tuple(plan_from_dict(payload) for payload in submissions)
    assert len(plans) == 4
    assert len({plan.team_id for plan in plans}) == 4
    assert any(plan.generator is not None for plan in plans)
    shared_bus_id = "bus-west-constrained"
    shared_plans = tuple(plan for plan in plans if plan.bus_id == shared_bus_id)
    assert len(shared_plans) == 2
    constrained_bus = next(bus for bus in scenario.buses if bus.bus_id == shared_bus_id)
    assert any(
        sum(plan.capacity_mw * plan.profile[index] for plan in shared_plans)
        > constrained_bus.headroom_mw_by_time[index]
        for index in range(6)
    )
    assert all(validate_plan(plan, scenario) == [] for plan in plans)


def test_validate_plan_reports_canonical_multi_site_reference_and_range_errors():
    plan = TeamPlan(
        team_id="team-multi",
        connections=(
            ConnectionPlan("site-a", "missing-bus", ("missing-corridor",), -1.0, (1.0,)),
            ConnectionPlan("site-a", "bus-a", (), 2.0, (math.nan, 1.0)),
        ),
        generators=(
            GeneratorPlan("gen-a", "site-a", -1.0, math.inf),
            GeneratorPlan("gen-a", "missing-site", 1.0, 10.0),
        ),
        intervention_budget_k=3,
        curtailment_depth_mu=1.1,
        flexibility_fee_per_mwh=0.0,
    )

    errors = validate_plan(plan, make_scenario())

    assert "duplicate connection_id: site-a" in errors
    assert "duplicate generator_id: gen-a" in errors
    assert "connection site-a: unknown bus_id: missing-bus" in errors
    assert "connection site-a: unknown corridor_id: missing-corridor" in errors
    assert "connection site-a: capacity_mw must be finite and non-negative" in errors
    assert "connection site-a: profile values must be finite and within [0, 1]" in errors
    assert "connection site-a: profile length must match scenario time horizon (2)" in errors
    assert "generator gen-a: capacity_mw must be finite and non-negative" in errors
    assert "generator gen-a: marginal_cost_per_mwh must be finite" in errors
    assert "generator gen-a references unknown connection_id: missing-site" in errors
    assert "intervention_budget_k must not exceed scenario time horizon (2)" in errors
    assert "curtailment_depth_mu must be finite and within [0, 1]" in errors


def test_validate_plan_rejects_empty_canonical_connections():
    plan = TeamPlan(
        "team-empty",
        connections=(),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    assert validate_plan(plan, make_scenario()) == ["connections must not be empty"]


def test_validate_plan_rejects_negative_generator_cost():
    plan = make_plan(generator=GeneratorPlan("gen-1", 2.0, -1.0))

    assert validate_plan(plan, make_scenario()) == [
        "generator marginal_cost_per_mwh must be non-negative"
    ]


def test_validate_plan_rejects_duplicate_corridors_within_one_connection():
    plan = make_plan(path_corridors=("corridor-1", "corridor-1"))

    assert validate_plan(plan, make_scenario()) == [
        "duplicate corridor_id in connection connection-legacy: corridor-1"
    ]


def test_validate_plan_reports_non_string_canonical_ids_without_type_error():
    plan = TeamPlan(
        "team-malformed-ids",
        connections=(ConnectionPlan(7, "bus-a", (), 1.0, (1.0,)),),  # type: ignore[arg-type]
        generators=(GeneratorPlan([], "missing-site", 1.0, 1.0),),  # type: ignore[arg-type]
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    errors = validate_plan(plan, make_scenario())

    assert "connection 7: connection_id must be a string" in errors
    assert "generator []: generator_id must be a string" in errors
    assert "generator [] references unknown connection_id: missing-site" in errors


@pytest.mark.parametrize("connection_id", ("", "   "))
def test_validate_plan_rejects_blank_connection_ids(connection_id: str):
    plan = TeamPlan(
        "team-1",
        connections=(ConnectionPlan(connection_id, "bus-a", ("corridor-1",), 100.0, (0.5, 1.0)),),
        generators=(),
        intervention_budget_k=1,
        curtailment_depth_mu=0.1,
        flexibility_fee_per_mwh=2.0,
    )

    assert validate_plan(plan, make_scenario()) == [
        f"connection {connection_id}: connection_id must not be empty"
    ]


@pytest.mark.parametrize("generator_id", ("", "   "))
def test_validate_plan_rejects_blank_generator_ids(generator_id: str):
    plan = make_plan(generator=GeneratorPlan(generator_id, 2.0, 1.0))

    assert validate_plan(plan, make_scenario()) == [
        f"generator {generator_id}: generator_id must not be empty"
    ]
