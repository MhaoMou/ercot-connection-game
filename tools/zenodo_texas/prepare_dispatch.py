"""Prepare bus-level demand and normalized dispatch limits from extracted tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


TIMESTAMP_COLUMNS = frozenset({"UTC", "UTC Time"})


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path.name} has no header")
        return list(reader.fieldnames), list(reader)


def _write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _number(value: str, *, field: str, row_id: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric for {row_id}") from exc


def _format(value: float) -> str:
    return str(float(value))


def _read_profile(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    fieldnames, rows = _read(path)
    if len(fieldnames) < 2:
        raise ValueError(f"{path.name} must contain a timestamp and at least one generator column")
    return fieldnames, rows


def _prepare_renewable_profiles(
    root: Path,
    output_dir: Path,
    demand_timestamps: tuple[str, ...],
    demand_timestamp_column: str,
) -> dict[str, object]:
    summaries: dict[str, object] = {}
    for filename in ("solar.csv", "wind.csv", "hydro.csv"):
        source = root / filename
        if not source.exists():
            continue
        fieldnames, rows = _read_profile(source)
        if len(rows) != len(demand_timestamps):
            raise ValueError(
                f"{filename} row count {len(rows)} does not match demand row count "
                f"{len(demand_timestamps)}"
            )
        timestamp_column = fieldnames[0]
        if timestamp_column not in TIMESTAMP_COLUMNS:
            raise ValueError(
                f"{filename} first column must be a recognized timestamp column "
                f"(UTC or UTC Time), got {timestamp_column!r}"
            )
        normalized_rows: list[dict[str, str]] = []
        for row_number, (row, expected_timestamp) in enumerate(
            zip(rows, demand_timestamps, strict=True), start=2
        ):
            timestamp = row.get(timestamp_column)
            if timestamp != expected_timestamp:
                raise ValueError(
                    f"{filename} timestamp mismatch at row {row_number}: "
                    f"expected {expected_timestamp!r}, got {timestamp!r}"
                )
            normalized = {timestamp_column: expected_timestamp}
            for generator_id in fieldnames[1:]:
                value = _number(row.get(generator_id), field=generator_id, row_id=str(row_number))
                if not math.isfinite(value) or value < 0:
                    raise ValueError(
                        f"{filename} profile value for {generator_id} must be finite and non-negative"
                    )
                normalized[generator_id] = _format(value)
            normalized_rows.append(normalized)
        _write(output_dir / filename, fieldnames, normalized_rows)
        summaries[filename] = {
            "timestamp_column": timestamp_column,
            "demand_timestamp_column": demand_timestamp_column,
            "timestamp_alignment": "exact row-wise match",
            "value_units": "MW",
            "row_count": len(rows),
            "generator_count": len(fieldnames) - 1,
        }
    return summaries


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expand_demand(root: Path, output: Path) -> dict[str, object]:
    _, buses = _read(root / "bus.csv")
    _, zones = _read(root / "zone.csv")
    demand_header, _ = _read(root / "demand.csv")
    with (root / "demand.csv").open(newline="", encoding="utf-8") as handle:
        demand_reader = csv.DictReader(handle)
        if demand_reader.fieldnames is None:
            raise ValueError("demand.csv has no header")
        timestamp_column = demand_reader.fieldnames[0]
        demand_rows = list(demand_reader)

    zone_ids = {row["zone_id"] for row in zones}
    bus_ids = [row["bus_id"] for row in buses]
    zone_total_pd: dict[str, float] = {zone_id: 0.0 for zone_id in zone_ids}
    for row in buses:
        zone_id = row["zone_id"]
        if zone_id not in zone_total_pd:
            raise ValueError(f"bus {row['bus_id']} references unknown zone {zone_id}")
        zone_total_pd[zone_id] += _number(row["Pd"], field="Pd", row_id=row["bus_id"])
    zero_pd = sorted(zone_id for zone_id, total in zone_total_pd.items() if total <= 0)
    if zero_pd:
        raise ValueError(f"zero base Pd for zone(s): {', '.join(zero_pd)}")

    shares = {
        row["bus_id"]: _number(row["Pd"], field="Pd", row_id=row["bus_id"])
        / zone_total_pd[row["zone_id"]]
        for row in buses
    }
    bus_zone_by_id = {row["bus_id"]: row["zone_id"] for row in buses}
    zone_column_ids = sorted(zone_ids)
    missing_zone_columns = [zone_id for zone_id in zone_column_ids if zone_id not in demand_header]
    if missing_zone_columns:
        raise ValueError(f"demand.csv is missing zone column(s): {', '.join(missing_zone_columns)}")

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([timestamp_column, *bus_ids])
        for row in demand_rows:
            zone_values = {
                zone_id: _number(row[zone_id], field=f"demand[{zone_id}]", row_id=row[timestamp_column])
                for zone_id in zone_column_ids
            }
            writer.writerow(
                [
                    row[timestamp_column],
                    *(_format(zone_values[bus_zone_by_id[bus_id]] * shares[bus_id]) for bus_id in bus_ids),
                ]
            )
    return {
        "timestamp_column": timestamp_column,
        "row_count": len(demand_rows),
        "zone_count": len(zone_ids),
        "bus_count": len(buses),
        "zone_ids": zone_column_ids,
        "allocation_rule": "bus_demand(bus,t) = zone_demand(zone(bus),t) * bus_Pd / sum_zone_Pd",
        "base_pd_total_mw": sum(zone_total_pd.values()),
    }


def _write_normalized_limits(root: Path, output_dir: Path) -> tuple[int, int]:
    _, plants = _read(root / "plant.csv")
    _, costs = _read(root / "gencost.csv")
    cost_by_plant = {row["plant_id"]: row for row in costs}
    generator_rows: list[dict[str, str]] = []
    for row in plants:
        cost = cost_by_plant.get(row["plant_id"], {})
        generator_rows.append(
            {
                "generator_id": row["plant_id"],
                "bus_id": row["bus_id"],
                "p_min_mw": _format(_number(row["Pmin"], field="Pmin", row_id=row["plant_id"])),
                "p_max_mw": _format(_number(row["Pmax"], field="Pmax", row_id=row["plant_id"])),
                "q_min_mvar": _format(_number(row["Qmin"], field="Qmin", row_id=row["plant_id"])),
                "q_max_mvar": _format(_number(row["Qmax"], field="Qmax", row_id=row["plant_id"])),
                "ramp_10_mw_per_10min": _format(_number(row["ramp_10"], field="ramp_10", row_id=row["plant_id"])),
                "status": row["status"],
                "technology": row["type"],
                "marginal_cost_c2_per_mw2h": _format(_number(cost.get("c2", "0"), field="c2", row_id=row["plant_id"])),
                "marginal_cost_c1_per_mwh": _format(_number(cost.get("c1", "0"), field="c1", row_id=row["plant_id"])),
                "marginal_cost_c0_per_h": _format(_number(cost.get("c0", "0"), field="c0", row_id=row["plant_id"])),
            }
        )
    _write(output_dir / "generator_limits.csv", list(generator_rows[0]), generator_rows)

    _, branches = _read(root / "branch.csv")
    branch_rows = [
        {
            "branch_id": row["branch_id"],
            "from_bus_id": row["from_bus_id"],
            "to_bus_id": row["to_bus_id"],
            "thermal_limit_mva": _format(_number(row["rateA"], field="rateA", row_id=row["branch_id"])),
            "status": row["status"],
            "resistance_pu": row["r"],
            "reactance_pu": row["x"],
            "charging_susceptance_pu": row["b"],
            "device_type": row["branch_device_type"],
        }
        for row in branches
    ]
    _write(output_dir / "branch_limits.csv", list(branch_rows[0]), branch_rows)
    return len(generator_rows), len(branch_rows)


def prepare_dispatch_source(extracted_dir: str | Path, output_dir: str | Path | None = None) -> dict[str, object]:
    """Create bus-level demand and normalized dispatch limit tables."""
    root = Path(extracted_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    demand_summary = _expand_demand(root, output / "demand_bus.csv")
    demand_header, demand_rows = _read(root / "demand.csv")
    demand_timestamps = tuple(row[demand_header[0]] for row in demand_rows)
    renewable_profiles = _prepare_renewable_profiles(
        root,
        output,
        demand_timestamps,
        demand_header[0],
    )
    generator_count, branch_count = _write_normalized_limits(root, output)
    files = sorted(path.name for path in output.glob("*.csv"))
    manifest: dict[str, object] = {
        "manifest_version": "0.1",
        "source_artifact": str(root),
        "demand_expansion": demand_summary,
        "renewable_profiles": renewable_profiles,
        "generator_count": generator_count,
        "branch_count": branch_count,
        "units": {
            "demand_bus": "MW",
            "generator_limits": {
                "p_min": "MW",
                "p_max": "MW",
                "q_min": "MVAr",
                "q_max": "MVAr",
                "ramp_10": "MW per 10 minutes",
                "marginal_cost_c2": "currency per MW^2-hour",
                "marginal_cost_c1": "currency per MWh",
                "marginal_cost_c0": "currency per hour",
            },
            "branch_limits": {
                "thermal_limit": "MVA",
                "r": "per unit",
                "x": "per unit",
                "b": "per unit",
            },
        },
        "files": files,
        "sha256": {name: _sha256(output / name) for name in files},
    }
    (output / "dispatch_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = prepare_dispatch_source(args.input, args.output)
    print(json.dumps({"output": str(args.output or args.input), "bus_count": manifest["demand_expansion"]["bus_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
