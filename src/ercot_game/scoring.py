"""Transparent deterministic score decomposition for one team plan."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping, Sequence

from .models import EvaluationConfig, Scenario, TeamPlan


_BALANCE_REL_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ScoreBreakdown:
    it_value: float
    energy_cost: float
    generator_cost: float
    flexibility_fee: float
    curtailment_cost: float
    unserved_penalty: float
    total: float


def _validate_series(name: str, values: Sequence[float], horizon: int) -> None:
    if len(values) != horizon:
        raise ValueError(f"{name} length must match scenario time horizon ({horizon})")
    for time_index, value in enumerate(values):
        if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name}[{time_index}] must be finite and non-negative")


def _validate_coefficient(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} coefficient must be finite and non-negative")


def _weighted_total(values: Sequence[float], coefficients: Sequence[float], step: float) -> float:
    try:
        return math.fsum(value * coefficient for value, coefficient in zip(values, coefficients)) * step
    except OverflowError:
        raise ValueError("score components must be finite") from None


def _mwh_total(values: Sequence[float], step: float) -> float:
    try:
        return math.fsum(values) * step
    except OverflowError:
        raise ValueError("score components must be finite") from None


def calculate_score(
    scenario: Scenario,
    config: EvaluationConfig,
    plan: TeamPlan,
    served_load_mw: tuple[float, ...],
    generator_dispatch_mw: tuple[float, ...],
    curtailed_mw: tuple[float, ...],
    unserved_mw: tuple[float, ...],
    *,
    requested_load_mw: Sequence[float] | None = None,
    generator_dispatch_by_generator: Mapping[str, Sequence[float]] | None = None,
) -> ScoreBreakdown:
    """Calculate a reproducible score and return every additive component.

    Requested load is the plan's capacity multiplied by its profile.  Any
    portion of served load not supplied by the generator is supplied by the
    grid.  Load-balance equality uses a scale-aware relative tolerance of
    ``1e-9`` with zero absolute tolerance.  The emergency-energy coefficient
    is validated as part of the shared configuration, but standalone scoring
    has no emergency-procurement input; it is reserved for the evaluator
    layer and does not affect this breakdown.
    """
    horizon = len(scenario.energy_price_per_mwh)
    if len(scenario.it_value_per_mwh) != horizon:
        raise ValueError("it_value_per_mwh length must match scenario time horizon")
    if (
        isinstance(scenario.time_step_hours, bool)
        or not math.isfinite(scenario.time_step_hours)
        or scenario.time_step_hours <= 0.0
    ):
        raise ValueError("time_step_hours must be finite and greater than zero")
    for time_index, value in enumerate(scenario.energy_price_per_mwh):
        _validate_coefficient(f"energy_price_per_mwh[{time_index}]", value)
    for time_index, value in enumerate(scenario.it_value_per_mwh):
        _validate_coefficient(f"it_value_per_mwh[{time_index}]", value)
    if requested_load_mw is None:
        if isinstance(plan.capacity_mw, bool) or not math.isfinite(plan.capacity_mw) or plan.capacity_mw < 0.0:
            raise ValueError("plan capacity_mw must be finite and non-negative")
        if len(plan.profile) != horizon:
            raise ValueError(f"plan profile length must match scenario time horizon ({horizon})")
        if any(isinstance(value, bool) or not math.isfinite(value) or value < 0.0 for value in plan.profile):
            raise ValueError("plan profile values must be finite and non-negative")
        requested_load_mw = tuple(plan.capacity_mw * profile for profile in plan.profile)
    else:
        _validate_series("requested_load_mw", requested_load_mw, horizon)
    _validate_coefficient("plan.flexibility_fee_per_mwh", plan.flexibility_fee_per_mwh)
    _validate_coefficient("curtailment_cost_per_mwh", config.curtailment_cost_per_mwh)
    _validate_coefficient("unserved_penalty_per_mwh", config.unserved_penalty_per_mwh)
    _validate_coefficient("emergency_energy_cost_per_mwh", config.emergency_energy_cost_per_mwh)

    _validate_series("served_load_mw", served_load_mw, horizon)
    _validate_series("generator_dispatch_mw", generator_dispatch_mw, horizon)
    _validate_series("curtailed_mw", curtailed_mw, horizon)
    _validate_series("unserved_mw", unserved_mw, horizon)

    if any(not math.isfinite(value) for value in requested_load_mw):
        raise ValueError("requested load must be finite")

    for generator in plan.generators:
        if not isinstance(generator.generator_id, str):
            raise ValueError("generator_id must be a string")
        if isinstance(generator.capacity_mw, bool) or not math.isfinite(generator.capacity_mw) or generator.capacity_mw < 0.0:
            raise ValueError("generator capacity_mw must be finite and non-negative")
        _validate_coefficient(
            "generator marginal_cost_per_mwh", generator.marginal_cost_per_mwh
        )

    generator_cost_series: tuple[float, ...]
    if generator_dispatch_by_generator is not None:
        if any(not isinstance(generator_id, str) for generator_id in generator_dispatch_by_generator):
            raise ValueError("generator dispatch IDs must be strings")
        generators_by_id = {generator.generator_id: generator for generator in plan.generators}
        if len(generators_by_id) != len(plan.generators):
            raise ValueError("generator IDs must be unique")
        if set(generator_dispatch_by_generator) != set(generators_by_id):
            raise ValueError("generator dispatch IDs must match plan generators")
        dispatch_total = []
        generator_cost_values = []
        for time_index in range(horizon):
            total_dispatch = 0.0
            total_cost = 0.0
            for generator_id in sorted(generator_dispatch_by_generator):
                generator = generators_by_id[generator_id]
                dispatch_series = generator_dispatch_by_generator[generator_id]
                if len(dispatch_series) != horizon:
                    raise ValueError(
                        f"generator_dispatch_by_generator[{generator_id}] length must match "
                        f"scenario time horizon ({horizon})"
                    )
                dispatch = dispatch_series[time_index]
                if not math.isfinite(dispatch) or dispatch < 0.0:
                    raise ValueError(
                        f"generator_dispatch_by_generator[{generator_id}][{time_index}] "
                        "must be finite and non-negative"
                    )
                if dispatch > generator.capacity_mw:
                    raise ValueError(
                        f"generator {generator_id} dispatch exceeds generator capacity"
                    )
                total_dispatch += dispatch
                total_cost += dispatch * generator.marginal_cost_per_mwh
            dispatch_total.append(total_dispatch)
            generator_cost_values.append(total_cost)
        if tuple(dispatch_total) != tuple(generator_dispatch_mw):
            if not all(
                math.isclose(left, right, rel_tol=_BALANCE_REL_TOLERANCE, abs_tol=0.0)
                for left, right in zip(dispatch_total, generator_dispatch_mw)
            ):
                raise ValueError("generator dispatch series must equal per-generator dispatch total")
        generator_cost_series = tuple(generator_cost_values)
    elif plan.generator is None:
        if any(dispatch != 0.0 for dispatch in generator_dispatch_mw):
            time_index = next(
                index for index, dispatch in enumerate(generator_dispatch_mw) if dispatch != 0.0
            )
            raise ValueError(
                f"generator_dispatch_mw[{time_index}] must be zero when plan has no generator"
            )
    else:
        if (
            isinstance(plan.generator.capacity_mw, bool)
            or not math.isfinite(plan.generator.capacity_mw)
            or plan.generator.capacity_mw < 0.0
        ):
            raise ValueError("generator capacity_mw must be finite and non-negative")
        _validate_coefficient(
            "generator marginal_cost_per_mwh", plan.generator.marginal_cost_per_mwh
        )
        for time_index, dispatch in enumerate(generator_dispatch_mw):
            if dispatch > plan.generator.capacity_mw:
                raise ValueError(
                    f"generator_dispatch_mw[{time_index}] exceeds generator capacity"
                )

    for time_index, (served, dispatch, curtailed, unserved, requested) in enumerate(
        zip(
            served_load_mw,
            generator_dispatch_mw,
            curtailed_mw,
            unserved_mw,
            requested_load_mw,
        )
    ):
        if dispatch > served:
            raise ValueError(
                f"generator_dispatch_mw[{time_index}] cannot exceed served load"
            )
        accounted_load = served + curtailed + unserved
        if not math.isfinite(accounted_load) or not math.isclose(
            accounted_load,
            requested,
            rel_tol=_BALANCE_REL_TOLERANCE,
            abs_tol=0.0,
        ):
            raise ValueError(
                f"served, curtailed, and unserved load at time {time_index} must equal requested load"
            )

    step = scenario.time_step_hours
    it_value = _weighted_total(served_load_mw, scenario.it_value_per_mwh, step)
    energy_cost = _weighted_total(
        tuple(served - dispatch for served, dispatch in zip(served_load_mw, generator_dispatch_mw)),
        scenario.energy_price_per_mwh,
        step,
    )
    if generator_dispatch_by_generator is None:
        generator_cost_series = tuple(
            dispatch
            * (plan.generator.marginal_cost_per_mwh if plan.generator is not None else 0.0)
            for dispatch in generator_dispatch_mw
        )
    try:
        generator_cost = math.fsum(generator_cost_series) * step
    except OverflowError:
        raise ValueError("score components must be finite") from None
    served_mwh = _mwh_total(served_load_mw, step)
    curtailed_mwh = _mwh_total(curtailed_mw, step)
    unserved_mwh = _mwh_total(unserved_mw, step)
    flexibility_fee = plan.flexibility_fee_per_mwh * served_mwh
    curtailment_cost = config.curtailment_cost_per_mwh * curtailed_mwh
    unserved_penalty = config.unserved_penalty_per_mwh * unserved_mwh
    components = (
        it_value,
        energy_cost,
        generator_cost,
        flexibility_fee,
        curtailment_cost,
        unserved_penalty,
    )
    if not all(math.isfinite(component) for component in components):
        raise ValueError("score components must be finite")
    try:
        total = it_value - math.fsum(components[1:])
    except OverflowError:
        raise ValueError("score components must be finite") from None
    if not math.isfinite(total):
        raise ValueError("total score must be finite")
    return ScoreBreakdown(
        it_value=it_value,
        energy_cost=energy_cost,
        generator_cost=generator_cost,
        flexibility_fee=flexibility_fee,
        curtailment_cost=curtailment_cost,
        unserved_penalty=unserved_penalty,
        total=total,
    )
