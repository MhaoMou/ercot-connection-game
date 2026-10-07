import json
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ercot_game import Bus, ConnectionPlan, Corridor, EvaluationConfig, GeneratorPlan, Scenario, TeamPlan
from ercot_game.cli import _configuration_from_inputs, main
from ercot_game.evaluator import EvaluationInputError, evaluate_week
from ercot_game.io import plan_from_dict, scenario_from_dict


PROJECT_ROOT = Path(__file__).parents[1]
CONFIG = EvaluationConfig(
    curtailment_cost_per_mwh=5.0,
    unserved_penalty_per_mwh=500.0,
    emergency_energy_cost_per_mwh=80.0,
)


def load_fixture_inputs():
    with (PROJECT_ROOT / "data/fixtures/ercot_small.json").open() as fixture_file:
        scenario = scenario_from_dict(json.load(fixture_file))
    with (PROJECT_ROOT / "examples/week_01_submissions.json").open() as submissions_file:
        plans = tuple(plan_from_dict(payload) for payload in json.load(submissions_file))
    return scenario, plans


def test_fixture_evaluation_is_identical_on_repeated_runs():
    scenario, plans = load_fixture_inputs()

    first = evaluate_week(scenario, CONFIG, plans)
    second = evaluate_week(scenario, CONFIG, plans)

    assert first == second
    assert first.input_hash == second.input_hash
    assert first.aggregate_diagnostics["evaluator_version"] == scenario.evaluator_version
    assert first.aggregate_diagnostics["configuration"] == {
        "curtailment_cost_per_mwh": 5.0,
        "unserved_penalty_per_mwh": 500.0,
        "emergency_energy_cost_per_mwh": 80.0,
    }


def test_evaluate_week_ignores_scenario_and_resource_presentation_in_input_hash():
    scenario, plans = load_fixture_inputs()
    first = evaluate_week(scenario, CONFIG, plans)
    changed_buses = list(scenario.buses)
    changed_buses[0] = replace(
        changed_buses[0],
        presentation={**changed_buses[0].presentation, "label": "Restyled bus"},
    )
    changed_corridors = list(scenario.corridors)
    changed_corridors[0] = replace(
        changed_corridors[0],
        presentation={**changed_corridors[0].presentation, "resource_class": "unconstrained"},
    )
    changed_scenario = replace(
        scenario,
        buses=tuple(changed_buses),
        corridors=tuple(changed_corridors),
        presentation={**scenario.presentation, "title": "Restyled teaching map"},
    )

    changed = evaluate_week(changed_scenario, CONFIG, plans)

    assert changed.input_hash == first.input_hash
    assert changed.team_results == first.team_results
    assert changed.aggregate_diagnostics == first.aggregate_diagnostics


def test_fixture_metadata_configuration_is_used_by_cli_resolution():
    scenario, _ = load_fixture_inputs()

    resolved = _configuration_from_inputs(scenario, None)

    assert resolved == EvaluationConfig(5.0, 500.0, 80.0)


def test_teaching_fixture_has_consistent_six_period_inputs_and_resource_diversity():
    scenario, _ = load_fixture_inputs()
    horizon = len(scenario.energy_price_per_mwh)

    assert horizon == 6
    assert len(scenario.it_value_per_mwh) == horizon
    assert len(scenario.base_load_mw_by_time) == horizon
    assert all(len(bus.headroom_mw_by_time) == horizon for bus in scenario.buses)
    assert all(len(corridor.capacity_mw_by_time) == horizon for corridor in scenario.corridors)
    assert sum(bus.presentation["resource_class"] == "constrained" for bus in scenario.buses) >= 4
    assert sum(bus.presentation["resource_class"] == "unconstrained" for bus in scenario.buses) >= 4
    assert sum(corridor.presentation["resource_class"] == "constrained" for corridor in scenario.corridors) >= 4
    assert sum(corridor.presentation["resource_class"] == "unconstrained" for corridor in scenario.corridors) >= 4
    constrained_means = [
        sum(bus.headroom_mw_by_time) / horizon
        for bus in scenario.buses
        if bus.presentation["resource_class"] == "constrained"
    ]
    unconstrained_means = [
        sum(bus.headroom_mw_by_time) / horizon
        for bus in scenario.buses
        if bus.presentation["resource_class"] == "unconstrained"
    ]
    assert min(unconstrained_means) < max(constrained_means)
    assert len({tuple(bus.headroom_mw_by_time) for bus in scenario.buses}) >= 24
    constrained_corridor_means = [
        sum(corridor.capacity_mw_by_time) / horizon
        for corridor in scenario.corridors
        if corridor.presentation["resource_class"] == "constrained"
    ]
    unconstrained_corridor_means = [
        sum(corridor.capacity_mw_by_time) / horizon
        for corridor in scenario.corridors
        if corridor.presentation["resource_class"] == "unconstrained"
    ]
    assert min(unconstrained_corridor_means) < max(constrained_corridor_means)
    assert len({tuple(corridor.capacity_mw_by_time) for corridor in scenario.corridors}) >= 24


def test_non_default_scenario_metadata_configuration_is_not_ignored():
    scenario, plans = load_fixture_inputs()
    scenario = replace(
        scenario,
        metadata={
            **scenario.metadata,
            "evaluation_config": {
                "curtailment_cost_per_mwh": 6.0,
                "unserved_penalty_per_mwh": 600.0,
                "emergency_energy_cost_per_mwh": 90.0,
            },
        },
    )

    result = evaluate_week(scenario, None, plans)

    assert result.aggregate_diagnostics["configuration"] == {
        "curtailment_cost_per_mwh": 6.0,
        "unserved_penalty_per_mwh": 600.0,
        "emergency_energy_cost_per_mwh": 90.0,
    }


def test_non_mapping_scenario_metadata_configuration_raises_typed_error():
    scenario, _ = load_fixture_inputs()
    scenario = replace(
        scenario,
        metadata={**scenario.metadata, "evaluation_config": [5.0, 500.0, 80.0]},
    )

    with pytest.raises(EvaluationInputError) as raised:
        _configuration_from_inputs(scenario, None)

    assert raised.value.errors == (
        "scenario metadata evaluation_config must be an object",
    )


def test_cli_reports_non_mapping_scenario_metadata_configuration(tmp_path, capsys):
    scenario_payload = json.loads(
        (PROJECT_ROOT / "data/fixtures/ercot_small.json").read_text()
    )
    scenario_payload["metadata"]["evaluation_config"] = [5.0, 500.0, 80.0]
    scenario_path = tmp_path / "invalid-config-scenario.json"
    scenario_path.write_text(json.dumps(scenario_payload))

    assert main(
        [
            "validate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(PROJECT_ROOT / "examples/week_01_submissions.json"),
        ]
    ) == 2
    assert capsys.readouterr().err.splitlines() == [
        "error: scenario metadata evaluation_config must be an object"
    ]


def test_explicit_configuration_overrides_scenario_metadata():
    scenario, plans = load_fixture_inputs()
    explicit = EvaluationConfig(7.0, 700.0, 90.0)

    result = evaluate_week(scenario, explicit, plans)

    assert result.aggregate_diagnostics["configuration"] == {
        "curtailment_cost_per_mwh": 7.0,
        "unserved_penalty_per_mwh": 700.0,
        "emergency_energy_cost_per_mwh": 90.0,
    }


def test_evaluator_uses_scenario_metadata_when_configuration_is_omitted():
    scenario, plans = load_fixture_inputs()

    result = evaluate_week(scenario, None, plans)

    assert result.aggregate_diagnostics["configuration"] == {
        "curtailment_cost_per_mwh": 5.0,
        "unserved_penalty_per_mwh": 500.0,
        "emergency_energy_cost_per_mwh": 80.0,
    }


def test_reversing_submission_order_does_not_change_output_or_hash():
    scenario, plans = load_fixture_inputs()

    forward = evaluate_week(scenario, CONFIG, plans)
    reversed_result = evaluate_week(scenario, CONFIG, tuple(reversed(plans)))

    assert forward == reversed_result


def test_reversing_scenario_resource_declarations_preserves_hash_and_semantics():
    scenario, plans = load_fixture_inputs()
    reordered_scenario = replace(
        scenario,
        buses=tuple(reversed(scenario.buses)),
        corridors=tuple(reversed(scenario.corridors)),
    )

    original = evaluate_week(scenario, CONFIG, plans)
    reordered = evaluate_week(reordered_scenario, CONFIG, plans)

    assert reordered.input_hash == original.input_hash
    assert reordered.team_results == original.team_results
    assert reordered.aggregate_diagnostics == original.aggregate_diagnostics


def test_reversing_team_path_corridors_preserves_hash_and_evaluation():
    scenario, plans = load_fixture_inputs()
    reordered_plans = tuple(
        replace(plan, path_corridors=tuple(reversed(plan.path_corridors)))
        for plan in plans
    )

    original = evaluate_week(scenario, CONFIG, plans)
    reordered = evaluate_week(scenario, CONFIG, reordered_plans)

    assert reordered.input_hash == original.input_hash
    assert reordered.team_results == original.team_results
    assert reordered.aggregate_diagnostics == original.aggregate_diagnostics


def test_shared_bus_teams_receive_proportional_allocation():
    scenario = Scenario(
        "shared-bus",
        "0.3.0",
        (Bus("bus-a", (60.0,)),),
        (),
        (40.0,),
        (100.0,),
        1.0,
    )
    plans = (
        TeamPlan("team-a", "bus-a", (), 100.0, (1.0,), None, 0, 0.0, 0.0),
        TeamPlan("team-b", "bus-a", (), 50.0, (1.0,), None, 0, 0.0, 0.0),
    )

    result = evaluate_week(scenario, CONFIG, plans)
    allocations = {team["team_id"]: team["allocation"] for team in result.team_results}

    assert allocations["team-a"]["resource_ratio_by_time"] == (0.4,)
    assert allocations["team-b"]["resource_ratio_by_time"] == (0.4,)
    assert allocations["team-a"]["allocated_capacity_mw"] == pytest.approx(40.0)
    assert allocations["team-b"]["allocated_capacity_mw"] == pytest.approx(20.0)


def test_generator_backed_fixture_team_has_no_residual_unserved_load():
    scenario, plans = load_fixture_inputs()

    result = evaluate_week(scenario, CONFIG, plans)
    sunrise = next(team for team in result.team_results if team["team_id"] == "team-sunrise")

    assert sunrise["generator_dispatch"]["generator_id"] == "gen-sunrise-01"
    assert sunrise["recourse"]["total_unserved_mwh"] == 0.0
    assert sunrise["recourse"]["residual_unserved_mw"] == (0.0,) * 6


def test_generator_dispatch_fills_network_shortfall_before_recourse():
    scenario = Scenario(
        "generator-recourse",
        "0.3.0",
        (Bus("bus-a", (2.0,)),),
        (),
        (40.0,),
        (100.0,),
        1.0,
    )
    plan = TeamPlan(
        "team-a",
        "bus-a",
        (),
        5.0,
        (1.0,),
        GeneratorPlan("gen-a", 2.0, 10.0),
        1,
        1.0,
        0.0,
    )

    team = evaluate_week(scenario, CONFIG, (plan,)).team_results[0]

    assert team["diagnostics"]["requested_load_mw"] == (5.0,)
    assert team["diagnostics"]["network_available_capacity_mw"] == (2.0,)
    assert team["diagnostics"]["effective_available_capacity_mw"] == (4.0,)
    assert team["generator_dispatch"]["dispatch_mw"] == (2.0,)
    assert team["recourse"]["served_mw"] == (4.0,)
    assert team["recourse"]["curtailed_mw"] == (1.0,)
    assert team["recourse"]["residual_unserved_mw"] == (0.0,)


def test_duplicate_and_malformed_plans_raise_typed_error_with_all_stable_errors():
    scenario, plans = load_fixture_inputs()
    invalid = replace(plans[0], bus_id="missing-bus", profile=(1.2,))
    duplicate = replace(plans[1], team_id=invalid.team_id)

    with pytest.raises(EvaluationInputError) as raised:
        evaluate_week(scenario, CONFIG, (invalid, duplicate))

    assert raised.value.errors == (
        "duplicate team_id: team-pioneer",
        "team-pioneer: profile length must match scenario time horizon (6)",
        "team-pioneer: profile values must be finite and within [0, 1]",
        "team-pioneer: unknown bus_id: missing-bus",
    )


def test_mixed_type_team_ids_raise_typed_error_and_cli_friendly_diagnostics(
    tmp_path, capsys
):
    scenario, plans = load_fixture_inputs()
    mixed_plans = (replace(plans[0], team_id=7), replace(plans[1], team_id="team-lone-star"))

    with pytest.raises(EvaluationInputError) as raised:
        evaluate_week(scenario, CONFIG, mixed_plans)

    assert raised.value.errors == ("7: team_id must be a string",)

    scenario_path = PROJECT_ROOT / "data/fixtures/ercot_small.json"
    submissions_path = tmp_path / "mixed-team-ids.json"
    submissions_path.write_text(
        json.dumps(
            [
                {
                    **json.loads((PROJECT_ROOT / "examples/week_01_submissions.json").read_text())[0],
                    "team_id": 7,
                },
                json.loads((PROJECT_ROOT / "examples/week_01_submissions.json").read_text())[1],
            ]
        )
    )

    assert main(
        [
            "validate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(submissions_path),
        ]
    ) != 0
    assert capsys.readouterr().err.splitlines() == ["error: 7: team_id must be a string"]


@pytest.mark.parametrize("resource_case", ("bus", "corridor", "plan_bus", "path"))
def test_mixed_type_resource_ids_raise_typed_evaluation_error(resource_case):
    scenario, plans = load_fixture_inputs()
    if resource_case == "bus":
        scenario = replace(
            scenario,
            buses=(replace(scenario.buses[0], bus_id=7),) + scenario.buses[1:],
        )
    elif resource_case == "corridor":
        scenario = replace(
            scenario,
            corridors=(replace(scenario.corridors[0], corridor_id=7),)
            + scenario.corridors[1:],
        )
    elif resource_case == "plan_bus":
        plans = (replace(plans[0], bus_id=7),) + plans[1:]
    else:
        plans = (replace(plans[0], path_corridors=("corridor-west-central", 7)),) + plans[1:]

    with pytest.raises(EvaluationInputError) as raised:
        evaluate_week(scenario, CONFIG, plans)

    assert all("TypeError" not in error for error in raised.value.errors)
    if resource_case == "bus":
        assert "bus_id must be a string" in raised.value.errors
    elif resource_case == "corridor":
        assert "corridor_id must be a string" in raised.value.errors
    elif resource_case == "plan_bus":
        assert "team-pioneer: bus_id must be a string" in raised.value.errors
    else:
        assert "team-pioneer: path_corridors[1] must be a string" in raised.value.errors


def test_cli_validate_and_evaluate_commands(tmp_path, capsys):
    scenario_path = PROJECT_ROOT / "data/fixtures/ercot_small.json"
    submissions_path = PROJECT_ROOT / "examples/week_01_submissions.json"
    output_path = tmp_path / "results.json"

    assert main(
        [
            "validate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(submissions_path),
        ]
    ) == 0
    assert capsys.readouterr().out == "valid\n"

    assert main(
        [
            "evaluate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(submissions_path),
            "--output",
            str(output_path),
        ]
    ) == 0
    payload = json.loads(output_path.read_text())
    assert payload["scenario_id"] == "ercot-small-week-01"
    assert payload["input_hash"]
    assert [team["team_id"] for team in payload["team_results"]] == [
        "team-lone-star",
        "team-pioneer",
        "team-prairie",
        "team-sunrise",
    ]


def test_cli_invalid_input_prints_deterministic_error_and_returns_nonzero(tmp_path, capsys):
    scenario_path = PROJECT_ROOT / "data/fixtures/ercot_small.json"
    submissions_path = tmp_path / "bad.json"
    submissions_path.write_text(
        json.dumps(
            [
                {
                    "team_id": "team-a",
                    "bus_id": "missing",
                    "path_corridors": [],
                    "capacity_mw": 1.0,
                    "profile": [1.0] * 6,
                    "generator": None,
                    "intervention_budget_k": 0,
                    "curtailment_depth_mu": 0.0,
                    "flexibility_fee_per_mwh": 0.0,
                },
                {
                    "team_id": "team-a",
                    "bus_id": "missing",
                    "path_corridors": [],
                    "capacity_mw": 1.0,
                    "profile": [1.0] * 6,
                    "generator": None,
                    "intervention_budget_k": 0,
                    "curtailment_depth_mu": 0.0,
                    "flexibility_fee_per_mwh": 0.0,
                },
            ]
        )
    )

    exit_code = main(
        [
            "validate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(submissions_path),
        ]
    )

    assert exit_code != 0
    assert capsys.readouterr().err.splitlines() == [
        "error: duplicate team_id: team-a",
        "error: team-a: unknown bus_id: missing",
    ]


def test_cli_module_runs_in_subprocess_with_src_layout(tmp_path):
    scenario_path = PROJECT_ROOT / "data/fixtures/ercot_small.json"
    submissions_path = PROJECT_ROOT / "examples/week_01_submissions.json"
    output_path = tmp_path / "subprocess-results.json"
    environment = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if not existing_pythonpath
        else os.pathsep.join((source_path, existing_pythonpath))
    )

    validate_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "ercot_game.cli",
            "validate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(submissions_path),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate_process.returncode == 0
    assert validate_process.stdout == "valid\n"
    assert validate_process.stderr == ""

    evaluate_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "ercot_game.cli",
            "evaluate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(submissions_path),
            "--output",
            str(output_path),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert evaluate_process.returncode == 0
    assert evaluate_process.stdout == ""
    assert evaluate_process.stderr == ""
    assert output_path.exists()
    assert json.loads(output_path.read_text())["scenario_id"] == "ercot-small-week-01"
    assert output_path.read_text().startswith("{\n  \"aggregate_diagnostics\"")

    invalid_submissions_path = tmp_path / "invalid-submissions.json"
    invalid_submissions_path.write_text(
        json.dumps(
            [
                {
                    "team_id": "team-invalid",
                    "bus_id": "missing-bus",
                    "path_corridors": [],
                    "capacity_mw": 1.0,
                    "profile": [1.0] * 6,
                    "generator": None,
                    "intervention_budget_k": 0,
                    "curtailment_depth_mu": 0.0,
                    "flexibility_fee_per_mwh": 0.0,
                }
            ]
        )
    )
    invalid_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "ercot_game.cli",
            "validate",
            "--scenario",
            str(scenario_path),
            "--submissions",
            str(invalid_submissions_path),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid_process.returncode != 0
    assert invalid_process.stdout == ""
    assert "error: team-invalid: unknown bus_id: missing-bus\n" in invalid_process.stderr


def test_evaluator_returns_deterministic_canonical_multi_site_and_generator_results():
    scenario = Scenario(
        "multi-site-evaluation",
        "0.3.0",
        (Bus("bus-a", (6.0,)), Bus("bus-b", (6.0,))),
        (Corridor("corridor-shared", (8.0,)),),
        (40.0,),
        (100.0,),
        1.0,
    )
    plan = TeamPlan(
        "team-multi",
        connections=(
            ConnectionPlan("site-z", "bus-a", ("corridor-shared",), 6.0, (1.0,)),
            ConnectionPlan("site-a", "bus-b", ("corridor-shared",), 6.0, (1.0,)),
        ),
        generators=(
            GeneratorPlan("gen-expensive", "site-z", 10.0, 20.0),
            GeneratorPlan("gen-cheap", "site-z", 2.0, 10.0),
        ),
        intervention_budget_k=1,
        curtailment_depth_mu=0.5,
        flexibility_fee_per_mwh=0.0,
    )

    result = evaluate_week(scenario, CONFIG, (plan,))
    reversed_result = evaluate_week(
        scenario,
        CONFIG,
        (TeamPlan(
            "team-multi",
            connections=tuple(reversed(plan.connections)),
            generators=tuple(reversed(plan.generators)),
            intervention_budget_k=1,
            curtailment_depth_mu=0.5,
            flexibility_fee_per_mwh=0.0,
        ),),
    )
    team = result.team_results[0]

    assert result == reversed_result
    assert [site["connection_id"] for site in team["connection_results"]] == ["site-a", "site-z"]
    assert [generator["generator_id"] for generator in team["generator_dispatch_results"]] == [
        "gen-cheap", "gen-expensive"
    ]
    assert team["diagnostics"]["site_binding_diagnostics"]
    assert result.aggregate_diagnostics["total_unserved_mwh"] == pytest.approx(
        team["recourse"]["total_unserved_mwh"]
    )


def test_evaluator_reports_explicit_binding_and_curtailed_site_id_collections():
    scenario = Scenario(
        "site-diagnostics",
        "0.3.0",
        (Bus("bus-a", (100.0,)), Bus("bus-b", (100.0,))),
        (Corridor("corridor-shared", (10.0,)),),
        (40.0,),
        (100.0,),
        1.0,
    )
    plans = (
        TeamPlan(
            "team-z",
            connections=(ConnectionPlan("site-z", "bus-a", ("corridor-shared",), 8.0, (1.0,)),),
            generators=(),
            intervention_budget_k=0,
            curtailment_depth_mu=0.0,
            flexibility_fee_per_mwh=0.0,
        ),
        TeamPlan(
            "team-a",
            connections=(ConnectionPlan("site-a", "bus-b", ("corridor-shared",), 8.0, (1.0,)),),
            generators=(),
            intervention_budget_k=0,
            curtailment_depth_mu=0.0,
            flexibility_fee_per_mwh=0.0,
        ),
    )

    result = evaluate_week(scenario, CONFIG, plans)
    by_team = {team["team_id"]: team for team in result.team_results}

    assert by_team["team-a"]["diagnostics"]["binding_site_ids"] == ()
    assert by_team["team-z"]["diagnostics"]["binding_site_ids"] == ("site-z",)
    assert by_team["team-z"]["diagnostics"]["curtailed_site_ids"] == ("site-z",)
    assert result.aggregate_diagnostics["binding_site_ids"] == (
        {"team_id": "team-z", "connection_id": "site-z"},
    )
    assert result.aggregate_diagnostics["curtailed_site_ids"] == (
        {"team_id": "team-z", "connection_id": "site-z"},
    )


def test_multi_site_overflow_becomes_structured_evaluation_input_error():
    scenario = Scenario(
        "multi-site-overflow",
        "0.3.0",
        (Bus("bus-a", (1e308,)), Bus("bus-b", (1e308,))),
        (),
        (40.0,),
        (100.0,),
        1.0,
    )
    plan = TeamPlan(
        "team-overflow",
        connections=(
            ConnectionPlan("site-a", "bus-a", (), 1e308, (1.0,)),
            ConnectionPlan("site-b", "bus-b", (), 1e308, (1.0,)),
        ),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    with pytest.raises(EvaluationInputError) as raised:
        evaluate_week(scenario, CONFIG, (plan,))

    assert "finite" in str(raised.value)


def test_malformed_canonical_ids_become_structured_evaluation_input_error():
    scenario = Scenario(
        "malformed-ids",
        "0.3.0",
        (Bus("bus-a", (10.0,)),),
        (),
        (40.0,),
        (100.0,),
        1.0,
    )
    plan = TeamPlan(
        "team-malformed-ids",
        connections=(ConnectionPlan(7, "bus-a", (), 1.0, (1.0,)),),  # type: ignore[arg-type]
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    with pytest.raises(EvaluationInputError) as raised:
        evaluate_week(scenario, CONFIG, (plan,))

    assert any("connection_id must be a string" in error for error in raised.value.errors)


@pytest.mark.parametrize(
    "field",
    (
        "curtailment_cost_per_mwh",
        "unserved_penalty_per_mwh",
        "emergency_energy_cost_per_mwh",
    ),
)
def test_boolean_evaluation_coefficients_are_rejected(field):
    scenario, plans = load_fixture_inputs()
    invalid_config = {
        "curtailment_cost_per_mwh": 5.0,
        "unserved_penalty_per_mwh": 500.0,
        "emergency_energy_cost_per_mwh": 80.0,
    }
    invalid_config[field] = True

    with pytest.raises(EvaluationInputError) as raised:
        evaluate_week(scenario, invalid_config, plans)

    assert f"{field} must be finite and non-negative" in raised.value.errors
