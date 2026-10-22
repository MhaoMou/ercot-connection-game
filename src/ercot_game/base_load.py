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


def materialize_base_load_artifact(
    source_artifact: str | Path,
    withdrawal_mw_by_bus: Mapping[str, Sequence[float]],
    output_dir: str | Path,
    *,
    provenance: Mapping[str, Any] | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Write a scenario artifact whose demand is base demand plus withdrawal.

    The source must be a ``demand_bus.csv`` artifact (the representative
    package).  A bus whose total would turn negative (a Submission 1 site
    exporting more than the bus base load) is floored at zero and the floored
    energy is recorded in the manifest.  With ``validate`` every period is
    solved with the single-period DCOPF before the manifest is ``passed``;
    the Submission 1 dispatch already proved feasibility, so a failure here
    indicates an inconsistent input.
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
    with (output / "demand_bus.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)

    files = [name for name in (*_STATIC_FILES, *_OPTIONAL_FILES, "demand_bus.csv") if (output / name).is_file()]
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
            "network": {
                "files": files,
                "sha256": {name: sha256_file(output / name) for name in files},
            },
        }
    )
    _write_manifest(output, manifest)
    if validate:
        from tools.activsg2000.dcopf import clear_prepared_artifact_cache, solve_prepared_period

        clear_prepared_artifact_cache()
        for period_index in range(horizon):
            result = solve_prepared_period(output, period_index=period_index)
            if result.status != "optimal":
                raise ValueError(
                    f"Submission 2 base load is not DCOPF-feasible in period {period_index}: {result.status}"
                )
        manifest["validation"] = {
            "method": "single-period DCOPF of every period with the carried base load",
            "passed_period_count": horizon,
        }
    else:
        manifest["validation"] = {
            "method": "not re-solved; the Submission 1 joint dispatch was feasible with this withdrawal",
        }
    manifest["validation_status"] = "passed"
    _write_manifest(output, manifest)
    return manifest


def _write_manifest(output: Path, manifest: Mapping[str, Any]) -> None:
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
