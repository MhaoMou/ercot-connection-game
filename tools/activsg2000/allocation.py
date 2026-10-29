"""Utilitarian allocation of requested sites on the shared network.

When the submitted plans do not fit the grid together, every site i gets a
fraction ``alpha_i`` in [0, 1].  The fraction scales the site's connection
capacity C, generator capacity G, storage power P and storage energy B.  The
allocation solves

* stage 1: maximize the total served capacity ``sum_i alpha_i C_i`` subject to
  the DCOPF of every period (load ``alpha_i C_i`` served in every period, the
  site's generator up to ``alpha_i G_i`` and its storage within
  ``alpha_i P_i`` and ``alpha_i B_i``, each team's generator and storage
  serving only that team's load at the bus);
* stage 2 (tie-break): among the stage-1 optima, minimize
  ``sum_i C_i (1 - alpha_i)^2``.  The objective is strictly convex in alpha,
  so the allocation is unique and does not depend on the solver's choice
  among optimal vertices.

``alpha`` is the same in every period, so the periods are coupled only
through alpha (and, within a day, through storage).  The problem is solved by
a cutting-plane method: a small master problem over alpha, and one
load-shedding LP per day that measures how far a candidate alpha is from
fitting.  The shed is a convex piecewise-linear function of alpha; its
reduced costs give a cut that removes the candidate.  Each day's LP is built
once and re-solved with new alpha bounds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from pathlib import Path

from .dcopf import (
    DCOPFUnresolved,
    _highs,
    _prepared_period_inputs,
    _run_highs,
    _validate_prepared_demand_schema,
    load_prepared_artifact,
)


@dataclass(frozen=True)
class AllocationSite:
    """One requested site, with its load in each evaluated period."""

    team_id: str
    site_id: str
    bus_id: str
    capacity_mw: float
    load_mw_by_period: tuple[float, ...]
    generator_mw: float = 0.0
    storage_power_mw: float = 0.0
    storage_energy_mwh: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.team_id, self.site_id)


@dataclass(frozen=True)
class AllocationResult:
    """Site fractions and solve diagnostics."""

    alpha_by_site: dict[tuple[str, str], float]
    max_total_capacity_mw: float
    total_capacity_mw: float
    requested_capacity_mw: float
    iterations: int
    cuts: int
    max_shed_mwh: float


# A day fits when its LP sheds at most this much energy (MWh).
SHED_TOLERANCE_MWH = 1e-4
# Stage 2 keeps the total served capacity within this share of stage 1.
TOTAL_RELATIVE_TOLERANCE = 1e-7
MAX_ITERATIONS = 500
# A best total below this (MW) means nothing fits: all fractions are zero.
EMPTY_TOTAL_MW = 1e-3
# In-out separation: test the master's proposal this far from the last
# point known to fit (Ben-Ameur and Neto, 2007).
IN_OUT_STEP = 0.5


class _DayModel:
    """Load-shedding LP of one day with alpha as fixed columns."""

    def __init__(
        self,
        prepared_periods,
        sites: Sequence[AllocationSite],
        period_offsets: Sequence[int],
        *,
        time_step_hours: float,
        base_mva: float,
    ) -> None:
        Highs, HighsModelStatus, _HighsVarType, inf = _highs()
        self.status_type = HighsModelStatus
        highs = Highs()
        highs.setOptionValue("output_flag", False)
        # The first solve starts from scratch: interior point with presolve
        # (and crossover to a basis) is several times faster there.  Later
        # solves only change the alpha bounds and warm-start the simplex.
        highs.setOptionValue("solver", "ipm")
        highs.setOptionValue("presolve", "on")
        highs.setOptionValue("parallel", "off")
        self.highs = highs
        self.solved = False
        angle_scale = 1000.0

        def add(coefficients: dict[int, float], column: int, value: float) -> None:
            coefficients[column] = coefficients.get(column, 0.0) + value

        def row(lower: float, upper: float, coefficients: dict[int, float]) -> None:
            highs.addRow(lower, upper, len(coefficients), list(coefficients), list(coefficients.values()))

        def column(lower: float, upper: float, cost: float = 0.0) -> int:
            highs.addVariable(lb=lower, ub=upper, obj=cost)
            return highs.getNumCol() - 1

        self.alpha_columns = [column(0.0, 0.0) for _ in sites]
        sites_by_bus: dict[str, list[int]] = {}
        for index, site in enumerate(sites):
            sites_by_bus.setdefault(site.bus_id, []).append(index)
        owners: dict[tuple[str, str], list[int]] = {}
        for index, site in enumerate(sites):
            if site.generator_mw > 0.0 or site.storage_power_mw > 0.0:
                owners.setdefault((site.team_id, site.bus_id), [])
        for index, site in enumerate(sites):
            if (site.team_id, site.bus_id) in owners:
                owners[(site.team_id, site.bus_id)].append(index)

        previous_soc: dict[int, int] = {}
        last = len(period_offsets) - 1
        for position, (offset, (buses, generators, branches, fixed)) in enumerate(
            zip(period_offsets, prepared_periods)
        ):
            reference = next((bus.bus_id for bus in buses if bus.reference), buses[0].bus_id)
            angle = {
                bus.bus_id: column(-inf, inf)
                for bus in buses
                if bus.bus_id != reference
            }
            balance: dict[str, dict[int, float]] = {bus.bus_id: {} for bus in buses}
            for generator in generators:
                add(balance[generator.bus_id], column(generator.p_min_mw, generator.p_max_mw), 1.0)
            for bus in buses:
                add(balance[bus.bus_id], column(0.0, inf, 1.0), 1.0)  # shed
            for branch in branches:
                susceptance = branch.susceptance_pu * base_mva / angle_scale
                flow: dict[int, float] = {}
                if branch.from_bus_id != reference:
                    add(flow, angle[branch.from_bus_id], susceptance)
                    add(balance[branch.from_bus_id], angle[branch.from_bus_id], -susceptance)
                    add(balance[branch.to_bus_id], angle[branch.from_bus_id], susceptance)
                if branch.to_bus_id != reference:
                    add(flow, angle[branch.to_bus_id], -susceptance)
                    add(balance[branch.to_bus_id], angle[branch.to_bus_id], -susceptance)
                    add(balance[branch.from_bus_id], angle[branch.to_bus_id], susceptance)
                row(-branch.thermal_limit_mw, branch.thermal_limit_mw, flow)

            owner_rows: dict[tuple[str, str], dict[int, float]] = {key: {} for key in owners}
            for index, site in enumerate(sites):
                alpha = self.alpha_columns[index]
                load = site.load_mw_by_period[offset]
                add(balance[site.bus_id], alpha, -load)
                owner = owner_rows.get((site.team_id, site.bus_id))
                if owner is not None:
                    add(owner, alpha, -load)
                if site.generator_mw > 0.0:
                    generation = column(0.0, inf)
                    add(balance[site.bus_id], generation, 1.0)
                    add(owner, generation, 1.0)
                    row(-inf, 0.0, {generation: 1.0, alpha: -site.generator_mw})
                if site.storage_power_mw > 0.0:
                    power = column(-inf, inf)  # positive discharges
                    soc = column(0.0, inf)
                    add(balance[site.bus_id], power, 1.0)
                    add(owner, power, 1.0)
                    row(-inf, 0.0, {power: 1.0, alpha: -site.storage_power_mw})
                    row(0.0, inf, {power: 1.0, alpha: site.storage_power_mw})
                    row(-inf, 0.0, {soc: 1.0, alpha: -site.storage_energy_mwh})
                    # soc_t = soc_{t-1} - dt * power_t, starting half full.
                    energy = {soc: 1.0, power: time_step_hours}
                    if position == 0:
                        add(energy, alpha, -0.5 * site.storage_energy_mwh)
                    else:
                        add(energy, previous_soc[index], -1.0)
                    row(0.0, 0.0, energy)
                    if position == last:
                        row(0.0, 0.0, {soc: 1.0, alpha: -0.5 * site.storage_energy_mwh})
                    previous_soc[index] = soc
            for bus in buses:
                rhs = bus.demand_mw - fixed.get(bus.bus_id, 0.0)
                row(rhs, rhs, balance[bus.bus_id])
            for coefficients in owner_rows.values():
                row(-inf, 0.0, coefficients)

    def shed(self, alphas: Sequence[float]) -> tuple[float, list[float]]:
        """Return the minimum shed (MWh) at ``alphas`` and its gradient."""
        for column, alpha in zip(self.alpha_columns, alphas):
            self.highs.changeColBounds(column, alpha, alpha)
        _run_highs(self.highs)
        status = self.highs.getModelStatus()
        if status != self.status_type.kOptimal:
            raise DCOPFUnresolved(f"allocation day LP unresolved: {status}")
        if not self.solved:
            self.solved = True
            self.highs.setOptionValue("solver", "simplex")
            self.highs.setOptionValue("presolve", "off")
        solution = self.highs.getSolution()
        reduced_costs = list(solution.col_dual)
        value = float(self.highs.getInfo().objective_function_value)
        return value, [float(reduced_costs[column]) for column in self.alpha_columns]


def _build_day(artifact_root: str, sites, period_indices, offsets, time_step_hours: float) -> _DayModel:
    artifact = load_prepared_artifact(artifact_root)
    prepared = tuple(
        _prepared_period_inputs(
            artifact_root, artifact, period_index=period_indices[offset], validate_artifact=False
        )
        for offset in offsets
    )
    return _DayModel(prepared, sites, offsets, time_step_hours=time_step_hours, base_mva=100.0)


def _day_worker(connection, artifact_root, sites, period_indices, offsets, time_step_hours) -> None:
    """Keep one day's LP in this process and answer shed queries."""
    try:
        day = _build_day(artifact_root, sites, period_indices, offsets, time_step_hours)
        connection.send(("ready", None))
        while True:
            alphas = connection.recv()
            if alphas is None:
                break
            connection.send(("ok", day.shed(alphas)))
    except Exception as exc:  # reported to the parent, which raises
        connection.send(("error", repr(exc)))
    finally:
        connection.close()


class _DayPool:
    """The days' LPs, solved in this process or one worker process per day.

    Each day keeps its own model and warm start, so the answers do not depend
    on the number of workers.
    """

    def __init__(self, artifact_root, sites, period_indices, blocks, time_step_hours, workers: int) -> None:
        self.days = []
        self.processes = []
        self.connections = []
        if workers <= 1 or len(blocks) == 1:
            self.days = [
                _build_day(artifact_root, sites, period_indices, offsets, time_step_hours)
                for offsets in blocks
            ]
            return
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        for offsets in blocks:
            parent, child = context.Pipe()
            process = context.Process(
                target=_day_worker,
                args=(child, artifact_root, sites, period_indices, offsets, time_step_hours),
                daemon=True,
            )
            process.start()
            child.close()
            self.processes.append(process)
            self.connections.append(parent)
        for connection in self.connections:
            self._receive(connection)

    @staticmethod
    def _receive(connection):
        kind, payload = connection.recv()
        if kind == "error":
            raise DCOPFUnresolved(f"allocation day worker failed: {payload}")
        return payload

    def shed(self, alphas: list[float]) -> list[tuple[float, list[float]]]:
        if self.days:
            return [day.shed(alphas) for day in self.days]
        for connection in self.connections:
            connection.send(list(alphas))
        return [self._receive(connection) for connection in self.connections]

    def close(self) -> None:
        for connection in self.connections:
            try:
                connection.send(None)
                connection.close()
            except OSError:
                pass
        for process in self.processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()


def _solve_master(
    capacities: Sequence[float],
    cuts: Sequence[tuple[list[float], float]],
    *,
    minimum_total: float | None,
) -> list[float] | None:
    """Stage 1 (``minimum_total`` None) or stage 2 master over alpha;
    ``None`` when the cuts leave no alpha."""
    Highs, HighsModelStatus, _HighsVarType, inf = _highs()
    highs = Highs()
    highs.setOptionValue("output_flag", False)
    count = len(capacities)
    scale = max(capacities)
    weights = [capacity / scale for capacity in capacities]
    for weight in weights:
        # Stage 1 maximizes sum C alpha; stage 2 minimizes
        # sum C (1 - alpha)^2 = sum C alpha^2 - 2 C alpha + const.
        highs.addVariable(lb=0.0, ub=1.0, obj=-weight if minimum_total is None else -2.0 * weight)
    for gradient, rhs in cuts:
        nonzero = [(index, value) for index, value in enumerate(gradient) if value != 0.0]
        highs.addRow(-inf, rhs, len(nonzero), [index for index, _ in nonzero], [value for _, value in nonzero])
    if minimum_total is not None:
        highs.addRow(minimum_total / scale, inf, count, list(range(count)), weights)
        # Hessian of (1/2) x'Qx with Q = diag(2 C).
        highs.passHessian(count, count, 1, list(range(count + 1)), list(range(count)), [2.0 * weight for weight in weights])
    _run_highs(highs)
    status = highs.getModelStatus()
    if status == HighsModelStatus.kInfeasible:
        return None
    if status != HighsModelStatus.kOptimal:
        raise DCOPFUnresolved(f"allocation master unresolved: {status}")
    return [min(1.0, max(0.0, float(value))) for value in highs.getSolution().col_value]


def allocate_sites(
    artifact_dir: str | Path,
    sites: Sequence[AllocationSite],
    *,
    period_indices: Sequence[int],
    time_step_hours: float = 1.0,
    block_periods: int = 24,
    workers: int = 1,
) -> AllocationResult | None:
    """Return the unique utilitarian allocation, or ``None`` when even the
    base network (every alpha zero) does not fit.

    ``period_indices`` are the artifact rows; ``sites[i].load_mw_by_period``
    is indexed by position in ``period_indices``.  Storage cycles over each
    block of ``block_periods`` periods, starting and ending half full; without
    storage the periods are independent and the last block may be shorter.
    With ``workers`` > 1 the blocks are solved in parallel processes.
    """
    period_indices = tuple(period_indices)
    if not period_indices:
        raise ValueError("period_indices must not be empty")
    sites = tuple(site for site in sites if site.capacity_mw > 0.0)
    has_storage = any(site.storage_power_mw > 0.0 for site in sites)
    if block_periods <= 0 or (has_storage and len(period_indices) % block_periods):
        raise ValueError("storage needs period_indices that split into whole blocks")
    for site in sites:
        if len(site.load_mw_by_period) != len(period_indices):
            raise ValueError(f"site {site.key} needs one load per period")
    requested = sum(site.capacity_mw for site in sites)
    if not sites:
        return AllocationResult({}, 0.0, 0.0, 0.0, 0, 0, 0.0)

    artifact_root = str(Path(artifact_dir).resolve())
    artifact = load_prepared_artifact(artifact_root)
    _validate_prepared_demand_schema(artifact, period_indices)
    blocks = [
        tuple(range(start, min(start + block_periods, len(period_indices))))
        for start in range(0, len(period_indices), block_periods)
    ]
    pool = _DayPool(artifact_root, sites, period_indices, blocks, time_step_hours, workers)
    try:
        return _allocate(sites, requested, pool)
    finally:
        pool.close()


def _allocate(sites, requested: float, pool: _DayPool) -> AllocationResult | None:
    capacities = [site.capacity_mw for site in sites]
    cuts: list[tuple[list[float], float]] = []
    iterations = 0
    max_shed = 0.0

    def cut_violations(alphas: list[float]) -> bool:
        """Add a cut for every day that does not fit at ``alphas``."""
        nonlocal max_shed
        violated = False
        max_shed = 0.0
        for shed, gradient in pool.shed(alphas):
            max_shed = max(max_shed, shed)
            if shed > SHED_TOLERANCE_MWH:
                # shed(alpha) >= shed + g'(alpha - alphas) must be <= 0.
                cuts.append((gradient, sum(g * a for g, a in zip(gradient, alphas)) - shed))
                violated = True
        return violated

    def converge(minimum_total: float | None, core: list[float]) -> list[float] | None:
        """Cutting planes with in-out separation.

        ``core`` is a point known to fit.  Each master proposal is first
        tested halfway towards it: a cut there is deeper, and when that
        point fits it becomes the new core.  The proposal itself is tested
        only when the halfway point fits, so the loop ends exactly when the
        master's optimum fits.
        """
        nonlocal iterations
        while True:
            iterations += 1
            if iterations > MAX_ITERATIONS:
                raise DCOPFUnresolved("allocation did not converge")
            alphas = _solve_master(capacities, cuts, minimum_total=minimum_total)
            if alphas is None:
                return None
            middle = [c + IN_OUT_STEP * (a - c) for a, c in zip(alphas, core)]
            if max(abs(a - m) for a, m in zip(alphas, middle)) > 1e-9 and cut_violations(middle):
                continue
            core = middle
            if not cut_violations(alphas):
                return alphas

    # The master becomes infeasible only when no alpha >= 0 fits, i.e. the
    # base network itself cannot be dispatched.
    stage_one = converge(None, [0.0] * len(sites))
    if stage_one is None:
        return None
    best_total = sum(c * a for c, a in zip(capacities, stage_one))
    if best_total <= EMPTY_TOTAL_MW:
        # No room at all (e.g. Submission 1 filled these buses): every
        # fraction is zero, and the tie-break problem would be degenerate.
        stage_one = [0.0] * len(capacities)
        best_total = 0.0
    minimum_total = best_total * (1.0 - TOTAL_RELATIVE_TOLERANCE)
    alphas = converge(minimum_total, stage_one) if 0.0 < best_total < requested else stage_one
    if alphas is None:
        raise DCOPFUnresolved("allocation tie-break found no point at the stage-1 total")
    return AllocationResult(
        alpha_by_site={site.key: alpha for site, alpha in zip(sites, alphas)},
        max_total_capacity_mw=best_total,
        total_capacity_mw=sum(c * a for c, a in zip(capacities, alphas)),
        requested_capacity_mw=requested,
        iterations=iterations,
        cuts=len(cuts),
        max_shed_mwh=max_shed,
    )
