import math
from dataclasses import replace

import pytest

from ercot_game.models import ConnectionPlan, EvaluationConfig, GeneratorPlan, Scenario, TeamPlan
from ercot_game.scoring import ScoreBreakdown, calculate_score


def make_case(*, generator=True, flexibility_fee=0.0):
    scenario = Scenario(
        scenario_id="scenario-1",
        evaluator_version="0.3.0",
        buses=(),
        corridors=(),
        energy_price_per_mwh=(40.0,),
        it_value_per_mwh=(60.0,),
        time_step_hours=1.0,
    )
    plan = TeamPlan(
        team_id="team-1",
        bus_id="bus-1",
        path_corridors=(),
        capacity_mw=4.0,
        profile=(1.0,),
        generator=GeneratorPlan("gen-1", 1.0, 10.0) if generator else None,
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=flexibility_fee,
    )
    config = EvaluationConfig(
        curtailment_cost_per_mwh=3.0,
        unserved_penalty_per_mwh=100.0,
        emergency_energy_cost_per_mwh=80.0,
    )
    return scenario, config, plan


def test_hand_calculated_score_contains_every_component():
    scenario, config, plan = make_case()

    score = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(2.0,),
        generator_dispatch_mw=(1.0,),
        curtailed_mw=(2.0,),
        unserved_mw=(0.0,),
    )

    assert score == ScoreBreakdown(
        it_value=120.0,
        energy_cost=40.0,
        generator_cost=10.0,
        flexibility_fee=0.0,
        curtailment_cost=6.0,
        unserved_penalty=0.0,
        total=64.0,
    )


def test_flexibility_fee_is_charged_on_served_mwh():
    scenario, config, plan = make_case(flexibility_fee=2.5)

    score = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(2.0,),
        generator_dispatch_mw=(0.0,),
        curtailed_mw=(2.0,),
        unserved_mw=(0.0,),
    )

    assert score.flexibility_fee == pytest.approx(5.0)
    assert score.total == pytest.approx(29.0)


def test_unserved_penalty_is_larger_than_curtailment_cost_for_same_mwh():
    scenario, config, plan = make_case(generator=False)

    curtailed = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(3.0,),
        generator_dispatch_mw=(0.0,),
        curtailed_mw=(1.0,),
        unserved_mw=(0.0,),
    )
    unserved = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(3.0,),
        generator_dispatch_mw=(0.0,),
        curtailed_mw=(0.0,),
        unserved_mw=(1.0,),
    )

    assert unserved.unserved_penalty > curtailed.curtailment_cost


def test_generator_dispatch_cannot_exceed_capacity_or_exist_without_generator():
    scenario, config, plan = make_case()
    with pytest.raises(ValueError, match=r"generator_dispatch_mw\[0\].*capacity"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(2.0,),
            generator_dispatch_mw=(1.1,),
            curtailed_mw=(2.0,),
            unserved_mw=(0.0,),
        )

    scenario, config, plan = make_case(generator=False)
    with pytest.raises(ValueError, match=r"generator_dispatch_mw\[0\].*generator"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(2.0,),
            generator_dispatch_mw=(0.1,),
            curtailed_mw=(2.0,),
            unserved_mw=(0.0,),
        )


@pytest.mark.parametrize(
    ("field", "values", "message"),
    [
        ("served_load_mw", (1.0, 1.0), "length"),
        ("served_load_mw", (math.nan,), "finite and non-negative"),
        ("curtailed_mw", (-0.1,), "finite and non-negative"),
        ("unserved_mw", (math.inf,), "finite and non-negative"),
    ],
)
def test_series_are_validated(field, values, message):
    scenario, config, plan = make_case(generator=False)
    series = {
        "served_load_mw": (1.0,),
        "generator_dispatch_mw": (0.0,),
        "curtailed_mw": (0.0,),
        "unserved_mw": (0.0,),
    }
    series[field] = values

    with pytest.raises(ValueError, match=message):
        calculate_score(scenario, config, plan, **series)


def test_load_balance_rejects_excess_supply_components_and_dispatch_above_served():
    scenario, config, plan = make_case()
    with pytest.raises(ValueError, match="requested load"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(3.0,),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(2.0,),
            unserved_mw=(0.1,),
        )

    with pytest.raises(ValueError, match="served load"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(0.5,),
            generator_dispatch_mw=(0.6,),
            curtailed_mw=(3.5,),
            unserved_mw=(0.0,),
        )


def test_load_balance_rejects_under_accounting():
    scenario, config, plan = make_case(generator=False)

    with pytest.raises(ValueError, match="must equal requested load"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(2.0,),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(1.0,),
            unserved_mw=(0.0,),
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("energy_price_per_mwh", "energy_price_per_mwh"),
        ("it_value_per_mwh", "it_value_per_mwh"),
    ],
)
def test_scenario_coefficients_must_be_finite_and_nonnegative(field, message):
    scenario, config, plan = make_case(generator=False)
    invalid_scenario = replace(scenario, **{field: (-1.0,)})

    with pytest.raises(ValueError, match=message):
        calculate_score(
            invalid_scenario,
            config,
            plan,
            served_load_mw=(4.0,),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(0.0,),
            unserved_mw=(0.0,),
        )


def test_plan_generator_and_configuration_coefficients_must_be_nonnegative():
    scenario, config, plan = make_case()
    invalid_plans = (
        replace(plan, flexibility_fee_per_mwh=-1.0),
        replace(plan, generator=replace(plan.generator, marginal_cost_per_mwh=-1.0)),
    )
    for invalid_plan in invalid_plans:
        with pytest.raises(ValueError, match="coefficient"):
            calculate_score(
                scenario,
                config,
                invalid_plan,
                served_load_mw=(2.0,),
                generator_dispatch_mw=(1.0,),
                curtailed_mw=(2.0,),
                unserved_mw=(0.0,),
            )


def test_nonfinite_scoring_coefficients_are_rejected():
    scenario, config, plan = make_case()
    invalid_cases = (
        (replace(scenario, energy_price_per_mwh=(math.nan,)), config, plan),
        (scenario, config, replace(plan, flexibility_fee_per_mwh=math.inf)),
        (scenario, replace(config, emergency_energy_cost_per_mwh=math.nan), plan),
    )

    for invalid_scenario, invalid_config, invalid_plan in invalid_cases:
        with pytest.raises(ValueError, match="coefficient"):
            calculate_score(
                invalid_scenario,
                invalid_config,
                invalid_plan,
                served_load_mw=(2.0,),
                generator_dispatch_mw=(1.0,),
                curtailed_mw=(2.0,),
                unserved_mw=(0.0,),
            )


def test_finite_but_overflowing_score_products_use_value_error_validation():
    scenario, config, plan = make_case(generator=False)
    overflowing_scenario = replace(scenario, energy_price_per_mwh=(1e308,))

    with pytest.raises(ValueError, match="score components must be finite"):
        calculate_score(
            overflowing_scenario,
            config,
            replace(plan, capacity_mw=1e308),
            served_load_mw=(1e308,),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(0.0,),
            unserved_mw=(0.0,),
        )


def test_fsum_overflow_from_finite_series_uses_value_error_validation():
    scenario, config, plan = make_case(generator=False)
    scenario = replace(
        scenario,
        energy_price_per_mwh=(0.0, 0.0),
        it_value_per_mwh=(0.0, 0.0),
    )
    plan = replace(plan, capacity_mw=1e308, profile=(1.0, 1.0))

    with pytest.raises(ValueError, match="score components must be finite"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(1e308, 1e308),
            generator_dispatch_mw=(0.0, 0.0),
            curtailed_mw=(0.0, 0.0),
            unserved_mw=(0.0, 0.0),
        )


def test_final_cost_aggregation_overflow_uses_value_error_validation():
    scenario, config, plan = make_case()
    scenario = replace(scenario, energy_price_per_mwh=(1e308,))
    plan = replace(
        plan,
        capacity_mw=2.0,
        generator=GeneratorPlan("gen-1", 1.0, 1e308),
    )

    with pytest.raises(ValueError, match="score components must be finite"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(2.0,),
            generator_dispatch_mw=(1.0,),
            curtailed_mw=(0.0,),
            unserved_mw=(0.0,),
        )


def test_balance_uses_scale_aware_relative_tolerance():
    scenario, config, plan = make_case(generator=False)
    large_requested = 1e9
    scenario = replace(scenario, energy_price_per_mwh=(0.0,), it_value_per_mwh=(1.0,))
    plan = replace(plan, capacity_mw=large_requested)

    within_tolerance = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(large_requested * (1.0 + 0.5e-9),),
        generator_dispatch_mw=(0.0,),
        curtailed_mw=(0.0,),
        unserved_mw=(0.0,),
    )
    assert within_tolerance.it_value == pytest.approx(large_requested * (1.0 + 0.5e-9))

    with pytest.raises(ValueError, match="must equal requested load"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(large_requested * (1.0 + 2e-9),),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(0.0,),
            unserved_mw=(0.0,),
        )


def test_zero_requested_load_rejects_any_nonzero_accounted_load():
    scenario, config, plan = make_case(generator=False)
    plan = replace(plan, capacity_mw=0.0)

    with pytest.raises(ValueError, match="must equal requested load"):
        calculate_score(
            scenario,
            config,
            plan,
            served_load_mw=(1e-12,),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(0.0,),
            unserved_mw=(0.0,),
        )


def test_emergency_cost_is_reserved_for_evaluator_layer():
    scenario, config, plan = make_case(generator=False)
    baseline = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(3.0,),
        generator_dispatch_mw=(0.0,),
        curtailed_mw=(1.0,),
        unserved_mw=(0.0,),
    )
    changed_emergency_cost = calculate_score(
        scenario,
        replace(config, emergency_energy_cost_per_mwh=1e6),
        plan,
        served_load_mw=(3.0,),
        generator_dispatch_mw=(0.0,),
        curtailed_mw=(1.0,),
        unserved_mw=(0.0,),
    )

    assert changed_emergency_cost == baseline


def test_multi_period_scoring_applies_time_step_to_each_component():
    scenario = Scenario(
        scenario_id="scenario-2",
        evaluator_version="0.3.0",
        buses=(),
        corridors=(),
        energy_price_per_mwh=(20.0, 40.0),
        it_value_per_mwh=(100.0, 200.0),
        time_step_hours=0.5,
    )
    config = EvaluationConfig(4.0, 100.0, 80.0)
    plan = TeamPlan(
        "team-2",
        "bus-2",
        (),
        10.0,
        (1.0, 0.5),
        GeneratorPlan("gen-2", 2.0, 5.0),
        0,
        0.0,
        3.0,
    )

    score = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(8.0, 4.0),
        generator_dispatch_mw=(2.0, 1.0),
        curtailed_mw=(2.0, 1.0),
        unserved_mw=(0.0, 0.0),
    )

    assert score.it_value == pytest.approx(800.0)
    assert score.energy_cost == pytest.approx(120.0)
    assert score.generator_cost == pytest.approx(7.5)
    assert score.flexibility_fee == pytest.approx(18.0)
    assert score.curtailment_cost == pytest.approx(6.0)
    assert score.unserved_penalty == pytest.approx(0.0)
    assert score.total == pytest.approx(648.5)

    for field in (
        "curtailment_cost_per_mwh",
        "unserved_penalty_per_mwh",
        "emergency_energy_cost_per_mwh",
    ):
        invalid_config = replace(config, **{field: -1.0})
        with pytest.raises(ValueError, match="coefficient"):
            calculate_score(
                scenario,
                invalid_config,
                plan,
                served_load_mw=(8.0, 4.0),
                generator_dispatch_mw=(1.0, 1.0),
                curtailed_mw=(2.0, 1.0),
                unserved_mw=(0.0, 0.0),
            )


def test_multi_generator_score_uses_each_generators_marginal_cost():
    scenario, config, _ = make_case(generator=False)
    plan = TeamPlan(
        "team-1",
        connections=(ConnectionPlan("site-a", "bus-1", (), 10.0, (1.0,)),),
        generators=(
            GeneratorPlan("gen-b", "site-a", 10.0, 20.0),
            GeneratorPlan("gen-a", "site-a", 10.0, 10.0),
        ),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    score = calculate_score(
        scenario,
        config,
        plan,
        served_load_mw=(4.0,),
        generator_dispatch_mw=(3.0,),
        curtailed_mw=(0.0,),
        unserved_mw=(0.0,),
        generator_dispatch_by_generator={"gen-a": (2.0,), "gen-b": (1.0,)},
        requested_load_mw=(4.0,),
    )

    assert score.generator_cost == pytest.approx(40.0)


@pytest.mark.parametrize(
    "generator",
    [
        GeneratorPlan("gen-a", "connection-legacy", math.nan, 10.0),
        GeneratorPlan("gen-a", "connection-legacy", 2.0, math.inf),
        GeneratorPlan("gen-a", "connection-legacy", -1.0, 10.0),
        GeneratorPlan("gen-a", "connection-legacy", 2.0, -1.0),
    ],
)
def test_standalone_scoring_validates_generator_parameters(generator):
    scenario, config, plan = make_case()
    invalid_plan = replace(plan, generator=generator)

    with pytest.raises(ValueError, match="generator"):
        calculate_score(
            scenario,
            config,
            invalid_plan,
            served_load_mw=(2.0,),
            generator_dispatch_mw=(1.0,),
            curtailed_mw=(2.0,),
            unserved_mw=(0.0,),
        )


@pytest.mark.parametrize(
    "field",
    (
        "curtailment_cost_per_mwh",
        "unserved_penalty_per_mwh",
        "emergency_energy_cost_per_mwh",
    ),
)
def test_scoring_rejects_boolean_configuration_coefficients(field):
    scenario, config, plan = make_case(generator=False)
    invalid_config = replace(config, **{field: True})

    with pytest.raises(ValueError, match="coefficient"):
        calculate_score(
            scenario,
            invalid_config,
            plan,
            served_load_mw=(4.0,),
            generator_dispatch_mw=(0.0,),
            curtailed_mw=(0.0,),
            unserved_mw=(0.0,),
        )
