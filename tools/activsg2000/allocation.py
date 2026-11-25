"""Utilitarian allocation of requested sites on the shared network.

When the submitted plans do not fit the grid together, every site i gets a
fraction ``alpha_i`` in [0, 1].  The fraction scales the site's connection
capacity C, generator capacity G, storage power P and storage energy B.  The
allocation solves

* stage 1: maximize the total grid request served, ``sum_i alpha_i w_i`` with
  ``w_i = C_i - G_i``, subject to the DCOPF of every period (load
  ``alpha_i C_i`` served in every period, the site's generator up to
  ``alpha_i G_i`` and its storage within ``alpha_i P_i`` and ``alpha_i B_i``,
  each team's generator and storage serving only that team's load at the
  bus).  A site's own generator is behind the meter: it serves the site, so
  only ``C_i - G_i`` counts as a request to the grid.  Storage is dispatched
  by the grid operator and is not subtracted;
* stage 2 (tie-break): among the stage-1 optima, minimize
  ``sum_i w_i (1 - alpha_i)^2``.  The objective is strictly convex in alpha,
  so the allocation is unique and does not depend on the solver's choice
  among optimal vertices; sites that tie in stage 1 get the same alpha.

A site with ``G_i = C_i`` asks nothing of the grid; its weight is floored at
``GRID_WEIGHT_FLOOR * C_i`` so that its alpha is still determined (it is 1,
since such a site can always serve itself).

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
    resolve_solver_backend,
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
    full_checks: int = 0
    active_hours: int | None = None
    # Stage-1 optimum: the most grid request, sum alpha (C - G), that fits.
    max_grid_capacity_mw: float = 0.0


# Weight of a site whose generator covers its whole connection (G = C),
# as a share of C, so that its alpha is determined.
GRID_WEIGHT_FLOOR = 1e-6
# A day fits when its LP sheds at most this much energy (MWh).
SHED_TOLERANCE_MWH = 1e-4
# With hour screening, an hour of the full LP that sheds more than this
# (MWh) joins the screened LP.
HOUR_SHED_TOLERANCE_MWH = 1e-7
# Stage 2 keeps the total grid request served within this share of stage 1.
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
        solver_backend: str = "highs",
        solver_threads: int = 1,
        active_offsets: frozenset[int] | None = None,
    ) -> None:
        if solver_backend not in {"highs", "gurobi"}:
            raise ValueError("solver_backend must be 'highs' or 'gurobi'")
        self.backend = solver_backend
        self.solved = False
        angle_scale = 1000.0
        inf = math.inf

        def add(coefficients: dict[int, float], column: int, value: float) -> None:
            coefficients[column] = coefficients.get(column, 0.0) + value

        if solver_backend == "highs":
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

            def row(lower: float, upper: float, coefficients: dict[int, float]) -> None:
                highs.addRow(lower, upper, len(coefficients), list(coefficients), list(coefficients.values()))

            def column(lower: float, upper: float, cost: float = 0.0) -> int:
                highs.addVariable(lb=lower, ub=upper, obj=cost)
                return highs.getNumCol() - 1

        else:
            # Gurobi: record the same columns and rows, then load them as one
            # sparse matrix (see _load_gurobi).
            self._column_data: list[tuple[float, float, float]] = []
            self._row_data: list[tuple[float, float, dict[int, float]]] = []

            def row(lower: float, upper: float, coefficients: dict[int, float]) -> None:
                self._row_data.append((lower, upper, coefficients))

            def column(lower: float, upper: float, cost: float = 0.0) -> int:
                self._column_data.append((lower, upper, cost))
                return len(self._column_data) - 1

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
        # Shed columns of each hour with network rows, to report which hours
        # do not fit (see hour_shed).
        self.shed_columns_by_offset: dict[int, list[int]] = {}
        for position, (offset, (buses, generators, branches, fixed)) in enumerate(
            zip(period_offsets, prepared_periods)
        ):
            if active_offsets is not None and offset not in active_offsets:
                # A screened-out hour keeps only the storage state of charge,
                # the generator limits and the "serve only your own load"
                # rows; its network rows are dropped, which relaxes the day.
                self._add_site_rows(
                    sites, offset, position, last, None, owners, previous_soc, time_step_hours, add, row, column, inf
                )
                continue
            reference = next((bus.bus_id for bus in buses if bus.reference), buses[0].bus_id)
            angle = {
                bus.bus_id: column(-inf, inf)
                for bus in buses
                if bus.bus_id != reference
            }
            balance: dict[str, dict[int, float]] = {bus.bus_id: {} for bus in buses}
            for generator in generators:
                add(balance[generator.bus_id], column(generator.p_min_mw, generator.p_max_mw), 1.0)
            shed_columns = self.shed_columns_by_offset.setdefault(offset, [])
            for bus in buses:
                shed_column = column(0.0, inf, 1.0)
                shed_columns.append(shed_column)
                add(balance[bus.bus_id], shed_column, 1.0)  # shed
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

            self._add_site_rows(
                sites, offset, position, last, balance, owners, previous_soc, time_step_hours, add, row, column, inf
            )
            for bus in buses:
                rhs = bus.demand_mw - fixed.get(bus.bus_id, 0.0)
                row(rhs, rhs, balance[bus.bus_id])
        if solver_backend == "gurobi":
            self._load_gurobi(solver_threads)

    def _add_site_rows(
        self, sites, offset, position, last, balance, owners, previous_soc, time_step_hours, add, row, column, inf
    ) -> None:
        """The sites' columns and rows of one hour.  ``balance`` is ``None``
        for an hour without network rows."""
        owner_rows: dict[tuple[str, str], dict[int, float]] = {key: {} for key in owners}
        for index, site in enumerate(sites):
            alpha = self.alpha_columns[index]
            load = site.load_mw_by_period[offset]
            if balance is not None:
                add(balance[site.bus_id], alpha, -load)
            owner = owner_rows.get((site.team_id, site.bus_id))
            if owner is not None:
                add(owner, alpha, -load)
            if site.generator_mw > 0.0:
                generation = column(0.0, inf)
                if balance is not None:
                    add(balance[site.bus_id], generation, 1.0)
                add(owner, generation, 1.0)
                row(-inf, 0.0, {generation: 1.0, alpha: -site.generator_mw})
            if site.storage_power_mw > 0.0:
                power = column(-inf, inf)  # positive discharges
                soc = column(0.0, inf)
                if balance is not None:
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
        for coefficients in owner_rows.values():
            row(-inf, 0.0, coefficients)

    def _load_gurobi(self, solver_threads: int) -> None:
        import gurobipy as gp
        import numpy as np
        import scipy.sparse as sp

        self._gp = gp
        columns = self._column_data
        model = gp.Model("allocation_day")
        model.Params.OutputFlag = 0
        model.Params.Threads = solver_threads
        # First solve from scratch with barrier (and crossover to a basis);
        # later solves only change the alpha bounds and warm-start the dual
        # simplex from the previous basis (see shed).
        model.Params.Method = 2
        big = gp.GRB.INFINITY
        x = model.addMVar(
            len(columns),
            lb=np.array([-big if math.isinf(lb) else lb for lb, _ub, _c in columns]),
            ub=np.array([big if math.isinf(ub) else ub for _lb, ub, _c in columns]),
            obj=np.array([cost for _lb, _ub, cost in columns]),
        )
        # Split ranged rows (branch limits) into two one-sided rows.
        senses: list[str] = []
        rhs: list[float] = []
        row_index: list[int] = []
        col_index: list[int] = []
        values: list[float] = []

        def emit(sense: str, bound: float, coefficients: dict[int, float]) -> None:
            position = len(senses)
            senses.append(sense)
            rhs.append(bound)
            row_index.extend([position] * len(coefficients))
            col_index.extend(coefficients)
            values.extend(coefficients.values())

        for lower, upper, coefficients in self._row_data:
            if lower == upper:
                emit("=", lower, coefficients)
                continue
            if not math.isinf(lower):
                emit(">", lower, coefficients)
            if not math.isinf(upper):
                emit("<", upper, coefficients)
        matrix = sp.csr_matrix((values, (row_index, col_index)), shape=(len(senses), len(columns)))
        model.addMConstr(matrix, x, np.array(senses), np.array(rhs))
        model.update()
        self._model = model
        self._vars = x.tolist()
        del self._column_data, self._row_data

    def _shed_gurobi(self, alphas: Sequence[float]) -> tuple[float, list[float]]:
        gp = self._gp
        alpha_vars = [self._vars[column] for column in self.alpha_columns]
        for var, alpha in zip(alpha_vars, alphas):
            var.LB = alpha
            var.UB = alpha
        self._model.optimize()
        status = self._model.Status
        if status != gp.GRB.OPTIMAL:
            raise DCOPFUnresolved(f"allocation day LP unresolved: Gurobi status {status}")
        if not self.solved:
            self.solved = True
            self._model.Params.Method = 1
        reduced_costs = self._model.getAttr("RC", alpha_vars)
        return float(self._model.ObjVal), [float(value) for value in reduced_costs]

    def shed(self, alphas: Sequence[float]) -> tuple[float, list[float]]:
        """Return the minimum shed (MWh) at ``alphas`` and its gradient."""
        if self.backend == "gurobi":
            return self._shed_gurobi(alphas)
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

    def hour_shed(self) -> dict[int, float]:
        """Shed (MWh) of each hour with network rows at the last solve."""
        if self.backend == "gurobi":
            values = self._model.getAttr("X", self._vars)
        else:
            values = self.highs.getSolution().col_value
        return {
            offset: float(sum(values[column] for column in columns))
            for offset, columns in self.shed_columns_by_offset.items()
        }


def _reserve_order(prepared_periods, offsets) -> list[int]:
    """The day's hours from the least to the most generation reserve
    (online capacity minus net demand)."""
    reserve = {}
    for offset, (buses, generators, _branches, fixed) in zip(offsets, prepared_periods):
        net_demand = sum(bus.demand_mw for bus in buses) - sum(fixed.values())
        reserve[offset] = sum(generator.p_max_mw for generator in generators) - net_demand
    return sorted(offsets, key=lambda offset: (reserve[offset], offset))


class _Day:
    """One day of the allocation: a screened LP and, on demand, the full LP.

    With ``screened_hours`` set, the screened LP has network rows only in an
    active set of hours, starting with the ``screened_hours`` hours of least
    generation reserve.  Every other hour keeps its storage and own-load rows,
    so the screened LP is a relaxation: its shed is at most the full shed,
    and its cuts are valid for the full day.  :meth:`full` checks a point
    against the full LP and returns the hours that shed load, which the
    caller adds with :meth:`activate`.  Without screening both are the
    same full LP.
    """

    def __init__(
        self, artifact_root, sites, period_indices, offsets, time_step_hours, solver_backend, solver_threads,
        screened_hours,
    ) -> None:
        artifact = load_prepared_artifact(artifact_root)
        self.prepared = tuple(
            _prepared_period_inputs(
                artifact_root, artifact, period_index=period_indices[offset], validate_artifact=False
            )
            for offset in offsets
        )
        self.sites = sites
        self.offsets = tuple(offsets)
        self.options = dict(time_step_hours=time_step_hours, base_mva=100.0, solver_backend=solver_backend,
                            solver_threads=solver_threads)
        self.full_model = None
        if screened_hours is None or screened_hours >= len(self.offsets):
            self.active = None
            self.screened = self._model(None)
            self.full_model = self.screened
        else:
            self.active = frozenset(_reserve_order(self.prepared, self.offsets)[:screened_hours])
            self.screened = self._model(self.active)

    def _model(self, active) -> _DayModel:
        return _DayModel(self.prepared, self.sites, self.offsets, active_offsets=active, **self.options)

    def shed(self, alphas):
        return self.screened.shed(alphas)

    def full(self, alphas):
        """Shed and gradient of the full LP, and the hours that shed load."""
        if self.full_model is None:
            self.full_model = self._model(None)
        shed, gradient = self.full_model.shed(alphas)
        hours = []
        if shed > SHED_TOLERANCE_MWH:
            by_hour = self.full_model.hour_shed()
            hours = [offset for offset, value in by_hour.items() if value > HOUR_SHED_TOLERANCE_MWH]
            if not hours:
                hours = [max(by_hour, key=by_hour.get)]
        return shed, gradient, hours

    def activate(self, hours) -> int:
        """Add hours to the screened LP; return the number of active hours."""
        if self.active is None:
            return len(self.offsets)
        new = self.active | frozenset(hours)
        if new != self.active:
            self.active = new
            if len(new) == len(self.offsets):
                self.screened = self.full_model if self.full_model is not None else self._model(None)
            else:
                self.screened = self._model(new)
        return len(self.active)


def _build_day(
    artifact_root: str,
    sites,
    period_indices,
    offsets,
    time_step_hours: float,
    solver_backend: str = "highs",
    solver_threads: int = 1,
    screened_hours: int | None = None,
) -> _Day:
    return _Day(
        artifact_root, sites, period_indices, offsets, time_step_hours, solver_backend, solver_threads,
        screened_hours,
    )


def _day_worker(
    connection, artifact_root, sites, period_indices, offsets, time_step_hours, solver_backend, solver_threads,
    screened_hours,
) -> None:
    """Keep one day's LPs in this process and answer queries."""
    try:
        day = _build_day(
            artifact_root, sites, period_indices, offsets, time_step_hours, solver_backend, solver_threads,
            screened_hours,
        )
        connection.send(("ready", None))
        while True:
            message = connection.recv()
            if message is None:
                break
            method, argument = message
            connection.send(("ok", getattr(day, method)(argument)))
    except Exception as exc:  # reported to the parent, which raises
        connection.send(("error", repr(exc)))
    finally:
        connection.close()


class _DayPool:
    """The days' LPs, solved in this process or one worker process per day.

    Each day keeps its own model and warm start, so the answers do not depend
    on the number of workers.
    """

    def __init__(
        self,
        artifact_root,
        sites,
        period_indices,
        blocks,
        time_step_hours,
        workers: int,
        solver_backend: str = "highs",
        solver_threads: int = 1,
        screened_hours: int | None = None,
    ) -> None:
        self.days = []
        self.processes = []
        self.connections = []
        if workers <= 1 or len(blocks) == 1:
            self.days = [
                _build_day(
                    artifact_root, sites, period_indices, offsets, time_step_hours, solver_backend, solver_threads,
                    screened_hours,
                )
                for offsets in blocks
            ]
            return
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        for offsets in blocks:
            parent, child = context.Pipe()
            process = context.Process(
                target=_day_worker,
                args=(
                    child,
                    artifact_root,
                    sites,
                    period_indices,
                    offsets,
                    time_step_hours,
                    solver_backend,
                    solver_threads,
                    screened_hours,
                ),
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

    def _call(self, method: str, arguments: list) -> list:
        if self.days:
            return [getattr(day, method)(argument) for day, argument in zip(self.days, arguments)]
        for connection, argument in zip(self.connections, arguments):
            connection.send((method, argument))
        return [self._receive(connection) for connection in self.connections]

    def _count(self) -> int:
        return len(self.days) or len(self.connections)

    def shed(self, alphas: list[float]) -> list[tuple[float, list[float]]]:
        """Shed and gradient of each day's screened LP."""
        return self._call("shed", [list(alphas)] * self._count())

    def full(self, alphas: list[float]) -> list[tuple[float, list[float], list[int]]]:
        """Shed, gradient and shedding hours of each day's full LP."""
        return self._call("full", [list(alphas)] * self._count())

    def activate(self, hours_by_day: list[list[int]]) -> list[int]:
        return self._call("activate", hours_by_day)

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


def grid_weight_mw(site: AllocationSite) -> float:
    """A site's request to the grid, ``C - G``, floored for off-grid sites."""
    return max(site.capacity_mw - site.generator_mw, GRID_WEIGHT_FLOOR * site.capacity_mw)


def _solve_master(
    weights_mw: Sequence[float],
    cuts: Sequence[tuple[list[float], float]],
    *,
    minimum_total: float | None,
) -> list[float] | None:
    """Stage 1 (``minimum_total`` None) or stage 2 master over alpha;
    ``None`` when the cuts leave no alpha."""
    Highs, HighsModelStatus, _HighsVarType, inf = _highs()
    highs = Highs()
    highs.setOptionValue("output_flag", False)
    count = len(weights_mw)
    scale = max(weights_mw)
    weights = [weight / scale for weight in weights_mw]
    for weight in weights:
        # Stage 1 maximizes sum w alpha; stage 2 minimizes
        # sum w (1 - alpha)^2 = sum w alpha^2 - 2 w alpha + const.
        highs.addVariable(lb=0.0, ub=1.0, obj=-weight if minimum_total is None else -2.0 * weight)
    for gradient, rhs in cuts:
        nonzero = [(index, value) for index, value in enumerate(gradient) if value != 0.0]
        highs.addRow(-inf, rhs, len(nonzero), [index for index, _ in nonzero], [value for _, value in nonzero])
    if minimum_total is not None:
        highs.addRow(minimum_total / scale, inf, count, list(range(count)), weights)
        # Hessian of (1/2) x'Qx with Q = diag(2 w).
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
    solver_backend: str = "highs",
    solver_threads: int = 1,
    screened_hours: int | None = None,
) -> AllocationResult | None:
    """Return the unique utilitarian allocation, or ``None`` when even the
    base network (every alpha zero) does not fit.

    ``period_indices`` are the artifact rows; ``sites[i].load_mw_by_period``
    is indexed by position in ``period_indices``.  Storage cycles over each
    block of ``block_periods`` periods, starting and ending half full; without
    storage the periods are independent and the last block may be shorter.
    With ``workers`` > 1 the blocks are solved in parallel processes.
    ``solver_backend`` (``highs``, ``gurobi`` or ``auto``: Gurobi when
    licensed) solves the daily LPs, each with ``solver_threads`` threads;
    the master problem always uses HiGHS.  ``screened_hours`` (None: off)
    starts each day's LP with network rows in only that many hours of least
    generation reserve and adds the hours that shed load at the candidate
    allocation (see :class:`_Day`); the result is the same allocation.
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
    backend = resolve_solver_backend(solver_backend)
    if not isinstance(solver_threads, int) or isinstance(solver_threads, bool) or solver_threads <= 0:
        raise ValueError("solver_threads must be a positive integer")
    if screened_hours is not None and (
        not isinstance(screened_hours, int) or isinstance(screened_hours, bool) or screened_hours <= 0
    ):
        raise ValueError("screened_hours must be a positive integer or None")
    pool = _DayPool(
        artifact_root, sites, period_indices, blocks, time_step_hours, workers, backend, solver_threads,
        screened_hours,
    )
    try:
        return _allocate(sites, requested, pool)
    finally:
        pool.close()


def _allocate(sites, requested: float, pool: _DayPool) -> AllocationResult | None:
    capacities = [site.capacity_mw for site in sites]
    weights = [grid_weight_mw(site) for site in sites]
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
            alphas = _solve_master(weights, cuts, minimum_total=minimum_total)
            if alphas is None:
                return None
            middle = [c + IN_OUT_STEP * (a - c) for a, c in zip(alphas, core)]
            if max(abs(a - m) for a, m in zip(alphas, middle)) > 1e-9 and cut_violations(middle):
                continue
            core = middle
            if not cut_violations(alphas):
                return alphas

    full_checks = 0
    active_hours: int | None = None

    def full_violations(alphas: list[float]) -> bool:
        """Check ``alphas`` against every day's full LP; cut every day that
        does not fit and add its shedding hours to its screened LP."""
        nonlocal max_shed, full_checks, active_hours
        full_checks += 1
        violated = False
        max_shed = 0.0
        hours_by_day = []
        for shed, gradient, hours in pool.full(alphas):
            max_shed = max(max_shed, shed)
            if shed > SHED_TOLERANCE_MWH:
                cuts.append((gradient, sum(g * a for g, a in zip(gradient, alphas)) - shed))
                violated = True
            hours_by_day.append(hours)
        if violated:
            active_hours = sum(pool.activate(hours_by_day))
        return violated

    def solve_stage(minimum_total: float | None, core: list[float]) -> list[float] | None:
        """Converge on the screened LPs until the point fits the full LPs.

        The screened LPs relax the full ones, so their cuts stay valid and
        an optimum of the screened problem that fits the full LPs is an
        optimum of the full problem.  ``core`` must fit the full LPs.
        """
        while True:
            alphas = converge(minimum_total, core)
            if alphas is None or not full_violations(alphas):
                return alphas

    # The master becomes infeasible only when no alpha >= 0 fits, i.e. the
    # base network itself cannot be dispatched.
    stage_one = solve_stage(None, [0.0] * len(sites))
    if stage_one is None:
        return None
    best_total = sum(w * a for w, a in zip(weights, stage_one))
    # Test served capacity, not the weighted total: off-grid sites carry
    # only a floor weight but are fully served.
    if sum(c * a for c, a in zip(capacities, stage_one)) <= EMPTY_TOTAL_MW:
        # No room at all (e.g. Submission 1 filled these buses): every
        # fraction is zero, and the tie-break problem would be degenerate.
        stage_one = [0.0] * len(capacities)
        best_total = 0.0
    minimum_total = best_total * (1.0 - TOTAL_RELATIVE_TOLERANCE)
    requested_grid = sum(weights)
    alphas = solve_stage(minimum_total, stage_one) if 0.0 < best_total < requested_grid else stage_one
    if alphas is None:
        raise DCOPFUnresolved("allocation tie-break found no point at the stage-1 total")
    return AllocationResult(
        alpha_by_site={site.key: alpha for site, alpha in zip(sites, alphas)},
        max_total_capacity_mw=sum(c * a for c, a in zip(capacities, stage_one)),
        total_capacity_mw=sum(c * a for c, a in zip(capacities, alphas)),
        requested_capacity_mw=requested,
        iterations=iterations,
        cuts=len(cuts),
        max_shed_mwh=max_shed,
        full_checks=full_checks,
        active_hours=active_hours,
        max_grid_capacity_mw=best_total,
    )
