"""Deterministic end-to-end evaluation for one offline competition week."""

from __future__ import annotations

from dataclasses import asdict
import math
from collections.abc import Iterable, Mapping

from .allocation import AllocationResult, allocate_shared_capacity
from .io import canonical_hash, plan_to_dict, scenario_to_dict
from .models import EvaluationConfig, EvaluationResult, Scenario, TeamPlan
from .recourse import (
    RecourseResult,
    dispatch_generators,
    repair_sites_with_curtailment,
    repair_with_curtailment,
)
from .scoring import ScoreBreakdown, calculate_score
from .validate import validate_plan, validate_scenario


class EvaluationInputError(ValueError):
    """Raised when an evaluation input is invalid.

    ``errors`` is an ordered, duplicate-free tuple so callers can display the
    same diagnostics regardless of submission order.
    """

    def __init__(self, errors: Iterable[str]):
        stable_errors = tuple(sorted(dict.fromkeys(str(error) for error in errors)))
        if not stable_errors:
            stable_errors = ("evaluation input is invalid",)
        self.errors = stable_errors
        super().__init__("; ".join(stable_errors))


DEFAULT_EVALUATION_CONFIG = EvaluationConfig(
    curtailment_cost_per_mwh=5.0,
    unserved_penalty_per_mwh=500.0,
    emergency_energy_cost_per_mwh=80.0,
)


def _evaluation_config_from_mapping(raw_config: Mapping[str, object]) -> EvaluationConfig:
    fields = (
        "curtailment_cost_per_mwh",
        "unserved_penalty_per_mwh",
        "emergency_energy_cost_per_mwh",
    )
    errors = [
        f"configuration missing field: {field}"
        for field in fields
        if field not in raw_config
    ]
    if errors:
        raise EvaluationInputError(errors)
    try:
        return EvaluationConfig(
            curtailment_cost_per_mwh=raw_config["curtailment_cost_per_mwh"],  # type: ignore[arg-type]
            unserved_penalty_per_mwh=raw_config["unserved_penalty_per_mwh"],  # type: ignore[arg-type]
            emergency_energy_cost_per_mwh=raw_config["emergency_energy_cost_per_mwh"],  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationInputError((f"configuration is malformed: {error}",)) from None


def resolve_evaluation_config(
    scenario: Scenario,
    explicit_config: EvaluationConfig | Mapping[str, object] | None = None,
) -> EvaluationConfig:
    """Resolve configuration from explicit input, scenario metadata, or defaults."""
    if explicit_config is not None:
        if isinstance(explicit_config, EvaluationConfig):
            return explicit_config
        if isinstance(explicit_config, Mapping):
            return _evaluation_config_from_mapping(explicit_config)
        raise EvaluationInputError(("configuration must be an object",))
    metadata_config = scenario.metadata.get("evaluation_config")
    if metadata_config is not None:
        if not isinstance(metadata_config, Mapping):
            raise EvaluationInputError(
                ("scenario metadata evaluation_config must be an object",)
            )
        return _evaluation_config_from_mapping(metadata_config)
    return DEFAULT_EVALUATION_CONFIG


def _configuration_to_dict(config: EvaluationConfig) -> dict[str, float]:
    return {
        "curtailment_cost_per_mwh": config.curtailment_cost_per_mwh,
        "unserved_penalty_per_mwh": config.unserved_penalty_per_mwh,
        "emergency_energy_cost_per_mwh": config.emergency_energy_cost_per_mwh,
    }


def _configuration_errors(config: EvaluationConfig) -> list[str]:
    errors: list[str] = []
    fields = (
        "curtailment_cost_per_mwh",
        "unserved_penalty_per_mwh",
        "emergency_energy_cost_per_mwh",
    )
    for field in fields:
        value = getattr(config, field, None)
        try:
            valid = not isinstance(value, bool) and math.isfinite(value) and value >= 0.0
        except TypeError:
            valid = False
        if not valid:
            errors.append(f"{field} must be finite and non-negative")
    return errors


def _team_sort_key(plan: TeamPlan) -> str:
    """Return a total-order key without comparing heterogeneous ID values."""
    return str(plan.team_id)


def _scenario_extra_errors(scenario: Scenario) -> list[str]:
    errors: list[str] = []
    bus_ids = [bus.bus_id for bus in scenario.buses]
    errors.extend(
        f"duplicate bus_id: {bus_id}"
        for bus_id in sorted(
            {str(bus_id) for bus_id in bus_ids if bus_ids.count(bus_id) > 1}
        )
    )
    corridor_ids = [corridor.corridor_id for corridor in scenario.corridors]
    errors.extend(
        f"duplicate corridor_id: {corridor_id}"
        for corridor_id in sorted(
            {
                str(corridor_id)
                for corridor_id in corridor_ids
                if corridor_ids.count(corridor_id) > 1
            }
        )
    )
    for bus in sorted(scenario.buses, key=lambda candidate: str(candidate.bus_id)):
        if not isinstance(bus.bus_id, str):
            errors.append("bus_id must be a string")
        if any(
            isinstance(value, (int, float)) and value < 0.0
            for value in bus.headroom_mw_by_time
        ):
            errors.append(f"bus {bus.bus_id} headroom_mw_by_time values must be non-negative")
    for corridor in sorted(scenario.corridors, key=lambda candidate: str(candidate.corridor_id)):
        if not isinstance(corridor.corridor_id, str):
            errors.append("corridor_id must be a string")
        if any(
            isinstance(value, (int, float)) and value < 0.0
            for value in corridor.capacity_mw_by_time
        ):
            errors.append(
                f"corridor {corridor.corridor_id} capacity_mw_by_time values must be non-negative"
            )
    return errors


def _validate_inputs(
    scenario: Scenario,
    config: EvaluationConfig,
    plans: tuple[TeamPlan, ...],
) -> None:
    try:
        errors = sorted(validate_scenario(scenario))
        errors.extend(sorted(_scenario_extra_errors(scenario)))
    except (AttributeError, TypeError, ValueError):
        errors = ["scenario payload is malformed"]
    errors.extend(_configuration_errors(config))

    team_ids = [plan.team_id for plan in plans]
    errors.extend(
        f"duplicate team_id: {team_id}"
        for team_id in sorted(
            {str(team_id) for team_id in team_ids if team_ids.count(team_id) > 1}
        )
    )
    for plan in sorted(plans, key=_team_sort_key):
        try:
            plan_errors = validate_plan(plan, scenario)
        except (AttributeError, TypeError, ValueError):
            plan_errors = ["plan payload is malformed"]
        if len(plan.connections) == 1 and plan.connections[0].connection_id == "connection-legacy":
            if not isinstance(plan.bus_id, str):
                plan_errors.insert(0, "bus_id must be a string")
            try:
                path_corridors = tuple(plan.path_corridors)
            except TypeError:
                path_corridors = ()
                plan_errors.append("path_corridors must be a sequence")
            for index, corridor_id in enumerate(path_corridors):
                if not isinstance(corridor_id, str):
                    plan_errors.append(f"path_corridors[{index}] must be a string")
        else:
            for connection in plan.connections:
                if not isinstance(connection.bus_id, str):
                    plan_errors.append(
                        f"connection {connection.connection_id}: bus_id must be a string"
                    )
                for index, corridor_id in enumerate(connection.path_corridors):
                    if not isinstance(corridor_id, str):
                        plan_errors.append(
                            f"connection {connection.connection_id}: "
                            f"path_corridors[{index}] must be a string"
                        )
        if not isinstance(plan.team_id, str):
            plan_errors.insert(0, "team_id must be a string")
        errors.extend(f"{plan.team_id}: {error}" for error in plan_errors)
    if errors:
        raise EvaluationInputError(errors)


def _requested_load(plan: TeamPlan) -> tuple[float, ...]:
    return tuple(plan.capacity_mw * profile for profile in plan.profile)


def _site_requested_load(plan: TeamPlan) -> dict[str, tuple[float, ...]]:
    return {
        connection.connection_id: tuple(
            connection.capacity_mw * profile for profile in connection.profile
        )
        for connection in sorted(plan.connections, key=lambda item: str(item.connection_id))
    }


def _site_network_available_capacity(
    scenario: Scenario,
    plan: TeamPlan,
    requested_by_site: dict[str, tuple[float, ...]],
    allocation: AllocationResult,
) -> dict[str, tuple[float, ...]]:
    buses = {bus.bus_id: bus for bus in scenario.buses}
    corridors = {corridor.corridor_id: corridor for corridor in scenario.corridors}
    allocation_by_site = {site.connection_id: site for site in allocation.site_results}
    result: dict[str, tuple[float, ...]] = {}
    for connection in sorted(plan.connections, key=lambda item: str(item.connection_id)):
        site_allocation = allocation_by_site[connection.connection_id]
        resources = (buses[connection.bus_id].headroom_mw_by_time,) + tuple(
            corridors[corridor_id].capacity_mw_by_time
            for corridor_id in sorted(connection.path_corridors)
        )
        result[connection.connection_id] = tuple(
            min(
                requested_by_site[connection.connection_id][time_index]
                * site_allocation.resource_ratio_by_time[time_index],
                *(resource[time_index] for resource in resources),
            )
            for time_index in range(len(requested_by_site[connection.connection_id]))
        )
    return result


def _sum_site_series(
    series_by_site: Mapping[str, tuple[float, ...]], horizon: int
) -> tuple[float, ...]:
    totals: list[float] = []
    for time_index in range(horizon):
        try:
            total = math.fsum(
                series_by_site[site_id][time_index]
                for site_id in sorted(series_by_site)
            )
        except OverflowError:
            raise ValueError(
                f"aggregate site series at time {time_index} must be finite"
            ) from None
        if not math.isfinite(total):
            raise ValueError(f"aggregate site series at time {time_index} must be finite")
        totals.append(total)
    return tuple(totals)


def _network_available_capacity(
    scenario: Scenario,
    plan: TeamPlan,
    requested_load_mw: tuple[float, ...],
    allocation: AllocationResult,
) -> tuple[float, ...]:
    buses = {bus.bus_id: bus for bus in scenario.buses}
    corridors = {corridor.corridor_id: corridor for corridor in scenario.corridors}
    resources = (buses[plan.bus_id].headroom_mw_by_time,) + tuple(
        corridors[corridor_id].capacity_mw_by_time
        for corridor_id in sorted(plan.path_corridors)
    )
    return tuple(
        min(
            requested_load_mw[time_index] * allocation.resource_ratio_by_time[time_index],
            *(resource[time_index] for resource in resources),
        )
        for time_index in range(len(requested_load_mw))
    )


def _generator_dispatch(
    plan: TeamPlan,
    requested_load_mw: tuple[float, ...],
    network_available_capacity_mw: tuple[float, ...],
) -> tuple[float, ...]:
    if plan.generator is None:
        return (0.0,) * len(requested_load_mw)
    return tuple(
        min(
            plan.generator.capacity_mw,
            requested_load_mw[time_index],
            max(0.0, requested_load_mw[time_index] - network_available_capacity_mw[time_index]),
        )
        for time_index in range(len(requested_load_mw))
    )


def _generator_payload(
    plan: TeamPlan, dispatch_mw: tuple[float, ...], time_step_hours: float
) -> dict[str, object]:
    try:
        total_mwh = math.fsum(dispatch_mw) * time_step_hours
    except OverflowError:
        raise EvaluationInputError((f"generator dispatch for team {plan.team_id} must be finite",)) from None
    return {
        "generator_id": plan.generator.generator_id if plan.generator is not None else None,
        "dispatch_mw": dispatch_mw,
        "total_mwh": total_mwh,
    }


def _generator_results_payload(
    plan: TeamPlan,
    dispatch_by_generator: Mapping[str, tuple[float, ...]],
    time_step_hours: float,
) -> tuple[dict[str, object], ...]:
    """Return canonical generator diagnostics in dispatch order."""
    generators_by_id = {generator.generator_id: generator for generator in plan.generators}
    payload: list[dict[str, object]] = []
    for generator in sorted(
        plan.generators,
        key=lambda item: (item.marginal_cost_per_mwh, str(item.generator_id)),
    ):
        dispatch = dispatch_by_generator[generator.generator_id]
        payload.append(
            {
                "generator_id": generator.generator_id,
                "connection_id": generator.connection_id,
                "dispatch_mw": dispatch,
                "total_mwh": math.fsum(dispatch) * time_step_hours,
                "capacity_mw": generator.capacity_mw,
                "marginal_cost_per_mwh": generator.marginal_cost_per_mwh,
            }
        )
    return tuple(payload)


def _recourse_payload(recourse: RecourseResult) -> dict[str, object]:
    return asdict(recourse)


def _score_payload(score: ScoreBreakdown) -> dict[str, object]:
    return asdict(score)


def _canonical_input_hash(
    scenario: Scenario,
    config: EvaluationConfig,
    ordered_plans: tuple[TeamPlan, ...],
) -> str:
    try:
        scenario_payload = scenario_to_dict(scenario)
        scenario_payload["buses"] = sorted(
            scenario_payload["buses"], key=lambda bus: str(bus["bus_id"])
        )
        scenario_payload["corridors"] = sorted(
            scenario_payload["corridors"],
            key=lambda corridor: str(corridor["corridor_id"]),
        )
        canonical_plans = []
        for plan in ordered_plans:
            plan_payload = plan_to_dict(plan)
            plan_payload["connections"] = sorted(
                plan_payload["connections"], key=lambda connection: str(connection["connection_id"])
            )
            for connection in plan_payload["connections"]:
                connection["path_corridors"] = sorted(
                    set(connection["path_corridors"]), key=str
                )
            plan_payload["generators"] = sorted(
                plan_payload["generators"],
                key=lambda generator: (
                    str(generator["connection_id"]),
                    str(generator["generator_id"]),
                ),
            )
            canonical_plans.append(plan_payload)
        return canonical_hash(
            {
                "scenario": scenario_payload,
                "configuration": _configuration_to_dict(config),
                "plans": canonical_plans,
            }
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise EvaluationInputError((f"input cannot be canonically serialized: {error}",)) from None


def _aggregate_diagnostics(
    scenario: Scenario,
    config: EvaluationConfig,
    allocations: dict[str, AllocationResult],
    team_results: tuple[dict[str, object], ...],
) -> dict[str, object]:
    binding_resource_ids = sorted(
        {
            resource_id
            for allocation in allocations.values()
            for resource_id in allocation.binding_resources
        }
    )
    binding_resource_diagnostics = {
        resource_id: {
            "team_ids": tuple(
                sorted(
                    team_id
                    for team_id, allocation in allocations.items()
                    if resource_id in allocation.binding_resources
                )
            )
        }
        for resource_id in binding_resource_ids
    }
    site_binding_diagnostics = tuple(
        {
            "team_id": team_id,
            "connection_id": site.connection_id,
            "bus_id": site.bus_id,
            "binding_resources": site.binding_resources,
        }
        for team_id in sorted(allocations)
        for site in sorted(
            allocations[team_id].site_results,
            key=lambda item: str(item.connection_id),
        )
        if site.binding_resources
    )
    binding_site_ids = tuple(
        {
            "team_id": team_id,
            "connection_id": site.connection_id,
        }
        for team_id in sorted(allocations)
        for site in sorted(
            allocations[team_id].site_results,
            key=lambda item: str(item.connection_id),
        )
        if site.binding_resources
    )
    curtailed_site_ids = tuple(
        {
            "team_id": team_id,
            "connection_id": site.connection_id,
        }
        for team_id in sorted(allocations)
        for site in sorted(
            allocations[team_id].site_results,
            key=lambda item: str(item.connection_id),
        )
        if any(amount > 0.0 for amount in site.curtailed_mw_by_time)
    )
    try:
        total_unserved = math.fsum(
            team["recourse"]["total_unserved_mwh"]  # type: ignore[index]
            for team in team_results
        )
    except OverflowError:
        raise EvaluationInputError(("aggregate unserved energy must be finite",)) from None
    return {
        "evaluator_version": scenario.evaluator_version,
        "configuration": _configuration_to_dict(config),
        "scenario_metadata": scenario_to_dict(scenario).get("metadata", {}),
        "base_load_mw_by_time": scenario.base_load_mw_by_time,
        "binding_resources": tuple(binding_resource_ids),
        "binding_resource_diagnostics": binding_resource_diagnostics,
        "site_binding_diagnostics": site_binding_diagnostics,
        "binding_site_ids": binding_site_ids,
        "curtailed_site_ids": curtailed_site_ids,
        "team_count": len(team_results),
        "total_unserved_mwh": total_unserved,
    }


def evaluate_week(
    scenario: Scenario,
    config: EvaluationConfig | Mapping[str, object] | None,
    plans: tuple[TeamPlan, ...],
) -> EvaluationResult:
    """Evaluate all team plans together using deterministic Phase 1 semantics."""
    config = resolve_evaluation_config(scenario, config)
    _validate_inputs(scenario, config, plans)
    ordered_plans = tuple(sorted(plans, key=_team_sort_key))
    input_hash = _canonical_input_hash(scenario, config, ordered_plans)

    try:
        allocations = allocate_shared_capacity(scenario, ordered_plans)
    except ValueError as error:
        raise EvaluationInputError((str(error),)) from None

    team_results: list[dict[str, object]] = []
    for plan in ordered_plans:
        allocation = allocations[plan.team_id]
        requested_by_site = _site_requested_load(plan)
        network_by_site = _site_network_available_capacity(
            scenario, plan, requested_by_site, allocation
        )
        try:
            dispatch_result = dispatch_generators(
                plan.generators, requested_by_site, network_by_site
            )
            dispatch_by_generator = dispatch_result.dispatch_mw_by_generator
            dispatch_by_site = dispatch_result.dispatch_mw_by_site
            effective_by_site = {
                site_id: tuple(
                    min(
                        requested_by_site[site_id][time_index],
                        network_by_site[site_id][time_index]
                        + dispatch_by_site[site_id][time_index],
                    )
                    for time_index in range(len(requested_by_site[site_id]))
                )
                for site_id in sorted(requested_by_site)
            }
            recourse = repair_sites_with_curtailment(
                requested_by_site,
                effective_by_site,
                allocation.allocated_capacity_mw,
                plan.intervention_budget_k,
                plan.curtailment_depth_mu,
                scenario.time_step_hours,
            )
            requested_load_mw = _sum_site_series(
                requested_by_site, len(scenario.energy_price_per_mwh)
            )
            network_available_capacity_mw = _sum_site_series(
                network_by_site, len(scenario.energy_price_per_mwh)
            )
            effective_available_capacity_mw = _sum_site_series(
                effective_by_site, len(scenario.energy_price_per_mwh)
            )
            dispatch_mw = dispatch_result.total_dispatch_mw
            score = calculate_score(
                scenario,
                config,
                plan,
                recourse.served_mw,
                dispatch_mw,
                recourse.curtailed_mw,
                recourse.residual_unserved_mw,
                requested_load_mw=requested_load_mw,
                generator_dispatch_by_generator=(dispatch_by_generator or None),
            )
        except ValueError as error:
            raise EvaluationInputError((f"team {plan.team_id}: {error}",)) from None
        try:
            site_recourse_by_id = {
                site.connection_id: site for site in recourse.site_results
            }
            site_connection_by_id = {
                connection.connection_id: connection for connection in plan.connections
            }
            connection_results: list[dict[str, object]] = []
            for connection_id in sorted(requested_by_site):
                connection = site_connection_by_id[connection_id]
                site_recourse = site_recourse_by_id[connection_id]
                site_allocation = next(
                    site for site in allocation.site_results
                    if site.connection_id == connection_id
                )
                site_generators = tuple(
                    generator for generator in plan.generators
                    if generator.connection_id == connection_id
                )
                site_dispatch_by_generator = {
                    generator.generator_id: dispatch_by_generator[generator.generator_id]
                    for generator in site_generators
                }
                site_dispatch = dispatch_by_site[connection_id]
                site_plan = TeamPlan(
                    plan.team_id,
                    connections=(connection,),
                    generators=site_generators,
                    intervention_budget_k=plan.intervention_budget_k,
                    curtailment_depth_mu=plan.curtailment_depth_mu,
                    flexibility_fee_per_mwh=plan.flexibility_fee_per_mwh,
                )
                site_score = calculate_score(
                    scenario,
                    config,
                    site_plan,
                    site_recourse.served_mw,
                    site_dispatch,
                    site_recourse.curtailed_mw,
                    site_recourse.residual_unserved_mw,
                    generator_dispatch_by_generator=(site_dispatch_by_generator or None),
                )
                site_balance_error = tuple(
                    requested_by_site[connection_id][time_index]
                    - site_recourse.served_mw[time_index]
                    - site_recourse.curtailed_mw[time_index]
                    - site_recourse.residual_unserved_mw[time_index]
                    for time_index in range(len(requested_by_site[connection_id]))
                )
                connection_results.append(
                    {
                        "connection_id": connection_id,
                        "bus_id": connection.bus_id,
                        "path_corridors": connection.path_corridors,
                        "allocation": {
                            "allocated_capacity_mw": site_allocation.allocated_capacity_mw,
                            "resource_ratio_by_time": site_allocation.resource_ratio_by_time,
                            "binding_resources": site_allocation.binding_resources,
                            "curtailed_mw_by_time": site_allocation.curtailed_mw_by_time,
                        },
                        "recourse": asdict(site_recourse),
                        "generator_dispatch": _generator_results_payload(
                            site_plan, site_dispatch_by_generator, scenario.time_step_hours
                        ),
                        "score_breakdown": _score_payload(site_score),
                        "diagnostics": {
                            "requested_load_mw": requested_by_site[connection_id],
                            "network_available_capacity_mw": network_by_site[connection_id],
                            "effective_available_capacity_mw": effective_by_site[connection_id],
                            "grid_supply_mw": tuple(
                                site_recourse.served_mw[time_index] - site_dispatch[time_index]
                                for time_index in range(len(site_dispatch))
                            ),
                            "balance_error_mw": site_balance_error,
                            "feasible": not any(site_recourse.residual_unserved_mw),
                        },
                    }
                )
        except ValueError as error:
            raise EvaluationInputError((f"team {plan.team_id}: {error}",)) from None

        balance_error_mw = tuple(
            requested_load_mw[time_index]
            - recourse.served_mw[time_index]
            - recourse.curtailed_mw[time_index]
            - recourse.residual_unserved_mw[time_index]
            for time_index in range(len(requested_load_mw))
        )
        if len(plan.generators) <= 1 and len(plan.connections) == 1:
            generator_payload = _generator_payload(
                plan, dispatch_mw, scenario.time_step_hours
            )
        else:
            generator_payload = {
                "generator_id": None,
                "dispatch_mw": dispatch_mw,
                "total_mwh": math.fsum(dispatch_mw) * scenario.time_step_hours,
            }
        site_binding_diagnostics = tuple(
            {
                "connection_id": site.connection_id,
                "bus_id": site.bus_id,
                "binding_resources": site.binding_resources,
            }
            for site in allocation.site_results
            if site.binding_resources
        )
        team_results.append(
            {
                "team_id": plan.team_id,
                "allocation": {
                    "allocated_capacity_mw": allocation.allocated_capacity_mw,
                    "resource_ratio_by_time": allocation.resource_ratio_by_time,
                    "binding_resources": allocation.binding_resources,
                },
                "recourse": _recourse_payload(recourse),
                "generator_dispatch": generator_payload,
                "generator_dispatch_results": _generator_results_payload(
                    plan, dispatch_by_generator, scenario.time_step_hours
                ),
                "connection_results": tuple(connection_results),
                "site_results": tuple(connection_results),
                "score_breakdown": _score_payload(score),
                "diagnostics": {
                    "requested_load_mw": requested_load_mw,
                    "network_available_capacity_mw": network_available_capacity_mw,
                    "effective_available_capacity_mw": effective_available_capacity_mw,
                    "grid_supply_mw": tuple(
                        recourse.served_mw[time_index] - dispatch_mw[time_index]
                        for time_index in range(len(requested_load_mw))
                    ),
                    "balance_error_mw": balance_error_mw,
                    "feasible": recourse.feasible,
                    "site_binding_diagnostics": site_binding_diagnostics,
                    "binding_site_ids": allocation.binding_site_ids,
                    "curtailed_site_ids": allocation.curtailed_site_ids,
                },
            }
        )

    ordered_team_results = tuple(team_results)
    return EvaluationResult(
        scenario_id=scenario.scenario_id,
        input_hash=input_hash,
        team_results=ordered_team_results,
        aggregate_diagnostics=_aggregate_diagnostics(
            scenario, config, allocations, ordered_team_results
        ),
    )
