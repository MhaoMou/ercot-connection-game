"""Submission 1 sites as fixed base load for Submission 2.

In the ten-year release every Submission 1 site of every team becomes part
of the base load of Submission 2: its hourly net grid withdrawal (site load
served minus its own private generation and battery net discharge) is added
to the bus demand of the representative package.  Those sites are not
re-evaluated, re-scored, re-projected or re-dispatched in Submission 2.

The batch writer records the per-site withdrawal in ``site_net_withdrawal.csv``;
:func:`materialize_base_load_artifact` turns it into a derived scenario
artifact whose ``demand_bus.csv`` is base demand plus that withdrawal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import csv
import json
import math
from pathlib import Path
import shutil
from typing import Any

from .models import TeamPlan
from .scenario_package import sha256_file


SITE_NET_WITHDRAWAL_FILE = "site_net_withdrawal.csv"
SITE_NET_WITHDRAWAL_FIELDS = (
    "period_index",
    "team_id",
    "site_id",
    "bus_id",
    "load_mw",
    "generation_mw",
    "storage_discharge_mw",
    "storage_charge_mw",
    "net_withdrawal_mw",
)
_STATIC_FILES = (
    "bus.csv",
    "bus_load_base.csv",
    "branch_limits.csv",
    "generator_catalog.csv",
    "generator_limits.csv",
    "dcline.csv",
)
_OPTIONAL_FILES = ("representative_days.csv",)
_DEMAND_DECIMALS = 6


def _team_dispatches(evaluation: Any) -> dict[str, Any]:
    """Return the dispatch each feasible team was scored on."""
    feasible = {
        score.team_id
        for score in getattr(evaluation, "team_scores", ())
        if score.valid and score.feasible
    }
    by_team: dict[str, Any] = {}
    for record in getattr(evaluation, "dispatch_records", ()):
        if record.status != "feasible" or record.dispatch is None:
            continue
        for team_id in record.attempted_team_ids:
            if team_id in feasible:
                by_team[team_id] = record.dispatch
    dispatch = getattr(evaluation, "dispatch", None)
    if dispatch is not None:
        for team_id in feasible:
            if team_id not in by_team and team_id in getattr(dispatch, "team_ids", ()):
                by_team[team_id] = dispatch
    return by_team


def _site_capacities(plan: TeamPlan) -> dict[str, tuple[str, float]]:
    if plan.connections:
        return {
            connection.connection_id: (connection.bus_id, float(connection.capacity_mw))
            for connection in plan.connections
        }
    return {site.site_id: (site.bus_id, float(site.connection_capacity_mw)) for site in plan.sites}


def site_net_withdrawal_rows(evaluation: Any) -> list[dict[str, Any]]:
    """Return one row per scored site and period with its net grid withdrawal.

    Site load is the team's dispatched load split by connection capacity
    (the projection scales every site of a team by the same fraction).
    """
    plans = {plan.team_id: plan for plan in getattr(evaluation, "evaluated_plans", ())}
    rows: list[dict[str, Any]] = []
    for team_id, dispatch in sorted(_team_dispatches(evaluation).items()):
        plan = plans.get(team_id)
        if plan is None:
            continue
        sites = _site_capacities(plan)
        team_capacity = sum(capacity for _bus, capacity in sites.values())
        generator_site = {generator.generator_id: generator.connection_id for generator in plan.generators}
        storage_site = {storage.storage_id: storage.connection_id for storage in plan.storages}
        for period in dispatch.periods:
            team_load = float(period.submitted_load_mw_by_team.get(team_id, 0.0))
            generation: dict[str, float] = {}
            for generator_id, amount in (period.generator_dispatch_mw_by_team.get(team_id) or {}).items():
                site_id = generator_site.get(generator_id)
                if site_id is not None:
                    generation[site_id] = generation.get(site_id, 0.0) + float(amount)
            discharge: dict[str, float] = {}
            charge: dict[str, float] = {}
            for target, source in (
                (discharge, getattr(period, "storage_discharge_mw_by_team", None)),
                (charge, getattr(period, "storage_charge_mw_by_team", None)),
            ):
                for storage_id, amount in ((source or {}).get(team_id) or {}).items():
                    site_id = storage_site.get(storage_id)
                    if site_id is not None:
                        target[site_id] = target.get(site_id, 0.0) + float(amount)
            for site_id, (bus_id, capacity) in sorted(sites.items()):
                load = team_load * capacity / team_capacity if team_capacity > 0 else 0.0
                net = load - generation.get(site_id, 0.0) - discharge.get(site_id, 0.0) + charge.get(site_id, 0.0)
                rows.append(
                    {
                        "period_index": period.period_index,
                        "team_id": team_id,
                        "site_id": site_id,
                        "bus_id": bus_id,
                        "load_mw": load,
                        "generation_mw": generation.get(site_id, 0.0),
                        "storage_discharge_mw": discharge.get(site_id, 0.0),
                        "storage_charge_mw": charge.get(site_id, 0.0),
                        "net_withdrawal_mw": net,
                    }
                )
    rows.sort(key=lambda row: (row["team_id"], row["site_id"], row["period_index"]))
    return rows


def write_site_net_withdrawal(rows: Sequence[Mapping[str, Any]], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SITE_NET_WITHDRAWAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in SITE_NET_WITHDRAWAL_FIELDS})


def read_site_net_withdrawal(path: str | Path) -> list[dict[str, Any]]:
    """Read a Submission 1 ``site_net_withdrawal.csv`` (file or output directory)."""
    source = Path(path)
    if not source.exists():
        raise ValueError(f"Submission 1 output directory not found: {source}")
    if source.is_dir():
        source = source / SITE_NET_WITHDRAWAL_FILE
    if not source.is_file():
        raise ValueError(
            f"Submission 1 output has no {SITE_NET_WITHDRAWAL_FILE}: {source}; "
            "rerun Submission 1 with this evaluator version"
        )
    rows = []
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != SITE_NET_WITHDRAWAL_FIELDS:
            raise ValueError(f"{source} has an unexpected header")
        for row in reader:
            parsed: dict[str, Any] = {
                "period_index": int(row["period_index"]),
                "team_id": row["team_id"],
                "site_id": row["site_id"],
                "bus_id": row["bus_id"],
            }
            for field in SITE_NET_WITHDRAWAL_FIELDS[4:]:
                value = float(row[field])
                if not math.isfinite(value):
                    raise ValueError(f"{source}: {field} must be finite")
                parsed[field] = value
            rows.append(parsed)
    return rows


def site_ids_by_team(rows: Iterable[Mapping[str, Any]]) -> dict[str, frozenset[str]]:
    """Return each team's Submission 1 site IDs."""
    result: dict[str, set[str]] = {}
    for row in rows:
        result.setdefault(str(row["team_id"]), set()).add(str(row["site_id"]))
    return {team_id: frozenset(sites) for team_id, sites in sorted(result.items())}


def net_withdrawal_by_bus(rows: Iterable[Mapping[str, Any]], horizon: int) -> dict[str, list[float]]:
    """Sum site withdrawals per bus into one value per period."""
    result: dict[str, list[float]] = {}
    for row in rows:
        period_index = int(row["period_index"])
        if not 0 <= period_index < horizon:
            raise ValueError(f"withdrawal period {period_index} is outside the horizon {horizon}")
        values = result.setdefault(str(row["bus_id"]), [0.0] * horizon)
        values[period_index] += float(row["net_withdrawal_mw"])
    return result


# A period of the derived artifact that the strict single-period DCOPF does
# not solve (HiGHS kInfeasible/kUnknown) is accepted only when a demand change
# of at most this many MW in total, at the buses that carry Submission 1
# withdrawal, makes it solve.  Submission 1 projects teams to the edge of
# feasibility, so the carried withdrawal can sit within solver tolerance
# (about 1e-7 MW) of the boundary; anything larger is a real infeasibility.
BASE_LOAD_VALIDATION_TOLERANCE_MW = 1.0e-3
# Extra margin applied away from the boundary when an adjustment is needed,
# so that the strict re-solve (and the Submission 2 evaluation) is not again
# decided by solver tolerances.
_BASE_LOAD_ADJUSTMENT_MARGIN_MW = 1.0e-6


class BaseLoadValidationError(ValueError):
    """The derived Submission 2 base load is not DCOPF-feasible."""

    def __init__(self, message: str, periods: Sequence[int]) -> None:
        super().__init__(message)
        self.periods = tuple(periods)


def materialize_base_load_artifact(
    source_artifact: str | Path,
    withdrawal_mw_by_bus: Mapping[str, Sequence[float]],
    output_dir: str | Path,
    *,
    provenance: Mapping[str, Any] | None = None,
    validate: bool = True,
    tolerance_mw: float = BASE_LOAD_VALIDATION_TOLERANCE_MW,
    workers: int = 1,
) -> dict[str, Any]:
    """Write a scenario artifact whose demand is base demand plus withdrawal.

    The source must be a ``demand_bus.csv`` artifact (the representative
    package).  A bus whose total would turn negative (a Submission 1 site
    exporting more than the bus base load) is floored at zero and the floored
    energy is recorded in the manifest.

    With ``validate`` every period is solved with the strict single-period
    DCOPF.  A period that does not solve is re-checked with a phase-one LP
    that finds the smallest demand change at the withdrawal buses restoring
    feasibility: if that change totals at most ``tolerance_mw`` it is applied
    (moved ``_BASE_LOAD_ADJUSTMENT_MARGIN_MW`` further from the boundary),
    the period is re-solved strictly, and every change is recorded under
    ``validation.tolerance_adjustments``.  Otherwise the manifest is left
    ``failed`` (never ``pending``) and :class:`BaseLoadValidationError`
    names the offending periods.
    """
    from .scenario_package import require_validated_block

    source = Path(source_artifact)
    output = Path(output_dir)
    source_manifest = require_validated_block(source)
    demand_path = source / "demand_bus.csv"
    if not demand_path.is_file():
        raise ValueError("Submission 2 base load needs a demand_bus.csv scenario artifact")
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").unlink(missing_ok=True)
    for name in _STATIC_FILES + _OPTIONAL_FILES:
        if (source / name).is_file():
            shutil.copyfile(source / name, output / name)
        elif name in _STATIC_FILES:
            raise ValueError(f"source artifact is missing {name}")

    with demand_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        source_rows = list(reader)
    horizon = len(source_rows)
    bus_columns = header[1:]
    unknown = sorted(set(withdrawal_mw_by_bus) - set(bus_columns))
    if unknown:
        raise ValueError("withdrawal references unknown bus: " + ", ".join(unknown))
    floored: list[dict[str, Any]] = []
    added_mwh = 0.0
    rows = []
    for period_index, raw in enumerate(source_rows):
        values = []
        for bus_id, text in zip(bus_columns, raw[1:]):
            extra = withdrawal_mw_by_bus.get(bus_id)
            if extra is None:
                values.append(text)
                continue
            if len(extra) != horizon:
                raise ValueError(f"withdrawal for bus {bus_id} must have {horizon} periods")
            total = float(text) + float(extra[period_index])
            added_mwh += float(extra[period_index])
            if total < 0.0:
                floored.append({"period_index": period_index, "bus_id": bus_id, "floored_mw": round(-total, 6)})
                total = 0.0
            values.append(f"{total:.{_DEMAND_DECIMALS}f}")
        rows.append([raw[0], *values])
    _write_demand(output, header, rows)

    manifest = {
        key: value
        for key, value in source_manifest.items()
        if key not in {"network", "validation", "validation_status", "validated_state_hash"}
    }
    manifest.update(
        {
            "validation_status": "pending",
            "description": (
                "Submission 2 base load: the source scenario plus the hourly net grid "
                "withdrawal of every Submission 1 site."
            ),
            "submission_2_base_load": {
                "source_artifact": str(source_manifest.get("package_version")),
                "source_demand_sha256": sha256_file(demand_path),
                "withdrawal_bus_count": len(withdrawal_mw_by_bus),
                "added_energy_mwh_per_period_sum": round(added_mwh, 6),
                "floored_points": floored,
                **dict(provenance or {}),
            },
        }
    )
    _set_network_hashes(output, manifest)
    _write_manifest(output, manifest)
    if not validate:
        manifest["validation"] = {
            "method": "not re-solved; the Submission 1 joint dispatch was feasible with this withdrawal",
        }
        manifest["validation_status"] = "passed"
        _write_manifest(output, manifest)
        return manifest

    try:
        adjustments, failures = _validate_base_load(
            output, horizon, sorted(withdrawal_mw_by_bus), tolerance_mw=tolerance_mw, workers=workers
        )
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        manifest["validation_status"] = "failed"
        manifest["validation"] = {"method": _VALIDATION_METHOD, "error": str(exc)}
        _write_manifest(output, manifest)
        raise
    if adjustments and not failures:
        column = {bus_id: index for index, bus_id in enumerate(bus_columns, start=1)}
        for item in adjustments:
            rows[item["period_index"]][column[item["bus_id"]]] = f"{item['adjusted_demand_mw']:.{_DEMAND_DECIMALS}f}"
        _write_demand(output, header, rows)
        _set_network_hashes(output, manifest)
        _write_manifest(output, manifest)
        # Re-solve the adjusted periods strictly.
        recheck, _ = _validate_base_load(
            output,
            horizon,
            (),
            tolerance_mw=0.0,
            workers=workers,
            periods=sorted({item["period_index"] for item in adjustments}),
        )
        failures = [
            {"period_index": item["period_index"], "reason": "still unsolved after the tolerance adjustment"}
            for item in recheck
        ] + failures
    validation: dict[str, Any] = {
        "method": _VALIDATION_METHOD,
        "tolerance_mw": tolerance_mw,
        "passed_period_count": horizon - len({item["period_index"] for item in failures}),
        "tolerance_adjustments": [
            {key: item[key] for key in ("period_index", "bus_id", "change_mw", "solver_status")}
            for item in adjustments
        ],
        "tolerance_adjusted_period_count": len({item["period_index"] for item in adjustments}),
        "tolerance_adjusted_total_mw": round(sum(abs(item["change_mw"]) for item in adjustments), 9),
    }
    if failures:
        validation["failed_periods"] = failures
        manifest["validation"] = validation
        manifest["validation_status"] = "failed"
        _write_manifest(output, manifest)
        periods = sorted({item["period_index"] for item in failures})
        details = "; ".join(
            f"period {item['period_index']}: {item['reason']}" for item in failures[:10]
        )
        raise BaseLoadValidationError(
            "Submission 2 base-load validation failed: the Submission 1 withdrawal is not "
            f"DCOPF-feasible in periods {periods} ({details}); see {output / 'manifest.json'}",
            periods,
        )
    manifest["validation"] = validation
    manifest["validation_status"] = "passed"
    _write_manifest(output, manifest)
    return manifest


_VALIDATION_METHOD = (
    "strict single-period DCOPF of every period with the carried base load; a period that "
    "does not solve is accepted only after a demand change within tolerance_mw at the "
    "withdrawal buses"
)


def _validate_period(
    output: Path,
    period_index: int,
    adjustable_bus_ids: Sequence[str],
    tolerance_mw: float,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return ``(adjustments, failure)`` for one period of the derived artifact."""
    from tools.activsg2000.dcopf import (
        DCOPFInfeasible,
        DCOPFUnresolved,
        _prepared_period_inputs,
        load_prepared_artifact,
        minimum_demand_adjustment,
        solve_dcopf,
    )

    artifact = load_prepared_artifact(str(output.resolve()))
    buses, generators, branches, fixed = _prepared_period_inputs(
        output, artifact, period_index=period_index, validate_artifact=False
    )
    try:
        solve_dcopf(
            buses=buses,
            generators=generators,
            branches=branches,
            fixed_injection_mw_by_bus=fixed,
            base_mva=100.0,
        )
        return [], None
    except (DCOPFInfeasible, DCOPFUnresolved) as exc:
        status = str(exc).rsplit(" ", 1)[-1]
    if not adjustable_bus_ids or tolerance_mw <= 0.0:
        return [], {"period_index": period_index, "reason": status}
    changes = minimum_demand_adjustment(
        buses=buses,
        generators=generators,
        branches=branches,
        adjustable_bus_ids=adjustable_bus_ids,
        fixed_injection_mw_by_bus=fixed,
        base_mva=100.0,
    )
    if changes is None:
        return [], {"period_index": period_index, "reason": f"{status}; no demand change at the withdrawal buses restores feasibility"}
    total = sum(abs(value) for value in changes.values())
    if total > tolerance_mw:
        return [], {
            "period_index": period_index,
            "reason": f"{status}; needs {total:.6g} MW of demand change (> {tolerance_mw:g} MW tolerance)",
        }
    demand = {bus.bus_id: bus.demand_mw for bus in buses}
    adjustments = []
    scale = 10**_DEMAND_DECIMALS
    for bus_id, change in sorted(changes.items()):
        if change < 0.0:
            adjusted = math.floor((demand[bus_id] + change - _BASE_LOAD_ADJUSTMENT_MARGIN_MW) * scale) / scale
        else:
            adjusted = math.ceil((demand[bus_id] + change + _BASE_LOAD_ADJUSTMENT_MARGIN_MW) * scale) / scale
        adjusted = max(0.0, adjusted)
        adjustments.append(
            {
                "period_index": period_index,
                "bus_id": bus_id,
                "change_mw": round(adjusted - demand[bus_id], 9),
                "adjusted_demand_mw": adjusted,
                "solver_status": status,
            }
        )
    return adjustments, None


def _validate_base_load(
    output: Path,
    horizon: int,
    adjustable_bus_ids: Sequence[str],
    *,
    tolerance_mw: float,
    workers: int = 1,
    periods: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from tools.activsg2000.dcopf import clear_prepared_artifact_cache

    clear_prepared_artifact_cache()
    indices = list(range(horizon)) if periods is None else list(periods)
    if workers > 1 and len(indices) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(
                executor.map(
                    lambda index: _validate_period(output, index, adjustable_bus_ids, tolerance_mw),
                    indices,
                )
            )
    else:
        results = [_validate_period(output, index, adjustable_bus_ids, tolerance_mw) for index in indices]
    adjustments = [item for period_adjustments, _ in results for item in period_adjustments]
    failures = [failure for _, failure in results if failure is not None]
    return adjustments, failures


def _write_demand(output: Path, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    with (output / "demand_bus.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _set_network_hashes(output: Path, manifest: dict[str, Any]) -> None:
    files = [name for name in (*_STATIC_FILES, *_OPTIONAL_FILES, "demand_bus.csv") if (output / name).is_file()]
    manifest["network"] = {
        "files": files,
        "sha256": {name: sha256_file(output / name) for name in files},
    }


def _write_manifest(output: Path, manifest: Mapping[str, Any]) -> None:
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
