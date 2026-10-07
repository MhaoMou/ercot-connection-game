"""Dependency-free DC economic-dispatch benchmark solver.

This module is intentionally a small validation solver. It enumerates LP
vertices and is suitable for tiny benchmark networks only; it is not the
solver for the full 2,000-bus production evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math


_TOL = 1e-7


@dataclass(frozen=True)
class BusSpec:
    bus_id: str
    demand_mw: float
    reference: bool = False


@dataclass(frozen=True)
class GeneratorSpec:
    generator_id: str
    bus_id: str
    p_min_mw: float
    p_max_mw: float
    marginal_cost_per_mwh: float


@dataclass(frozen=True)
class BranchSpec:
    branch_id: str
    from_bus_id: str
    to_bus_id: str
    susceptance_pu: float
    thermal_limit_mw: float


@dataclass(frozen=True)
class DispatchResult:
    status: str
    objective_cost: float
    generation_mw: dict[str, float]
    angle_by_bus: dict[str, float]
    flow_mw_by_branch: dict[str, float]


class DispatchInfeasible(ValueError):
    """Raised when no feasible dispatch exists under the selected rules."""


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve a square linear system with deterministic partial pivoting."""
    n = len(rhs)
    augmented = [list(row) + [rhs[index]] for index, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= _TOL:
            return None
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        augmented[column] = [value / pivot_value for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) <= _TOL:
                continue
            augmented[row] = [
                current - factor * pivot_value
                for current, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(n)]


def _validate_inputs(
    buses: tuple[BusSpec, ...],
    generators: tuple[GeneratorSpec, ...],
    branches: tuple[BranchSpec, ...],
) -> tuple[dict[str, BusSpec], str]:
    bus_by_id = {bus.bus_id: bus for bus in buses}
    if len(bus_by_id) != len(buses) or not buses:
        raise ValueError("bus IDs must be unique and non-empty")
    references = [bus.bus_id for bus in buses if bus.reference]
    if len(references) > 1:
        raise ValueError("at most one reference bus is allowed")
    reference = references[0] if references else buses[0].bus_id
    for bus in buses:
        if not math.isfinite(bus.demand_mw) or bus.demand_mw < 0:
            raise ValueError(f"demand must be finite and non-negative: {bus.bus_id}")
    generator_ids = set()
    for generator in generators:
        if generator.generator_id in generator_ids:
            raise ValueError(f"duplicate generator ID: {generator.generator_id}")
        generator_ids.add(generator.generator_id)
        if generator.bus_id not in bus_by_id:
            raise ValueError(f"unknown generator bus_id: {generator.bus_id}")
        if generator.p_min_mw < 0 or generator.p_max_mw < generator.p_min_mw:
            raise ValueError(f"invalid generator limits: {generator.generator_id}")
        if not all(math.isfinite(value) for value in (generator.p_min_mw, generator.p_max_mw, generator.marginal_cost_per_mwh)):
            raise ValueError(f"non-finite generator data: {generator.generator_id}")
    branch_ids = set()
    for branch in branches:
        if branch.branch_id in branch_ids:
            raise ValueError(f"duplicate branch ID: {branch.branch_id}")
        branch_ids.add(branch.branch_id)
        for label, bus_id in (("from_bus_id", branch.from_bus_id), ("to_bus_id", branch.to_bus_id)):
            if bus_id not in bus_by_id:
                raise ValueError(f"unknown {label}: {bus_id}")
        if branch.susceptance_pu == 0 or branch.thermal_limit_mw < 0:
            raise ValueError(f"invalid branch parameters: {branch.branch_id}")
    return bus_by_id, reference


def solve_dc_dispatch(
    buses: tuple[BusSpec, ...],
    generators: tuple[GeneratorSpec, ...],
    branches: tuple[BranchSpec, ...],
) -> DispatchResult:
    """Solve a small fixed-load linear DC dispatch problem.

    Branch flow is ``susceptance * (theta_from - theta_to)``; angles
    are dimensionless benchmark variables and the reference angle is fixed at
    zero. Insufficient supply or network capacity raises
    ``DispatchInfeasible``; no load-shedding variables are introduced.
    """
    buses = tuple(buses)
    generators = tuple(generators)
    branches = tuple(branches)
    bus_by_id, reference = _validate_inputs(buses, generators, branches)
    bus_ids = [bus.bus_id for bus in buses]
    non_reference = [bus_id for bus_id in bus_ids if bus_id != reference]
    generator_index = {item.generator_id: index for index, item in enumerate(generators)}
    angle_offset = len(generators)
    variable_count = angle_offset + len(non_reference)
    angle_index = {bus_id: angle_offset + index for index, bus_id in enumerate(non_reference)}

    def angle_coefficient(bus_id: str, row: list[float], coefficient: float) -> None:
        if bus_id != reference:
            row[angle_index[bus_id]] += coefficient

    equalities: list[list[float]] = []
    equality_rhs: list[float] = []
    for bus in buses:
        row = [0.0] * variable_count
        for generator in generators:
            if generator.bus_id == bus.bus_id:
                row[generator_index[generator.generator_id]] = 1.0
        for branch in branches:
            if branch.from_bus_id == bus.bus_id:
                angle_coefficient(branch.from_bus_id, row, -branch.susceptance_pu)
                angle_coefficient(branch.to_bus_id, row, branch.susceptance_pu)
            elif branch.to_bus_id == bus.bus_id:
                angle_coefficient(branch.to_bus_id, row, -branch.susceptance_pu)
                angle_coefficient(branch.from_bus_id, row, branch.susceptance_pu)
        equalities.append(row)
        equality_rhs.append(bus.demand_mw)

    inequalities: list[tuple[list[float], float, str]] = []
    for index, generator in enumerate(generators):
        lower = [0.0] * variable_count
        lower[index] = -1.0
        inequalities.append((lower, -generator.p_min_mw, f"{generator.generator_id}:p_min"))
        upper = [0.0] * variable_count
        upper[index] = 1.0
        inequalities.append((upper, generator.p_max_mw, f"{generator.generator_id}:p_max"))
    for branch in branches:
        flow = [0.0] * variable_count
        angle_coefficient(branch.from_bus_id, flow, branch.susceptance_pu)
        angle_coefficient(branch.to_bus_id, flow, -branch.susceptance_pu)
        inequalities.append((flow, branch.thermal_limit_mw, f"{branch.branch_id}:flow_max"))
        inequalities.append(([-value for value in flow], branch.thermal_limit_mw, f"{branch.branch_id}:flow_min"))

    active_count = variable_count - len(equalities)
    if active_count < 0:
        raise ValueError("benchmark has more equality constraints than variables")
    best: tuple[float, tuple[float, ...]] | None = None
    objective = [generator.marginal_cost_per_mwh for generator in generators]
    objective.extend([0.0] * len(non_reference))
    for active_indices in combinations(range(len(inequalities)), active_count):
        matrix = list(equalities) + [inequalities[index][0] for index in active_indices]
        rhs = list(equality_rhs) + [inequalities[index][1] for index in active_indices]
        solution = _solve_linear_system(matrix, rhs)
        if solution is None:
            continue
        if any(abs(sum(row[i] * solution[i] for i in range(variable_count)) - target) > 1e-5 for row, target in zip(equalities, equality_rhs)):
            continue
        if any(sum(row[i] * solution[i] for i in range(variable_count)) > bound + 1e-5 for row, bound, _ in inequalities):
            continue
        cost = sum(coefficient * value for coefficient, value in zip(objective, solution))
        candidate = (cost, tuple(solution))
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise DispatchInfeasible("no feasible dispatch")

    cost, solution = best
    generation = {generator.generator_id: round(solution[index], 10) for index, generator in enumerate(generators)}
    angles = {reference: 0.0}
    angles.update({bus_id: round(solution[index], 10) for bus_id, index in angle_index.items()})
    flows = {
        branch.branch_id: round(branch.susceptance_pu * (angles[branch.from_bus_id] - angles[branch.to_bus_id]), 10)
        for branch in branches
    }
    return DispatchResult("optimal", round(cost, 10), generation, angles, flows)
