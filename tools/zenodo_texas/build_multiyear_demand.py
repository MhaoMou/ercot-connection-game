"""Allocate normalized ERCOT zone load to the fixed Zenodo Texas buses."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ZONE_IDS = tuple(str(value) for value in range(301, 309))
STATIC_ARTIFACT_FILES = (
    "bus.csv", "generator_limits.csv", "branch_limits.csv", "dcline.csv",
    "solar.csv", "wind.csv", "hydro.csv",
)


def _read(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header")
        return list(reader.fieldnames), list(reader)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def allocate_zone_loads(
    bus_csv: str | Path,
    normalized_zone_csv: str | Path,
    output_csv: str | Path,
) -> dict[str, object]:
    """Allocate each normalized ERCOT zone row using fixed Zenodo Pd shares."""
    bus_fields, buses = _read(bus_csv)
    for required in ("bus_id", "Pd", "zone_id"):
        if required not in bus_fields:
            raise ValueError(f"bus catalog must contain {required}")
    zone_fields, zone_rows = _read(normalized_zone_csv)
    missing = [zone_id for zone_id in ZONE_IDS if zone_id not in zone_fields]
    if missing:
        raise ValueError(f"normalized ERCOT load is missing zone columns: {', '.join(missing)}")
    if "timestamp_utc" not in zone_fields:
        raise ValueError("normalized ERCOT load must contain timestamp_utc")

    totals = {zone_id: 0.0 for zone_id in ZONE_IDS}
    for row in buses:
        zone_id = str(row["zone_id"])
        if zone_id not in totals:
            raise ValueError(f"bus {row['bus_id']} references unsupported zone {zone_id}")
        totals[zone_id] += float(row["Pd"])
    if any(value <= 0 for value in totals.values()):
        raise ValueError("every Zenodo zone must have positive base Pd")
    shares = {
        row["bus_id"]: float(row["Pd"]) / totals[str(row["zone_id"])]
        for row in buses
    }
    bus_ids = [row["bus_id"] for row in buses]
    bus_zones = {row["bus_id"]: str(row["zone_id"]) for row in buses}
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["UTC Time", *bus_ids])
        for row in zone_rows:
            values = {zone_id: float(row[zone_id]) for zone_id in ZONE_IDS}
            writer.writerow([
                row["timestamp_utc"],
                *[str(values[bus_zones[bus_id]] * shares[bus_id]) for bus_id in bus_ids],
            ])
    return {
        "row_count": len(zone_rows),
        "bus_count": len(buses),
        "zone_count": len(ZONE_IDS),
        "zone_ids": list(ZONE_IDS),
        "allocation_rule": "bus_demand(bus,t) = ercot_zone_load(zone(bus),t) * bus_Pd / sum_zone_Pd",
        "base_pd_by_zone_mw": totals,
        "output_sha256": _sha256(output_path),
    }


def build_year_artifact(
    base_artifact: str | Path,
    normalized_zone_csv: str | Path,
    output_dir: str | Path,
    *,
    year: int,
) -> dict[str, object]:
    """Create a year-specific artifact with shared static tables linked in."""
    base = Path(base_artifact).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename in STATIC_ARTIFACT_FILES:
        source = base / filename
        if not source.is_file():
            raise ValueError(f"base artifact is missing {filename}")
        destination = output / filename
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        destination.symlink_to(source)
    demand_summary = allocate_zone_loads(
        base / "bus.csv",
        normalized_zone_csv,
        output / "demand_bus.csv",
    )
    manifest = {
        "manifest_version": "0.2",
        "year": year,
        "source_artifact": str(base),
        "zone_load_source": str(Path(normalized_zone_csv).resolve()),
        "demand_expansion": demand_summary,
        "static_tables": list(STATIC_ARTIFACT_FILES),
        "timestamp_semantics": "canonical year timestamps assigned in ERCOT workbook row order; DST-marked repeated hours are retained sequentially",
    }
    (output / "multiyear_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-csv", type=Path, help="bus.csv for allocation-only mode")
    parser.add_argument("--zone-load-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--base-artifact",
        type=Path,
        help="base Zenodo artifact; when set, build a complete year artifact with shared static tables",
    )
    parser.add_argument("--year", type=int, help="calendar year for the generated artifact")
    args = parser.parse_args()
    if args.base_artifact is not None:
        if args.year is None:
            parser.error("--year is required with --base-artifact")
        payload = build_year_artifact(
            args.base_artifact,
            args.zone_load_csv,
            args.output,
            year=args.year,
        )
    else:
        if args.bus_csv is None:
            parser.error("--bus-csv is required unless --base-artifact is used")
        if args.year is not None:
            parser.error("--year requires --base-artifact")
        payload = allocate_zone_loads(args.bus_csv, args.zone_load_csv, args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
