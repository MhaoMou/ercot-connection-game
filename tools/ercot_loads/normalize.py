"""Normalize ERCOT native-load workbooks into the game's zone schema."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping
import csv
import hashlib
import json

import openpyxl


ZONE_COLUMNS = {
    "COAST": "307",
    "EAST": "308",
    "FWEST": "301",
    "NORTH": "302",
    "NCENT": "305",
    "SOUTH": "304",
    "SCENT": "306",
    "WEST": "303",
}
OUTPUT_COLUMNS = ("timestamp_utc", *tuple(sorted(ZONE_COLUMNS.values())), "ercot_total_mw")


def _number(value: object, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def normalize_rows(rows: Iterable[Mapping[str, object]], *, year: int) -> list[dict[str, object]]:
    """Convert Hour Ending rows to hour-start rows and Zenodo zone IDs."""
    normalized: list[dict[str, object]] = []
    for row_index, row in enumerate(rows):
        raw_timestamp = row.get("Hour Ending", row.get("HourEnding"))
        if not raw_timestamp:
            raise ValueError("ERCOT workbook must contain an Hour Ending column")
        raw_text = str(raw_timestamp).strip()
        raw_text = raw_text.removesuffix(" DST")
        try:
            if raw_text.endswith(" 24:00"):
                ending = datetime.strptime(raw_text[:-6], "%m/%d/%Y") + timedelta(days=1)
            else:
                ending = datetime.strptime(raw_text, "%m/%d/%Y %H:%M")
        except ValueError as exc:
            raise ValueError(f"invalid Hour Ending value: {raw_timestamp!r}") from exc
        timestamp = ending - timedelta(hours=1)
        if timestamp.year not in (year, year - 1):
            raise ValueError(f"ERCOT row timestamp year {timestamp.year} does not match requested year {year}")
        # ERCOT's historical workbook contains a repeated DST hour and omits
        # the spring-forward hour. Preserve the workbook's 8760-row sequence
        # and assign canonical year timestamps by row order.
        timestamp = datetime(year, 1, 1) + timedelta(hours=row_index)
        timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        zone_values = {
            zone_id: _number(row.get(source_name), source_name)
            for source_name, zone_id in ZONE_COLUMNS.items()
        }
        total = _number(row.get("ERCOT"), "ERCOT")
        if abs(sum(zone_values.values()) - total) > 0.05:
            raise ValueError(f"ERCOT zone total does not match ERCOT total at {timestamp_text}")
        normalized.append({"timestamp_utc": timestamp_text, **zone_values, "ercot_total_mw": total})
    normalized.sort(key=lambda row: row["timestamp_utc"])
    return normalized


def read_workbook(path: str | Path, *, year: int) -> list[dict[str, object]]:
    """Read the single-sheet official ERCOT XLSX archive."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = worksheet.iter_rows(values_only=True)
    try:
        header = tuple(str(value).strip() if value is not None else "" for value in next(rows))
    except StopIteration:
        raise ValueError("ERCOT workbook is empty") from None
    return normalize_rows((dict(zip(header, row, strict=False)) for row in rows), year=year)


def write_normalized_csv(rows: list[dict[str, object]], path: str | Path) -> None:
    """Write normalized wide zone demand and validate the expected year length."""
    if not rows:
        raise ValueError("cannot write an empty ERCOT load series")
    year = int(str(rows[0]["timestamp_utc"])[:4])
    expected = 8784 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 8760
    if len(rows) != expected:
        raise ValueError(f"year {year} must contain {expected} hourly rows, found {len(rows)}")
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_workbook(path: str | Path, output: str | Path, *, year: int) -> dict[str, object]:
    rows = read_workbook(path, year=year)
    write_normalized_csv(rows, output)
    digest = hashlib.sha256(Path(output).read_bytes()).hexdigest()
    return {"year": year, "row_count": len(rows), "columns": list(OUTPUT_COLUMNS), "sha256": digest}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--year", required=True, type=int)
    args = parser.parse_args()
    print(json.dumps(normalize_workbook(args.input, args.output, year=args.year), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
