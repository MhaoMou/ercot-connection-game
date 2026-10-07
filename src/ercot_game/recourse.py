"""Deterministic bounded flexible-curtailment recourse."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping, Sequence

from .models import GeneratorPlan, _freeze_result


def _safe_fsum(values: Sequence[float], label: str) -> float:
    try:
        total = math.fsum(values)
    except OverflowError:
        raise ValueError(f"{label} must be finite") from None
    if not math.isfinite(total):
        raise ValueError(f"{label} must be finite")
    return total


def _safe_energy_total(values: Sequence[float], step: float, label: str) -> float:
    total = _safe_fsum(values, label)
    result = total * step
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _validated_site_ids(*mappings: Mapping[object, object]) -> tuple[str, ...]:
    site_ids = tuple(
        site_id
        for mapping in mappings
        for site_id in mapping
    )
    if any(not isinstance(site_id, str) for site_id in site_ids):
        raise ValueError("site IDs must be strings")
    return tuple(sorted(set(site_ids)))


@dataclass(frozen=True)
class SiteRecourseResult:
    """Recourse vectors for one canonical connection site."""

    connection_id: str
    served_mw: tuple[float, ...]
    curtailed_mw: tuple[float, ...]
    residual_unserved_mw: tuple[float, ...]
    intervention_times: tuple[int, ...]
    total_curtailed_mwh: float
    total_unserved_mwh: float


@dataclass(frozen=True)
class GeneratorDispatchResult:
    """Deterministic dispatch vectors keyed by generator and site."""

    dispatch_mw_by_generator: dict[str, tuple[float, ...]]
    dispatch_mw_by_site: dict[str, tuple[float, ...]]
    total_dispatch_mw: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dispatch_mw_by_generator", _freeze_result(self.dispatch_mw_by_generator)
        )
        object.__setattr__(
            self, "dispatch_mw_by_site", _freeze_result(self.dispatch_mw_by_site)
        )
        object.__setattr__(self, "total_dispatch_mw", tuple(self.total_dispatch_mw))


@dataclass(frozen=True)
class RecourseResult:
    feasible: bool
    served_mw: tuple[float, ...]
    curtailed_mw: tuple[float, ...]
    residual_unserved_mw: tuple[float, ...]
    intervention_times: tuple[int, ...]
    total_curtailed_mwh: float
    total_unserved_mwh: float
    site_results: tuple[SiteRecourseResult, ...] = ()


def dispatch_generators(
    generators: Sequence[GeneratorPlan],
    requested_load_by_site: Mapping[str, Sequence[float]],
    network_available_by_site: Mapping[str, Sequence[float]],
) -> GeneratorDispatchResult:
    """Dispatch site-attached generators by cost, then generator ID.

    A generator can only serve its own connection's shortfall.  Within each
    period, dispatch is capped by generator capacity, remaining site demand,
    and the shortfall left after network capacity.
    """
    requested_site_ids = _validated_site_ids(requested_load_by_site)
    available_site_ids = _validated_site_ids(network_available_by_site)
    if requested_site_ids != available_site_ids:
        raise ValueError("requested and available site IDs must match")
    site_ids = requested_site_ids
    horizon = len(next(iter(requested_load_by_site.values()), ()))
    requested: dict[str, tuple[float, ...]] = {}
    available: dict[str, tuple[float, ...]] = {}
    for site_id in site_ids:
        requested[site_id] = tuple(requested_load_by_site[site_id])
        available[site_id] = tuple(network_available_by_site[site_id])
        if len(requested[site_id]) != len(available[site_id]):
            raise ValueError(f"site {site_id} requested and available lengths must match")
        _validate_series(f"requested_load_by_site[{site_id}]", requested[site_id])
        _validate_series(f"network_available_by_site[{site_id}]", available[site_id])
        if len(requested[site_id]) != horizon:
            raise ValueError("site time series must have equal lengths")

    for generator in generators:
        if not isinstance(generator.generator_id, str):
            raise ValueError("generator_id must be a string")

    dispatch: dict[str, list[float]] = {
        generator.generator_id: [0.0] * horizon
        for generator in generators
    }
    if len(dispatch) != len(generators):
        raise ValueError("generator IDs must be unique")
    for generator in generators:
        if (
            isinstance(generator.capacity_mw, bool)
            or not math.isfinite(generator.capacity_mw)
            or generator.capacity_mw < 0.0
        ):
            raise ValueError(
                f"generator {generator.generator_id} capacity_mw must be finite and non-negative"
            )
        if (
            isinstance(generator.marginal_cost_per_mwh, bool)
            or not math.isfinite(generator.marginal_cost_per_mwh)
            or generator.marginal_cost_per_mwh < 0.0
        ):
            raise ValueError(
                f"generator {generator.generator_id} marginal_cost_per_mwh must be finite and non-negative"
            )
        if generator.connection_id not in requested:
            raise ValueError(
                f"generator {generator.generator_id} references unknown connection_id: "
                f"{generator.connection_id}"
            )

    remaining = {
        site_id: [
            max(0.0, requested[site_id][t] - available[site_id][t])
            for t in range(horizon)
        ]
        for site_id in site_ids
    }
    for generator in sorted(
        generators,
        key=lambda item: (item.marginal_cost_per_mwh, str(item.generator_id)),
    ):
        for time_index in range(horizon):
            amount = min(generator.capacity_mw, remaining[generator.connection_id][time_index])
            dispatch[generator.generator_id][time_index] = amount
            remaining[generator.connection_id][time_index] -= amount

    dispatch_by_generator = {
        generator_id: tuple(dispatch[generator_id])
        for generator_id in sorted(dispatch)
    }
    dispatch_by_site = {
        site_id: tuple(
            _safe_fsum(
                tuple(
                    dispatch[generator.generator_id][time_index]
                    for generator in generators
                    if generator.connection_id == site_id
                ),
                f"dispatch for site {site_id} at time {time_index}",
            )
            for time_index in range(horizon)
        )
        for site_id in site_ids
    }
    total_dispatch = tuple(
        _safe_fsum(
            tuple(
                dispatch_by_generator[generator_id][time_index]
                for generator_id in dispatch_by_generator
            ),
            f"total generator dispatch at time {time_index}",
        )
        for time_index in range(horizon)
    )
    return GeneratorDispatchResult(
        dispatch_mw_by_generator=dispatch_by_generator,
        dispatch_mw_by_site=dispatch_by_site,
        total_dispatch_mw=total_dispatch,
    )


def repair_sites_with_curtailment(
    requested_load_by_site: Mapping[str, Sequence[float]],
    available_capacity_by_site: Mapping[str, Sequence[float]],
    allocated_capacity_mw: float,
    k: int,
    mu: float,
    time_step_hours: float,
) -> RecourseResult:
    """Apply one team recourse budget to deterministic site shortfalls."""
    requested_site_ids = _validated_site_ids(requested_load_by_site)
    available_site_ids = _validated_site_ids(available_capacity_by_site)
    if requested_site_ids != available_site_ids:
        raise ValueError("requested and available site IDs must match")
    site_ids = requested_site_ids
    if not site_ids:
        raise ValueError("site inputs must not be empty")
    horizon = len(next(iter(requested_load_by_site.values())))
    requested = {site_id: tuple(requested_load_by_site[site_id]) for site_id in site_ids}
    available = {site_id: tuple(available_capacity_by_site[site_id]) for site_id in site_ids}
    for site_id in site_ids:
        if len(requested[site_id]) != len(available[site_id]):
            raise ValueError("requested and available site lengths must match")
        _validate_series(f"requested_load_by_site[{site_id}]", requested[site_id])
        _validate_series(f"available_capacity_by_site[{site_id}]", available[site_id])
    for name, value in (("allocated_capacity_mw", allocated_capacity_mw), ("time_step_hours", time_step_hours)):
        if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and non-negative")
    if not isinstance(k, int) or isinstance(k, bool) or k < 0:
        raise ValueError("k must be an integer greater than or equal to zero")
    if isinstance(mu, bool) or not math.isfinite(mu) or not 0.0 <= mu <= 1.0:
        raise ValueError("mu must be between zero and one")

    overload_by_site = {
        site_id: tuple(
            max(0.0, requested[site_id][t] - available[site_id][t])
            for t in range(horizon)
        )
        for site_id in site_ids
    }
    total_overload = tuple(
        _safe_fsum(
            tuple(overload_by_site[site_id][t] for site_id in site_ids),
            f"aggregate overload at time {t}",
        )
        for t in range(horizon)
    )
    selected_times = sorted(
        (t for t, overload in enumerate(total_overload) if overload > 0.0),
        key=lambda t: (-total_overload[t], t),
    )[:k]
    curtailment_limit = mu * allocated_capacity_mw
    curtailed_by_site = {site_id: [0.0] * horizon for site_id in site_ids}
    for time_index in selected_times:
        remaining_curtailment = min(total_overload[time_index], curtailment_limit)
        for site_id in site_ids:
            amount = min(remaining_curtailment, overload_by_site[site_id][time_index])
            curtailed_by_site[site_id][time_index] = amount
            remaining_curtailment -= amount

    site_results: list[SiteRecourseResult] = []
    for site_id in site_ids:
        curtailed = tuple(curtailed_by_site[site_id])
        residual = tuple(
            overload_by_site[site_id][t] - curtailed[t] for t in range(horizon)
        )
        served = tuple(
            requested[site_id][t] - curtailed[t] - residual[t]
            for t in range(horizon)
        )
        site_results.append(
            SiteRecourseResult(
                connection_id=site_id,
                served_mw=served,
                curtailed_mw=curtailed,
                residual_unserved_mw=residual,
                intervention_times=tuple(t for t, amount in enumerate(curtailed) if amount > 0.0),
                total_curtailed_mwh=_safe_energy_total(
                    curtailed, time_step_hours, f"site {site_id} curtailed energy"
                ),
                total_unserved_mwh=_safe_energy_total(
                    residual, time_step_hours, f"site {site_id} unserved energy"
                ),
            )
        )
    served = tuple(
        _safe_fsum(tuple(site.served_mw[t] for site in site_results), f"aggregate served load at time {t}")
        for t in range(horizon)
    )
    curtailed = tuple(
        _safe_fsum(tuple(site.curtailed_mw[t] for site in site_results), f"aggregate curtailed load at time {t}")
        for t in range(horizon)
    )
    residual = tuple(
        _safe_fsum(tuple(site.residual_unserved_mw[t] for site in site_results), f"aggregate unserved load at time {t}")
        for t in range(horizon)
    )
    return RecourseResult(
        feasible=not any(residual),
        served_mw=served,
        curtailed_mw=curtailed,
        residual_unserved_mw=residual,
        intervention_times=tuple(t for t, amount in enumerate(curtailed) if amount > 0.0),
        total_curtailed_mwh=_safe_energy_total(
            curtailed, time_step_hours, "aggregate curtailed energy"
        ),
        total_unserved_mwh=_safe_energy_total(
            residual, time_step_hours, "aggregate unserved energy"
        ),
        site_results=tuple(site_results),
    )


def _validate_series(name: str, values: Sequence[float]) -> None:
    for time_index, value in enumerate(values):
        if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name}[{time_index}] must be finite and non-negative")


def repair_with_curtailment(
    requested_load_mw: Sequence[float],
    available_capacity_mw: Sequence[float],
    allocated_capacity_mw: float,
    k: int,
    mu: float,
    time_step_hours: float,
) -> RecourseResult:
    """Repair load overloads with at most ``k`` bounded interventions.

    Overloaded time slots are considered in descending overload order, with
    time index as the deterministic tie-breaker.  Each selected slot can
    curtail at most ``mu * allocated_capacity_mw`` MW.
    """
    if len(requested_load_mw) != len(available_capacity_mw):
        raise ValueError("requested load and available capacity must have equal lengths")
    _validate_series("requested_load_mw", requested_load_mw)
    _validate_series("available_capacity_mw", available_capacity_mw)
    for name, value in (
        ("allocated_capacity_mw", allocated_capacity_mw),
        ("time_step_hours", time_step_hours),
    ):
        if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and non-negative")
    if not isinstance(k, int) or isinstance(k, bool) or k < 0:
        raise ValueError("k must be an integer greater than or equal to zero")
    if isinstance(mu, bool) or not math.isfinite(mu) or not 0.0 <= mu <= 1.0:
        raise ValueError("mu must be between zero and one")

    overloads = tuple(
        max(0.0, requested - available)
        for requested, available in zip(requested_load_mw, available_capacity_mw)
    )
    positive_overloads = tuple(
        time_index
        for time_index, overload in enumerate(overloads)
        if overload > 0.0
    )
    selected_times = sorted(
        positive_overloads,
        key=lambda time_index: (-overloads[time_index], time_index),
    )[:k]

    curtailed = [0.0] * len(requested_load_mw)
    curtailment_limit = mu * allocated_capacity_mw
    intervention_times: list[int] = []
    for time_index in selected_times:
        amount = min(overloads[time_index], curtailment_limit)
        if amount > 0.0:
            curtailed[time_index] = amount
            intervention_times.append(time_index)

    residual_unserved = tuple(
        max(0.0, overload - curtailed[time_index])
        for time_index, overload in enumerate(overloads)
    )
    curtailed_tuple = tuple(curtailed)
    served = tuple(
        requested_load_mw[time_index]
        - curtailed_tuple[time_index]
        - residual_unserved[time_index]
        for time_index in range(len(requested_load_mw))
    )

    try:
        total_curtailed_mwh = math.fsum(curtailed_tuple) * time_step_hours
        total_unserved_mwh = math.fsum(residual_unserved) * time_step_hours
    except OverflowError:
        raise ValueError("energy totals must be finite") from None
    if not math.isfinite(total_curtailed_mwh) or not math.isfinite(total_unserved_mwh):
        raise ValueError("energy totals must be finite")

    return RecourseResult(
        feasible=not any(residual_unserved),
        served_mw=served,
        curtailed_mw=curtailed_tuple,
        residual_unserved_mw=residual_unserved,
        intervention_times=tuple(intervention_times),
        total_curtailed_mwh=total_curtailed_mwh,
        total_unserved_mwh=total_unserved_mwh,
    )
