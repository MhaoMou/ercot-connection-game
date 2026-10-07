import math
import re
from dataclasses import FrozenInstanceError

import pytest

from ercot_game import GeneratorPlan
from ercot_game.recourse import (
    RecourseResult,
    dispatch_generators,
    repair_sites_with_curtailment,
    repair_with_curtailment,
)


def test_already_feasible_load_has_no_curtailment_or_unserved_energy():
    result = repair_with_curtailment(
        (8.0, 10.0),
        (10.0, 10.0),
        allocated_capacity_mw=6.0,
        k=2,
        mu=0.5,
        time_step_hours=2.0,
    )

    assert result == RecourseResult(
        feasible=True,
        served_mw=(8.0, 10.0),
        curtailed_mw=(0.0, 0.0),
        residual_unserved_mw=(0.0, 0.0),
        intervention_times=(),
        total_curtailed_mwh=0.0,
        total_unserved_mwh=0.0,
    )


def test_k_zero_cannot_repair_overload():
    result = repair_with_curtailment((12.0,), (10.0,), 10.0, k=0, mu=1.0, time_step_hours=1.0)

    assert not result.feasible
    assert result.served_mw == (10.0,)
    assert result.curtailed_mw == (0.0,)
    assert result.residual_unserved_mw == (2.0,)
    assert result.intervention_times == ()


def test_tiny_positive_overload_remains_unserved():
    result = repair_with_curtailment(
        (1e-13,), (0.0,), 1.0, k=0, mu=1.0, time_step_hours=1.0
    )

    assert not result.feasible
    assert result.residual_unserved_mw == (1e-13,)
    assert result.total_unserved_mwh == 1e-13


def test_zero_depth_cannot_repair_overload():
    result = repair_with_curtailment((12.0,), (10.0,), 10.0, k=1, mu=0.0, time_step_hours=1.0)

    assert not result.feasible
    assert result.curtailed_mw == (0.0,)
    assert result.residual_unserved_mw == (2.0,)
    assert result.intervention_times == ()


def test_largest_overloads_are_selected_with_earliest_time_tie_breaking():
    result = repair_with_curtailment(
        (15.0, 14.0, 15.0),
        (10.0, 10.0, 10.0),
        allocated_capacity_mw=10.0,
        k=2,
        mu=0.5,
        time_step_hours=1.0,
    )

    assert result.intervention_times == (0, 2)
    assert result.curtailed_mw == (5.0, 0.0, 5.0)
    assert result.residual_unserved_mw == (0.0, 4.0, 0.0)
    assert not result.feasible


def test_depth_limit_can_leave_residual_unserved_energy():
    result = repair_with_curtailment(
        (16.0, 12.0),
        (10.0, 10.0),
        allocated_capacity_mw=10.0,
        k=2,
        mu=0.25,
        time_step_hours=2.0,
    )

    assert result.curtailed_mw == (2.5, 2.0)
    assert result.residual_unserved_mw == (3.5, 0.0)
    assert result.served_mw == (10.0, 10.0)
    assert result.total_curtailed_mwh == pytest.approx(9.0)
    assert result.total_unserved_mwh == pytest.approx(7.0)
    assert not result.feasible


def test_energy_totals_and_complete_vectors_for_feasible_repair():
    result = repair_with_curtailment(
        (14.0, 8.0),
        (10.0, 10.0),
        allocated_capacity_mw=10.0,
        k=1,
        mu=0.5,
        time_step_hours=0.5,
    )

    assert result.feasible
    assert result.intervention_times == (0,)
    assert result.served_mw == (10.0, 8.0)
    assert result.curtailed_mw == (4.0, 0.0)
    assert result.residual_unserved_mw == (0.0, 0.0)
    assert result.total_curtailed_mwh == pytest.approx(2.0)
    assert result.total_unserved_mwh == 0.0


@pytest.mark.parametrize(
    ("requested", "available", "allocated", "k", "mu", "step", "message"),
    [
        ((1.0,), (), 1.0, 1, 1.0, 1.0, "requested load and available capacity must have equal lengths"),
        ((1.0,), (1.0, 1.0), 1.0, 1, 1.0, 1.0, "requested load and available capacity must have equal lengths"),
        ((math.inf,), (1.0,), 1.0, 1, 1.0, 1.0, "requested_load_mw[0] must be finite and non-negative"),
        ((1.0,), (math.nan,), 1.0, 1, 1.0, 1.0, "available_capacity_mw[0] must be finite and non-negative"),
        ((1.0,), (1.0,), math.inf, 1, 1.0, 1.0, "allocated_capacity_mw must be finite and non-negative"),
        ((1.0,), (1.0,), 1.0, -1, 1.0, 1.0, "k must be an integer greater than or equal to zero"),
        ((1.0,), (1.0,), 1.0, 1.0, 1.0, 1.0, "k must be an integer greater than or equal to zero"),
        ((1.0,), (1.0,), 1.0, 1, -0.1, 1.0, "mu must be between zero and one"),
        ((1.0,), (1.0,), 1.0, 1, 1.1, 1.0, "mu must be between zero and one"),
        ((1.0,), (1.0,), 1.0, 1, 1.0, -1.0, "time_step_hours must be finite and non-negative"),
    ],
)
def test_invalid_inputs_have_field_specific_errors(
    requested, available, allocated, k, mu, step, message
):
    with pytest.raises(ValueError, match=re.escape(message)):
        repair_with_curtailment(requested, available, allocated, k, mu, step)


def test_negative_load_or_capacity_is_rejected():
    with pytest.raises(ValueError, match=re.escape("requested_load_mw[0] must be finite and non-negative")):
        repair_with_curtailment((-1.0,), (1.0,), 1.0, 1, 1.0, 1.0)
    with pytest.raises(ValueError, match=re.escape("available_capacity_mw[0] must be finite and non-negative")):
        repair_with_curtailment((1.0,), (-1.0,), 1.0, 1, 1.0, 1.0)
    with pytest.raises(ValueError, match=re.escape("allocated_capacity_mw must be finite and non-negative")):
        repair_with_curtailment((1.0,), (1.0,), -1.0, 1, 1.0, 1.0)


def test_inputs_are_not_mutated():
    requested = [12.0, 8.0]
    available = [10.0, 10.0]

    result = repair_with_curtailment(requested, available, 10.0, 1, 0.5, 1.0)

    assert requested == [12.0, 8.0]
    assert available == [10.0, 10.0]
    with pytest.raises(FrozenInstanceError):
        result.feasible = False


def test_generators_dispatch_by_marginal_cost_then_id_with_site_caps():
    result = dispatch_generators(
        generators=(
            GeneratorPlan("gen-expensive", "site-a", 10.0, 20.0),
            GeneratorPlan("gen-cheap-b", "site-a", 2.0, 10.0),
            GeneratorPlan("gen-cheap-a", "site-a", 2.0, 10.0),
        ),
        requested_load_by_site={"site-a": (9.0,)},
        network_available_by_site={"site-a": (1.0,)},
    )

    assert result.dispatch_mw_by_generator == {
        "gen-cheap-a": (2.0,),
        "gen-cheap-b": (2.0,),
        "gen-expensive": (4.0,),
    }
    assert result.dispatch_mw_by_site == {"site-a": (8.0,)}
    assert result.total_dispatch_mw == (8.0,)


def test_generator_dispatch_result_is_immutable_and_detached():
    result = dispatch_generators(
        generators=(GeneratorPlan("gen-a", "site-a", 2.0, 1.0),),
        requested_load_by_site={"site-a": (2.0,)},
        network_available_by_site={"site-a": (0.0,)},
    )

    with pytest.raises(TypeError):
        result.dispatch_mw_by_generator["gen-b"] = (1.0,)  # type: ignore[index]
    with pytest.raises(TypeError):
        result.dispatch_mw_by_site["site-a"] = (0.0,)  # type: ignore[index]


def test_recourse_helpers_reject_mixed_type_site_ids_without_type_error():
    with pytest.raises(ValueError, match="site IDs must be strings"):
        dispatch_generators(
            generators=(),
            requested_load_by_site={"site-a": (1.0,), 7: (1.0,)},  # type: ignore[dict-item]
            network_available_by_site={"site-a": (1.0,), 7: (1.0,)},  # type: ignore[dict-item]
        )

    with pytest.raises(ValueError, match="site IDs must be strings"):
        repair_sites_with_curtailment(
            requested_load_by_site={"site-a": (1.0,), 7: (1.0,)},  # type: ignore[dict-item]
            available_capacity_by_site={"site-a": (1.0,), 7: (1.0,)},  # type: ignore[dict-item]
            allocated_capacity_mw=1.0,
            k=0,
            mu=0.0,
            time_step_hours=1.0,
        )


def test_site_recourse_aggregates_totals_and_retains_site_series():
    result = repair_sites_with_curtailment(
        requested_load_by_site={"site-b": (8.0,), "site-a": (8.0,)},
        available_capacity_by_site={"site-b": (3.0,), "site-a": (3.0,)},
        allocated_capacity_mw=10.0,
        k=1,
        mu=0.5,
        time_step_hours=1.0,
    )

    assert result.curtailed_mw == (5.0,)
    assert result.residual_unserved_mw == (5.0,)
    assert [(site.connection_id, site.curtailed_mw) for site in result.site_results] == [
        ("site-a", (5.0,)),
        ("site-b", (0.0,)),
    ]
