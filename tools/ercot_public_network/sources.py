"""Small, dependency-free readers for the Gate 2 public source artifacts."""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_rows(path: Path, member: str) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as outer:
        data = outer.read(member)
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in root.findall(NS + "si"):
                shared.append("".join(node.text or "" for node in item.iter(NS + "t")))
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        for row in sheet.find(NS + "sheetData").findall(NS + "row"):
            values: list[str] = []
            for cell in row.findall(NS + "c"):
                value = cell.find(NS + "v")
                text = value.text if value is not None and value.text is not None else ""
                if cell.get("t") == "s" and text:
                    text = shared[int(text)]
                values.append(text)
            yield values


def _as_float(value: str | None) -> float | None:
    if value in (None, "", "NA", "N/A"):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def read_eia_plants(path: Path) -> list[dict]:
    member = "2___Plant_Y2025.xlsx"
    rows = _xlsx_rows(path, member)
    title = next(rows)
    headers = next(rows)
    index = {name: i for i, name in enumerate(headers)}
    result = []
    for row in rows:
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))
        result.append(
            {
                "plant_id": row[index["Plant Code"]],
                "plant_name": row[index["Plant Name"]],
                "state": row[index["State"]],
                "county": row[index["County"]],
                "latitude": _as_float(row[index["Latitude"]]),
                "longitude": _as_float(row[index["Longitude"]]),
                "balancing_authority_code": row[index["Balancing Authority Code"]],
                "balancing_authority_name": row[index["Balancing Authority Name"]],
                "source_row": row,
            }
        )
    return result


def read_eia_generators(path: Path) -> list[dict]:
    member = "3_1_Generator_Y2025.xlsx"
    rows = _xlsx_rows(path, member)
    next(rows)
    headers = next(rows)
    index = {name: i for i, name in enumerate(headers)}
    result = []
    for row in rows:
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))
        result.append(
            {
                "plant_id": row[index["Plant Code"]],
                "plant_name": row[index["Plant Name"]],
                "generator_id": row[index["Generator ID"]],
                "technology": row[index["Technology"]],
                "prime_mover": row[index["Prime Mover"]],
                "capacity_mw": _as_float(row[index["Nameplate Capacity (MW)"]]),
                "state": row[index["State"]],
                "county": row[index["County"]],
            }
        )
    return result


def read_geojson(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    return data
