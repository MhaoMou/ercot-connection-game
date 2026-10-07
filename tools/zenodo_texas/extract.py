"""Extract and validate the Texas interconnect from the Zenodo source archive.

The extractor intentionally keeps the source CSV schema and values intact. It
creates a dispatch-source artifact, not a reduced teaching model or an
evaluator input package.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import zipfile
from typing import Iterable


SELECTION_RULE = "interconnect == Texas"
NETWORK_FILES = (
    "bus.csv",
    "branch.csv",
    "sub.csv",
    "bus2sub.csv",
    "plant.csv",
    "gencost.csv",
    "zone.csv",
)
DC_LINE_FILE = "dcline.csv"
PROFILE_FILES = ("demand.csv", "hydro.csv", "solar.csv", "wind.csv")
TIMESTAMP_COLUMNS = ("UTC Time", "UTC")


def _source_path(name: str) -> str:
    return f"base_grid/{name}"


def _read_rows(handle: object) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(handle)  # type: ignore[arg-type]
    if reader.fieldnames is None:
        raise ValueError("source CSV has no header")
    return list(reader.fieldnames), list(reader)


def _write_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_members(archive: zipfile.ZipFile) -> dict[str, str]:
    names = set(archive.namelist())
    missing = [name for name in NETWORK_FILES if _source_path(name) not in names]
    if missing:
        raise ValueError(f"missing required source file(s): {', '.join(missing)}")
    return {name: _source_path(name) for name in NETWORK_FILES}


def _read_csv_from_zip(archive: zipfile.ZipFile, member: str) -> tuple[list[str], list[dict[str, str]]]:
    with archive.open(member) as raw:
        import io

        return _read_rows(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def _filter_rows(
    fieldnames: list[str], rows: list[dict[str, str]], *, file_name: str
) -> list[dict[str, str]]:
    if file_name == DC_LINE_FILE:
        return [
            row
            for row in rows
            if row.get("from_interconnect", "").strip() == "Texas"
            or row.get("to_interconnect", "").strip() == "Texas"
        ]
    if "interconnect" not in fieldnames:
        raise ValueError(f"{file_name} has no interconnect column")
    return [row for row in rows if row.get("interconnect", "").strip() == "Texas"]


def _reference_errors(
    tables: dict[str, list[dict[str, str]]],
    selected_bus_ids: set[str],
    selected_sub_ids: set[str],
    selected_plant_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for row in tables["branch.csv"]:
        for column in ("from_bus_id", "to_bus_id"):
            if row.get(column) not in selected_bus_ids:
                errors.append(f"unresolved branch endpoint: {row.get('branch_id', '?')}:{column}")
    for row in tables["bus2sub.csv"]:
        if row.get("bus_id") not in selected_bus_ids:
            errors.append(f"unresolved bus2sub bus: {row.get('bus_id', '?')}")
        if row.get("sub_id") not in selected_sub_ids:
            errors.append(f"unresolved bus2sub substation: {row.get('sub_id', '?')}")
    for row in tables["plant.csv"]:
        if row.get("bus_id") not in selected_bus_ids:
            errors.append(f"unresolved plant bus: {row.get('plant_id', '?')}:{row.get('bus_id', '?')}")
    for row in tables["gencost.csv"]:
        if row.get("plant_id") not in selected_plant_ids:
            errors.append(f"unresolved gencost plant: {row.get('plant_id', '?')}")
    return errors


def _profile_report(
    archive: zipfile.ZipFile,
    output_dir: Path,
    selected_bus_ids: set[str],
    selected_plant_ids: set[str],
    selected_zone_ids: set[str],
) -> dict[str, dict[str, object]]:
    reports: dict[str, dict[str, object]] = {}
    members = set(archive.namelist())
    for file_name in PROFILE_FILES:
        member = _source_path(file_name)
        if member not in members:
            reports[f"{file_name}"] = {"status": "missing"}
            continue
        with archive.open(member) as raw:
            import io

            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            try:
                header = next(reader)
            except StopIteration:
                reports[file_name] = {"status": "empty"}
                continue
            timestamp_column = next((value for value in TIMESTAMP_COLUMNS if value in header), None)
            columns = [value for value in header if value != timestamp_column]
            matching_buses = sorted(set(columns) & selected_bus_ids) if file_name == "demand.csv" else []
            matching_plants = sorted(set(columns) & selected_plant_ids) if file_name != "demand.csv" else []
            matching_zones = sorted(set(columns) & selected_zone_ids) if file_name == "demand.csv" else []
            row_count = sum(1 for _ in reader)
            if file_name == "demand.csv":
                matching = matching_zones
                identifier_kind = "zone"
            else:
                matching = matching_plants
                identifier_kind = "plant"
            unresolved = sorted(set(columns) - set(matching))
            if timestamp_column is None:
                status = "missing_timestamp_column"
            elif not matching:
                status = "no_resolved_columns"
            elif len(matching) < len(columns):
                status = f"partial_{identifier_kind}_id_coverage"
            else:
                status = "resolved"
            reports[file_name] = {
                "timestamp_column": timestamp_column,
                "column_count": len(columns),
                "selected_column_count": len(matching),
                "row_count": row_count,
                "matching_selected_bus_columns": len(matching_buses),
                "matching_selected_zone_columns": len(matching_zones),
                "matching_selected_plant_columns": len(matching_plants),
                "unresolved_column_count": len(unresolved),
                "unresolved_columns": unresolved[:100],
                "unresolved_columns_truncated": len(unresolved) > 100,
                "status": status,
            }
            if timestamp_column is not None and matching:
                selected_columns = [timestamp_column, *matching]
                with (output_dir / file_name).open("w", newline="", encoding="utf-8") as output:
                    writer = csv.writer(output, lineterminator="\n")
                    writer.writerow(selected_columns)
                    with archive.open(member) as source:
                        source_reader = csv.reader(io.TextIOWrapper(source, encoding="utf-8", newline=""))
                        source_header = next(source_reader)
                        selected_indexes = [source_header.index(column) for column in selected_columns]
                        for source_row in source_reader:
                            writer.writerow(source_row[index] for index in selected_indexes)
    return reports


def extract_archive(archive_path: str | Path, output_dir: str | Path) -> dict[str, object]:
    """Extract Texas source tables and return the generated validation report."""
    archive_path = Path(archive_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, list[dict[str, str]]] = {}
    fieldnames: dict[str, list[str]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        members = _required_members(archive)
        for file_name, member in members.items():
            columns, rows = _read_csv_from_zip(archive, member)
            fieldnames[file_name] = columns
            tables[file_name] = _filter_rows(columns, rows, file_name=file_name)

        if _source_path(DC_LINE_FILE) in archive.namelist():
            columns, rows = _read_csv_from_zip(archive, _source_path(DC_LINE_FILE))
            fieldnames[DC_LINE_FILE] = columns
            tables[DC_LINE_FILE] = _filter_rows(columns, rows, file_name=DC_LINE_FILE)

        selected_bus_ids = {row["bus_id"] for row in tables["bus.csv"]}
        selected_sub_ids = {row["sub_id"] for row in tables["sub.csv"]}
        selected_plant_ids = {row["plant_id"] for row in tables["plant.csv"]}
        selected_zone_ids = {row["zone_id"] for row in tables["zone.csv"]}
        errors = _reference_errors(tables, selected_bus_ids, selected_sub_ids, selected_plant_ids)
        profile_reports = _profile_report(
            archive, output_dir, selected_bus_ids, selected_plant_ids, selected_zone_ids
        )

    for file_name in sorted(tables):
        _write_rows(output_dir / file_name, fieldnames[file_name], tables[file_name])

    files = sorted(path.name for path in output_dir.glob("*.csv"))
    hashes = {file_name: _sha256(output_dir / file_name) for file_name in files}
    dc_lines = tables.get(DC_LINE_FILE, [])
    report: dict[str, object] = {
        "manifest_version": "0.1",
        "selection_rule": SELECTION_RULE,
        "source_archive": archive_path.name,
        "row_counts": {file_name.removesuffix(".csv"): len(tables[file_name]) for file_name in sorted(tables)},
        "files": files,
        "sha256": hashes,
        "errors": errors,
        "warnings": [
            f"{file_name} profile could not be mapped"
            for file_name, profile in profile_reports.items()
            if profile.get("status") in {"missing", "empty", "missing_timestamp_column", "no_resolved_columns"}
        ],
        "valid": not errors,
        "dc_lines": {
            "selected_count": len(dc_lines),
            "cross_interconnect_count": sum(
                row.get("from_interconnect") != row.get("to_interconnect") for row in dc_lines
            ),
        },
        "profiles": profile_reports,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = extract_archive(args.archive, args.output)
    print(json.dumps({"valid": report["valid"], "output": str(args.output)}, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
