import pytest

from ercot_game import Bus, ConnectionPlan, Corridor, Scenario, TeamPlan
from ercot_game.allocation import AllocationResult, allocate_shared_capacity


def make_scenario(
    *,
    bus_headroom: tuple[float, ...] = (100.0, 100.0),
    corridor_capacity: tuple[float, ...] = (100.0, 100.0),
) -> Scenario:
    return Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", bus_headroom), Bus("bus-b", (100.0, 100.0))),
        (Corridor("corridor-1", corridor_capacity), Corridor("corridor-2", (100.0, 100.0))),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )


def make_plan(team_id: str, **overrides: object) -> TeamPlan:
    values: dict[str, object] = {
        "team_id": team_id,
        "bus_id": "bus-a",
        "path_corridors": ("corridor-1",),
        "capacity_mw": 40.0,
        "profile": (1.0, 0.5),
        "generator": None,
        "intervention_budget_k": 0,
        "curtailment_depth_mu": 0.0,
        "flexibility_fee_per_mwh": 0.0,
    }
    values.update(overrides)
    return TeamPlan(**values)  # type: ignore[arg-type]


def test_reversed_submission_order_gives_identical_allocation_results():
    scenario = make_scenario(bus_headroom=(60.0, 60.0), corridor_capacity=(100.0, 100.0))
    plans = (make_plan("team-b"), make_plan("team-a"))

    assert allocate_shared_capacity(scenario, plans) == allocate_shared_capacity(
        scenario, tuple(reversed(plans))
    )


def test_allocation_does_not_overload_any_resource():
    scenario = make_scenario(bus_headroom=(60.0, 60.0), corridor_capacity=(100.0, 100.0))
    results = allocate_shared_capacity(scenario, (make_plan("team-a"), make_plan("team-b")))

    assert sum(result.allocated_capacity_mw for result in results.values()) <= 60.0
    assert all(result.allocated_capacity_mw <= 40.0 for result in results.values())


def test_one_binding_bus_limits_team_ratio():
    scenario = make_scenario(bus_headroom=(60.0, 60.0), corridor_capacity=(100.0, 100.0))
    results = allocate_shared_capacity(scenario, (make_plan("team-a"), make_plan("team-b")))

    assert results["team-a"].resource_ratio_by_time == (0.75, 1.0)
    assert results["team-a"].allocated_capacity_mw == pytest.approx(30.0)
    assert results["team-a"].binding_resources == ("bus:bus-a",)


def test_one_binding_corridor_limits_team_ratio():
    scenario = make_scenario(bus_headroom=(100.0, 100.0), corridor_capacity=(60.0, 60.0))
    results = allocate_shared_capacity(scenario, (make_plan("team-a"), make_plan("team-b")))

    assert results["team-a"].resource_ratio_by_time == (0.75, 1.0)
    assert results["team-a"].allocated_capacity_mw == pytest.approx(30.0)
    assert results["team-a"].binding_resources == ("corridor:corridor-1",)


def test_multiple_binding_resources_are_reported_in_sorted_order():
    scenario = make_scenario(bus_headroom=(60.0, 60.0), corridor_capacity=(60.0, 60.0))
    plan = make_plan("team-a", path_corridors=("corridor-2", "corridor-1"))

    result = allocate_shared_capacity(scenario, (plan,))["team-a"]

    assert result.resource_ratio_by_time == (1.0, 1.0)
    assert result.binding_resources == ()

    scenario = make_scenario(bus_headroom=(30.0, 30.0), corridor_capacity=(30.0, 30.0))
    result = allocate_shared_capacity(scenario, (plan,))["team-a"]
    assert result.resource_ratio_by_time == (0.75, 1.0)
    assert result.binding_resources == (
        "bus:bus-a",
        "corridor:corridor-1",
    )


def test_zero_requested_capacity_has_full_ratio_and_no_binding_resources():
    result = allocate_shared_capacity(
        make_scenario(bus_headroom=(0.0, 0.0), corridor_capacity=(0.0, 0.0)),
        (make_plan("team-a", capacity_mw=0.0, profile=(1.0, 1.0)),),
    )["team-a"]

    assert result == AllocationResult("team-a", 0.0, (1.0, 1.0), ())


def test_time_slots_are_handled_by_profile_index_not_timestamps_or_input_order():
    scenario = make_scenario(bus_headroom=(60.0, 30.0), corridor_capacity=(100.0, 100.0))
    plan = make_plan("team-a", capacity_mw=40.0, profile=(0.5, 1.0))

    result = allocate_shared_capacity(scenario, (plan,))["team-a"]

    assert result.resource_ratio_by_time == (1.0, 0.75)
    assert result.allocated_capacity_mw == pytest.approx(30.0)


def test_duplicate_team_ids_are_rejected_deterministically():
    with pytest.raises(ValueError, match="duplicate team_id: team-a"):
        allocate_shared_capacity(make_scenario(), (make_plan("team-a"), make_plan("team-a")))


def test_duplicate_bus_ids_are_rejected_before_allocation():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", (100.0, 100.0)), Bus("bus-a", (1.0, 1.0))),
        (Corridor("corridor-1", (100.0, 100.0)),),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )

    with pytest.raises(ValueError, match="duplicate bus_id: bus-a"):
        allocate_shared_capacity(scenario, (make_plan("team-a"),))


def test_duplicate_corridor_ids_are_rejected_before_allocation():
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-a", (100.0, 100.0)),),
        (
            Corridor("corridor-1", (100.0, 100.0)),
            Corridor("corridor-1", (1.0, 1.0)),
        ),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )

    with pytest.raises(ValueError, match="duplicate corridor_id: corridor-1"):
        allocate_shared_capacity(scenario, (make_plan("team-a"),))


def test_reordered_invalid_resources_have_identical_diagnostics():
    first = Scenario(
        "scenario-1",
        "0.3.0",
        (Bus("bus-z", (100.0,)), Bus("bus-a", (100.0, 100.0))),
        (Corridor("corridor-z", (100.0,)), Corridor("corridor-a", (100.0, 100.0))),
        (30.0, 31.0),
        (100.0, 100.0),
        1.0,
    )
    second = Scenario(
        "scenario-1",
        "0.3.0",
        tuple(reversed(first.buses)),
        tuple(reversed(first.corridors)),
        first.energy_price_per_mwh,
        first.it_value_per_mwh,
        first.time_step_hours,
    )

    with pytest.raises(ValueError) as first_error:
        allocate_shared_capacity(first, ())
    with pytest.raises(ValueError) as second_error:
        allocate_shared_capacity(second, ())

    assert str(first_error.value) == str(second_error.value)


def test_mixed_magnitude_requests_use_fsum_for_aggregate_ratios():
    scenario = make_scenario(bus_headroom=(1_000_000_000_000_000.0,) * 2)
    plans = (
        make_plan("team-a", capacity_mw=0.125, path_corridors=()),
        make_plan("team-b", capacity_mw=1_000_000_000_000_000.0, path_corridors=()),
    )

    results = allocate_shared_capacity(scenario, plans)

    assert results["team-a"].resource_ratio_by_time[0] < 1.0
    assert results["team-b"].resource_ratio_by_time[0] < 1.0


def test_near_equal_resource_ratios_are_reported_as_co_binding():
    scenario = make_scenario(
        bus_headroom=(50.0, 50.0),
        corridor_capacity=(50.00000000001, 50.00000000001),
    )

    result = allocate_shared_capacity(
        scenario, (make_plan("team-a", capacity_mw=100.0),)
    )["team-a"]

    assert result.binding_resources == ("bus:bus-a", "corridor:corridor-1")


def test_resource_declaration_order_does_not_change_results():
    scenario = make_scenario(bus_headroom=(60.0, 40.0), corridor_capacity=(50.0, 70.0))
    reordered = Scenario(
        scenario.scenario_id,
        scenario.evaluator_version,
        tuple(reversed(scenario.buses)),
        tuple(reversed(scenario.corridors)),
        scenario.energy_price_per_mwh,
        scenario.it_value_per_mwh,
        scenario.time_step_hours,
    )
    plans = (
        make_plan("team-b", bus_id="bus-b", path_corridors=("corridor-2",)),
        make_plan("team-a"),
    )

    assert allocate_shared_capacity(scenario, plans) == allocate_shared_capacity(
        reordered, plans
    )


def test_each_time_slot_respects_the_tightest_resource_limit():
    scenario = make_scenario(bus_headroom=(30.0, 60.0), corridor_capacity=(60.0, 20.0))
    plans = (
        make_plan("team-a", profile=(1.0, 1.0)),
        make_plan("team-b", profile=(1.0, 1.0)),
    )
    results = allocate_shared_capacity(scenario, plans)

    assert results["team-a"].resource_ratio_by_time == (0.375, 0.25)
    for time_index in range(2):
        allocated_load = sum(
            plan.capacity_mw * plan.profile[time_index]
            * results[plan.team_id].resource_ratio_by_time[time_index]
            for plan in plans
        )
        assert allocated_load <= scenario.buses[0].headroom_mw_by_time[time_index]
        assert allocated_load <= scenario.corridors[0].capacity_mw_by_time[time_index]


def test_invalid_scenario_and_plan_are_rejected():
    with pytest.raises(ValueError, match="unknown bus_id: missing"):
        allocate_shared_capacity(
            make_scenario(), (make_plan("team-a", bus_id="missing"),)
        )


def test_multi_site_allocation_uses_each_sites_bus_resources():
    scenario = Scenario(
        "multi-site",
        "0.3.0",
        (Bus("bus-a", (10.0,)), Bus("bus-b", (30.0,))),
        (),
        (30.0,),
        (100.0,),
        1.0,
    )
    plan = TeamPlan(
        "team-a",
        connections=(
            ConnectionPlan("site-a", "bus-a", (), 20.0, (1.0,)),
            ConnectionPlan("site-b", "bus-b", (), 20.0, (1.0,)),
        ),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    result = allocate_shared_capacity(scenario, (plan,))["team-a"]

    assert [(site.connection_id, site.allocated_capacity_mw) for site in result.site_results] == [
        ("site-a", 10.0),
        ("site-b", 20.0),
    ]
    assert result.site_results[0].binding_resources == ("bus:bus-a",)
    assert result.site_results[0].curtailed_mw_by_time == (10.0,)
    assert result.site_results[1].binding_resources == ()


def test_shared_corridor_is_consumed_by_sorted_connection_id():
    scenario = Scenario(
        "shared-corridor",
        "0.3.0",
        (Bus("bus-a", (100.0,)), Bus("bus-b", (100.0,))),
        (Corridor("corridor-shared", (10.0,)),),
        (30.0,),
        (100.0,),
        1.0,
    )
    plan = TeamPlan(
        "team-a",
        connections=(
            ConnectionPlan("site-z", "bus-a", ("corridor-shared",), 8.0, (1.0,)),
            ConnectionPlan("site-a", "bus-b", ("corridor-shared",), 8.0, (1.0,)),
        ),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )

    result = allocate_shared_capacity(scenario, (plan,))["team-a"]
    by_site = {site.connection_id: site for site in result.site_results}

    assert by_site["site-a"].resource_ratio_by_time == (1.0,)
    assert by_site["site-z"].resource_ratio_by_time == (0.25,)
    assert by_site["site-z"].curtailed_mw_by_time == (6.0,)
    assert by_site["site-z"].binding_resources == ("corridor:corridor-shared",)

    reversed_plan = TeamPlan(
        "team-a",
        connections=tuple(reversed(plan.connections)),
        generators=(),
        intervention_budget_k=0,
        curtailment_depth_mu=0.0,
        flexibility_fee_per_mwh=0.0,
    )
    assert allocate_shared_capacity(scenario, (reversed_plan,)) == allocate_shared_capacity(
        scenario, (plan,)
    )


def test_canonical_one_site_teams_share_corridor_in_connection_id_order():
    scenario = Scenario(
        "canonical-one-site-corridor",
        "0.3.0",
        (Bus("bus-a", (100.0,)), Bus("bus-b", (100.0,))),
        (Corridor("corridor-shared", (10.0,)),),
        (30.0,),
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

    results = allocate_shared_capacity(scenario, tuple(reversed(plans)))

    assert results["team-a"].site_results[0].resource_ratio_by_time == (1.0,)
    assert results["team-z"].site_results[0].resource_ratio_by_time == (0.25,)


def test_allocation_rejects_duplicate_corridors_within_a_connection():
    with pytest.raises(ValueError, match="duplicate corridor_id"):
        allocate_shared_capacity(
            make_scenario(),
            (make_plan("team-a", path_corridors=("corridor-1", "corridor-1")),),
        )


def test_allocation_rejects_mixed_type_team_ids_without_type_error():
    with pytest.raises(ValueError, match="team_id must be a string"):
        allocate_shared_capacity(make_scenario(), (make_plan("team-a"), make_plan(7)))  # type: ignore[arg-type]


@pytest.mark.parametrize("resource", ("bus", "corridor"))
def test_allocation_rejects_mixed_type_resource_ids_without_type_error(resource: str):
    scenario = Scenario(
        "scenario-1",
        "0.3.0",
        (
            (Bus("bus-a", (100.0,)), Bus(7, (100.0,)))
            if resource == "bus"
            else (Bus("bus-a", (100.0,)),)
        ),
        (
            (Corridor("corridor-1", (100.0,)), Corridor(7, (100.0,)))
            if resource == "corridor"
            else (Corridor("corridor-1", (100.0,)),)
        ),
        (30.0,),
        (100.0,),
        1.0,
    )

    with pytest.raises(ValueError, match=f"{resource}_id must be a string"):
        allocate_shared_capacity(scenario, (make_plan("team-a", profile=(1.0,)),))  # type: ignore[arg-type]
