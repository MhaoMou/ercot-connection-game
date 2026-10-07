"""Order-independent proportional allocation of shared network capacity."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from .models import Scenario, TeamPlan
from .validate import validate_plan, validate_scenario


# Ratios within this tolerance represent the same limiting resource in the
# diagnostics, while the allocation itself still uses the exact minimum.
_BINDING_RATIO_REL_TOL = 1e-12
_BINDING_RATIO_ABS_TOL = 1e-12


def _safe_fsum(values: tuple[float, ...], label: str) -> float:
    try:
        total = math.fsum(values)
    except OverflowError:
        raise ValueError(f"{label} must be finite") from None
    if not math.isfinite(total):
        raise ValueError(f"{label} must be finite")
    return total


@dataclass(frozen=True)
class SiteAllocationResult:
    """Allocation and congestion diagnostics for one connection site."""

    connection_id: str
    bus_id: str
    allocated_capacity_mw: float
    resource_ratio_by_time: tuple[float, ...]
    binding_resources: tuple[str, ...]
    curtailed_mw_by_time: tuple[float, ...]


@dataclass(frozen=True)
class AllocationResult:
    team_id: str
    allocated_capacity_mw: float
    resource_ratio_by_time: tuple[float, ...]
    binding_resources: tuple[str, ...]
    site_results: tuple[SiteAllocationResult, ...] = field(default=(), compare=False)
    binding_site_ids: tuple[str, ...] = field(default=(), compare=False)
    curtailed_site_ids: tuple[str, ...] = field(default=(), compare=False)

    @property
    def site_allocations(self) -> tuple[SiteAllocationResult, ...]:
        """Compatibility alias for callers that use the allocation vocabulary."""
        return self.site_results


def _multi_site_allocation(
    scenario: Scenario,
    ordered_plans: tuple[TeamPlan, ...],
    bus_by_id: dict[str, object],
    corridor_by_id: dict[str, object],
) -> dict[str, AllocationResult]:
    """Allocate canonical sites, with deterministic residual corridor use.

    Bus sharing retains the Phase 1 proportional rule.  Corridors are shared
    sequentially in canonical ``(connection_id, team_id)`` order, which makes
    the result independent of submission and declaration order while exposing
    the site that encountered the residual bottleneck.
    """
    horizon = len(scenario.energy_price_per_mwh)
    sites = tuple(
        sorted(
            (
                (plan.team_id, connection)
                for plan in ordered_plans
                for connection in plan.connections
            ),
            key=lambda item: (str(item[1].connection_id), str(item[0])),
        )
    )
    requests: dict[tuple[str, str], tuple[float, ...]] = {}
    for team_id, connection in sites:
        request = tuple(
            connection.capacity_mw * connection.profile[t] for t in range(horizon)
        )
        if any(not math.isfinite(value) or value < 0.0 for value in request):
            raise ValueError(
                f"requested load for site {connection.connection_id} of team "
                f"{team_id} must be finite and non-negative"
            )
        requests[(team_id, connection.connection_id)] = request

    bus_requesters: dict[str, list[tuple[str, str]]] = {}
    for team_id, connection in sites:
        bus_requesters.setdefault(connection.bus_id, []).append(
            (team_id, connection.connection_id)
        )
    bus_ratios: dict[str, tuple[float, ...]] = {}
    for bus_id, requester_ids in sorted(bus_requesters.items()):
        capacities = bus_by_id[bus_id].headroom_mw_by_time  # type: ignore[union-attr]
        ratios: list[float] = []
        for time_index in range(horizon):
            total_requested = _safe_fsum(
                tuple(requests[site_id][time_index] for site_id in requester_ids),
                f"aggregate request for bus {bus_id} at time {time_index}",
            )
            ratios.append(
                1.0
                if total_requested == 0.0
                else min(1.0, capacities[time_index] / total_requested)
            )
        bus_ratios[bus_id] = tuple(ratios)

    remaining_corridor = {
        corridor_id: list(corridor.capacity_mw_by_time)  # type: ignore[union-attr]
        for corridor_id, corridor in sorted(corridor_by_id.items())
    }
    site_results_by_id: dict[tuple[str, str], SiteAllocationResult] = {}
    for team_id, connection in sites:
        site_id = (team_id, connection.connection_id)
        request = requests[site_id]
        ratios: list[float] = []
        corridor_ratios_by_id: dict[str, list[float]] = {
            corridor_id: [] for corridor_id in connection.path_corridors
        }
        for time_index in range(horizon):
            ratio = bus_ratios[connection.bus_id][time_index]
            for corridor_id in sorted(connection.path_corridors):
                requested = request[time_index]
                corridor_ratio = (
                    1.0
                    if requested == 0.0
                    else min(1.0, remaining_corridor[corridor_id][time_index] / requested)
                )
                corridor_ratios_by_id[corridor_id].append(corridor_ratio)
                ratio = min(ratio, corridor_ratio)
            ratios.append(ratio)
        allocated_by_time = tuple(request[t] * ratios[t] for t in range(horizon))
        if any(not math.isfinite(value) or value < 0.0 for value in allocated_by_time):
            raise ValueError(
                f"allocated load for site {connection.connection_id} of team "
                f"{team_id} must be finite and non-negative"
            )
        for corridor_id in connection.path_corridors:
            remaining_corridor[corridor_id] = [
                max(0.0, remaining - allocated)
                for remaining, allocated in zip(
                    remaining_corridor[corridor_id], allocated_by_time
                )
            ]
        site_ratio = tuple(ratios)
        binding_resources = []
        resource_ratios = {
            f"bus:{connection.bus_id}": bus_ratios[connection.bus_id],
            **{
                f"corridor:{corridor_id}": tuple(corridor_ratios_by_id[corridor_id])
                for corridor_id in sorted(connection.path_corridors)
            },
        }
        for resource_id, resource_ratios_by_time in sorted(resource_ratios.items()):
            if any(
                resource_ratios_by_time[t] < 1.0
                and math.isclose(
                    resource_ratios_by_time[t], site_ratio[t],
                    rel_tol=_BINDING_RATIO_REL_TOL,
                    abs_tol=_BINDING_RATIO_ABS_TOL,
                )
                and request[t] > 0.0
                for t in range(horizon)
            ):
                binding_resources.append(resource_id)
        allocated_capacity = connection.capacity_mw * min(site_ratio, default=1.0)
        if not math.isfinite(allocated_capacity) or allocated_capacity < 0.0:
            raise ValueError(
                f"allocated capacity for site {connection.connection_id} of team "
                f"{team_id} must be finite and non-negative"
            )
        site_results_by_id[site_id] = SiteAllocationResult(
            connection_id=connection.connection_id,
            bus_id=connection.bus_id,
            allocated_capacity_mw=allocated_capacity,
            resource_ratio_by_time=site_ratio,
            binding_resources=tuple(binding_resources),
            curtailed_mw_by_time=tuple(request[t] - allocated_by_time[t] for t in range(horizon)),
        )

    results: dict[str, AllocationResult] = {}
    for plan in ordered_plans:
        sites_for_team = tuple(
            site_results_by_id[(plan.team_id, connection.connection_id)]
            for connection in sorted(plan.connections, key=lambda item: str(item.connection_id))
        )
        total_requested = tuple(
            _safe_fsum(
                tuple(
                    requests[(plan.team_id, connection.connection_id)][t]
                    for connection in plan.connections
                ),
                f"aggregate request for team {plan.team_id} at time {t}",
            )
            for t in range(horizon)
        )
        total_allocated = tuple(
            _safe_fsum(
                tuple(
                    requests[(plan.team_id, connection.connection_id)][t]
                    * site_results_by_id[(plan.team_id, connection.connection_id)].resource_ratio_by_time[t]
                    for connection in plan.connections
                ),
                f"allocated request for team {plan.team_id} at time {t}",
            )
            for t in range(horizon)
        )
        team_ratios = tuple(
            1.0 if total_requested[t] == 0.0 else total_allocated[t] / total_requested[t]
            for t in range(horizon)
        )
        results[plan.team_id] = AllocationResult(
            team_id=plan.team_id,
            allocated_capacity_mw=_safe_fsum(
                tuple(site.allocated_capacity_mw for site in sites_for_team),
                f"allocated capacity for team {plan.team_id}",
            ),
            resource_ratio_by_time=team_ratios,
            binding_resources=tuple(
                sorted({resource for site in sites_for_team for resource in site.binding_resources})
            ),
            site_results=sites_for_team,
            binding_site_ids=tuple(
                site.connection_id
                for site in sites_for_team
                if site.binding_resources
            ),
            curtailed_site_ids=tuple(
                site.connection_id
                for site in sites_for_team
                if any(amount > 0.0 for amount in site.curtailed_mw_by_time)
            ),
        )
    return results


def allocate_shared_capacity(
    scenario: Scenario,
    plans: tuple[TeamPlan, ...],
) -> dict[str, AllocationResult]:
    """Allocate shared bus and corridor capacity proportionally by time slot.

    Requests are aggregated by resource before ratios are calculated.  All
    externally visible iteration is sorted, so neither plan order nor resource
    declaration order affects the result.
    """
    scenario_errors = sorted(validate_scenario(scenario))
    if scenario_errors:
        raise ValueError("; ".join(scenario_errors))

    duplicate_resource_errors = [
        f"duplicate bus_id: {bus_id}"
        for bus_id in sorted(
            {
                bus.bus_id
                for bus in scenario.buses
                if sum(candidate.bus_id == bus.bus_id for candidate in scenario.buses) > 1
            }
        )
    ]
    duplicate_resource_errors.extend(
        f"duplicate corridor_id: {corridor_id}"
        for corridor_id in sorted(
            {
                corridor.corridor_id
                for corridor in scenario.corridors
                if sum(
                    candidate.corridor_id == corridor.corridor_id
                    for candidate in scenario.corridors
                )
                > 1
            }
        )
    )
    if duplicate_resource_errors:
        raise ValueError("; ".join(duplicate_resource_errors))

    team_ids = [plan.team_id for plan in plans]
    if any(not isinstance(team_id, str) for team_id in team_ids):
        raise ValueError("team_id must be a string")
    duplicate_team_ids = sorted({team_id for team_id in team_ids if team_ids.count(team_id) > 1})
    if duplicate_team_ids:
        raise ValueError(f"duplicate team_id: {duplicate_team_ids[0]}")

    ordered_plans = tuple(sorted(plans, key=lambda plan: str(plan.team_id)))
    plan_errors = [
        (plan.team_id, error)
        for plan in ordered_plans
        for error in sorted(validate_plan(plan, scenario))
    ]
    if plan_errors:
        raise ValueError("; ".join(f"{team_id}: {error}" for team_id, error in plan_errors))

    horizon = len(scenario.energy_price_per_mwh)
    bus_by_id = {bus.bus_id: bus for bus in scenario.buses}
    corridor_by_id = {corridor.corridor_id: corridor for corridor in scenario.corridors}

    legacy_proportional_path = all(
        len(plan.connections) == 1
        and plan.connections[0].connection_id == "connection-legacy"
        for plan in ordered_plans
    )
    if not legacy_proportional_path:
        return _multi_site_allocation(
            scenario, ordered_plans, bus_by_id, corridor_by_id
        )

    resources: dict[str, tuple[float, ...]] = {
        f"bus:{bus_id}": bus_by_id[bus_id].headroom_mw_by_time
        for bus_id in sorted(bus_by_id)
    }
    resources.update(
        {
            f"corridor:{corridor_id}": corridor_by_id[corridor_id].capacity_mw_by_time
            for corridor_id in sorted(corridor_by_id)
        }
    )
    for resource_id, capacities in resources.items():
        if any(capacity < 0 for capacity in capacities):
            raise ValueError(f"{resource_id} capacity must be non-negative")

    requests_by_team: dict[str, tuple[float, ...]] = {
        plan.team_id: tuple(plan.capacity_mw * plan.profile[t] for t in range(horizon))
        for plan in ordered_plans
    }
    for team_id in sorted(requests_by_team):
        for time_index, requested_load in enumerate(requests_by_team[team_id]):
            if not math.isfinite(requested_load):
                raise ValueError(
                    f"requested load for team {team_id} at time {time_index} must be finite"
                )
    resource_ids_by_team = {
        plan.team_id: tuple(
            sorted(
                {f"bus:{plan.bus_id}"}
                | {f"corridor:{corridor_id}" for corridor_id in plan.path_corridors}
            )
        )
        for plan in ordered_plans
    }

    ratio_by_resource: dict[str, tuple[float, ...]] = {}
    for resource_id in sorted(resources):
        requesting_team_ids = tuple(
            team_id
            for team_id in sorted(requests_by_team)
            if resource_id in resource_ids_by_team[team_id]
        )
        totals_list: list[float] = []
        for time_index in range(horizon):
            try:
                total_requested = math.fsum(
                    requests_by_team[team_id][time_index]
                    for team_id in requesting_team_ids
                )
            except OverflowError:
                raise ValueError(
                    f"aggregate request for {resource_id} at time {time_index} must be finite"
                ) from None
            totals_list.append(total_requested)
        totals = tuple(totals_list)
        for time_index, total_requested in enumerate(totals):
            if not math.isfinite(total_requested):
                raise ValueError(
                    f"aggregate request for {resource_id} at time {time_index} must be finite"
                )
        ratios = tuple(
            1.0
            if total_requested == 0.0
            else min(1.0, resources[resource_id][t] / total_requested)
            for t, total_requested in enumerate(totals)
        )
        for time_index, ratio in enumerate(ratios):
            if not math.isfinite(ratio):
                raise ValueError(
                    f"allocation ratio for {resource_id} at time {time_index} must be finite"
                )
        ratio_by_resource[resource_id] = ratios

    results: dict[str, AllocationResult] = {}
    for plan in ordered_plans:
        resource_ids = resource_ids_by_team[plan.team_id]
        team_ratios = tuple(
            min((ratio_by_resource[resource_id][t] for resource_id in resource_ids), default=1.0)
            for t in range(horizon)
        )
        allocated_capacity = plan.capacity_mw * min(team_ratios, default=1.0)
        if any(not math.isfinite(ratio) for ratio in team_ratios):
            raise ValueError(f"allocation ratios for team {plan.team_id} must be finite")
        if not math.isfinite(allocated_capacity):
            raise ValueError(
                f"allocated capacity for team {plan.team_id} must be finite"
            )
        binding_resources = tuple(
            resource_id
            for resource_id in resource_ids
            if any(
                ratio_by_resource[resource_id][t] < 1.0
                and math.isclose(
                    ratio_by_resource[resource_id][t],
                    team_ratios[t],
                    rel_tol=_BINDING_RATIO_REL_TOL,
                    abs_tol=_BINDING_RATIO_ABS_TOL,
                )
                and requests_by_team[plan.team_id][t] > 0.0
                for t in range(horizon)
            )
        )
        connection = plan.connections[0]
        request = requests_by_team[plan.team_id]
        site_result = SiteAllocationResult(
            connection_id=connection.connection_id,
            bus_id=connection.bus_id,
            allocated_capacity_mw=allocated_capacity,
            resource_ratio_by_time=team_ratios,
            binding_resources=binding_resources,
            curtailed_mw_by_time=tuple(
                request[t] * (1.0 - team_ratios[t]) for t in range(horizon)
            ),
        )
        results[plan.team_id] = AllocationResult(
            team_id=plan.team_id,
            allocated_capacity_mw=allocated_capacity,
            resource_ratio_by_time=team_ratios,
            binding_resources=binding_resources,
            site_results=(site_result,),
            binding_site_ids=(
                (connection.connection_id,) if binding_resources else ()
            ),
            curtailed_site_ids=(
                (connection.connection_id,)
                if any(amount > 0.0 for amount in site_result.curtailed_mw_by_time)
                else ()
            ),
        )
    return results
