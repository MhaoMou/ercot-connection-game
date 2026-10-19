"""Build an approximate geographic bus layout for the ACTIVSg2000 grid map.

The released scenario package has no coordinates. The June 2016 ACTIVSg2000
release (Texas A&M Electric Grid Test Cases) lists substation latitude and
longitude in its PowerWorld ``.AUX`` file, and the MATPOWER copy of the current
case names every bus ``"<CITY> <substation index> <bus index>"``. This tool
matches each current bus to a 2016 substation by normalized name, falls back
to the mean of that city's substations, and places any remaining bus at the
mean position of its already-placed neighbors. Positions are approximate.

Inputs are downloaded separately (they are not redistributed here):

* ``--aux``: ``Texas2000_June2016.AUX`` from the 2016 release archive
  (https://electricgrids.engr.tamu.edu/electric-grid-test-cases/activsg2000/).
* ``--matpower-case``: ``case_ACTIVSg2000.m`` from MATPOWER
  (https://github.com/MATPOWER/matpower/blob/master/data/case_ACTIVSg2000.m).
* ``--boundary-geojson``: a US states GeoJSON with a ``Texas`` feature, e.g.
  https://github.com/PublicaMundi/MappingAPI (data/geojson/us-states.json,
  derived from US Census boundaries).

The output uses the grid-map layout format (``positions`` in the unit square)
plus a ``background_paths`` outline in the same projected coordinates.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shlex
from collections import defaultdict
from pathlib import Path

LAYOUT_VERSION = "activsg2000-geographic-layout-v1"


def _normalize(name: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", "", name.upper().replace("'", "")).replace("  ", " ").strip()


def _city(key: str) -> str:
    tokens = key.split()
    return " ".join(tokens[:-1]) if len(tokens) > 1 and tokens[-1].isdigit() else key


def read_substations(aux_path: Path) -> dict[str, tuple[float, float]]:
    text = aux_path.read_text(encoding="latin-1")
    match = re.search(r"DATA \(Substation, \[(.*?)\]\)\s*\{(.*?)\n\}", text, re.S)
    if match is None:
        raise ValueError("no Substation table in AUX file")
    fields = [field.strip() for field in match.group(1).replace("\n", " ").split(",")]
    name_i, lat_i, lon_i = fields.index("SubName"), fields.index("Latitude"), fields.index("Longitude")
    substations = {}
    for line in match.group(2).strip().splitlines():
        if not line.strip() or line.strip().startswith("//"):
            continue
        row = shlex.split(line)
        substations[_normalize(row[name_i])] = (float(row[lat_i]), float(row[lon_i]))
    return substations


def read_matpower_bus_names(case_path: Path) -> dict[str, str]:
    text = case_path.read_text(encoding="utf-8")
    bus_block = re.search(r"mpc\.bus = \[(.*?)\];", text, re.S).group(1)
    ids = [line.split()[0] for line in bus_block.strip().splitlines() if line.strip() and not line.strip().startswith("%")]
    names = re.findall(r"'([^']*)';", re.search(r"mpc\.bus_name = \{(.*?)\};", text, re.S).group(1))
    if len(ids) != len(names):
        raise ValueError("bus and bus_name lengths differ")
    return dict(zip(ids, names))


def read_texas_outline(geojson_path: Path) -> list[list[tuple[float, float]]]:
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    feature = next(f for f in data["features"] if f["properties"].get("name") == "Texas")
    geometry = feature["geometry"]
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [[(lat, lon) for lon, lat in polygon[0]] for polygon in polygons]


def build_layout(artifact_dir: Path, aux: Path, matpower_case: Path, boundary_geojson: Path) -> dict:
    with (artifact_dir / "bus.csv").open(newline="", encoding="utf-8") as handle:
        bus_ids = [row["bus_id"] for row in csv.DictReader(handle)]
    with (artifact_dir / "branch_limits.csv").open(newline="", encoding="utf-8") as handle:
        edges = [(row["from_bus_id"], row["to_bus_id"]) for row in csv.DictReader(handle)]
    substations = read_substations(aux)
    names = read_matpower_bus_names(matpower_case)
    by_city: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for key, coordinate in substations.items():
        by_city[_city(key)].append(coordinate)

    latlon: dict[str, tuple[float, float]] = {}
    method = {"substation": 0, "city": 0, "neighbors": 0}
    for bus_id in bus_ids:
        key = _normalize(" ".join(names[bus_id].split()[:-1]))
        if key in substations:
            latlon[bus_id] = substations[key]
            method["substation"] += 1
        elif _city(key) in by_city:
            points = by_city[_city(key)]
            latlon[bus_id] = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
            method["city"] += 1
    neighbors: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        neighbors[a].add(b)
        neighbors[b].add(a)
    pending = [bus_id for bus_id in bus_ids if bus_id not in latlon]
    while pending:
        progress = []
        for bus_id in pending:
            placed = [latlon[n] for n in neighbors[bus_id] if n in latlon]
            if placed:
                progress.append((bus_id, (sum(p[0] for p in placed) / len(placed), sum(p[1] for p in placed) / len(placed))))
        if not progress:
            raise ValueError(f"{len(pending)} buses cannot be placed")
        for bus_id, coordinate in progress:
            latlon[bus_id] = coordinate
            method["neighbors"] += 1
        pending = [bus_id for bus_id in pending if bus_id not in latlon]

    outline = read_texas_outline(boundary_geojson)
    lat0 = math.radians(31.0)

    def project(lat: float, lon: float) -> tuple[float, float]:
        return lon * math.cos(lat0), -lat

    projected = {bus_id: project(*coordinate) for bus_id, coordinate in latlon.items()}
    outline_xy = [[project(lat, lon) for lat, lon in polygon] for polygon in outline]
    xs = [p[0] for p in projected.values()] + [p[0] for poly in outline_xy for p in poly]
    ys = [p[1] for p in projected.values()] + [p[1] for poly in outline_xy for p in poly]
    x0, y0, scale = min(xs), min(ys), max(max(xs) - min(xs), max(ys) - min(ys))

    def normalize(point: tuple[float, float]) -> list[float]:
        return [round((point[0] - x0) / scale, 5), round((point[1] - y0) / scale, 5)]

    return {
        "layout_version": LAYOUT_VERSION,
        "positions": {bus_id: normalize(point) for bus_id, point in projected.items()},
        "background_paths": [[normalize(point) for point in polygon] for polygon in outline_xy],
        "provenance": {
            "kind": "approximate geographic",
            "substation_coordinates": "ACTIVSg2000 June 2016 release (Texas A&M), Substation table of Texas2000_June2016.AUX",
            "bus_names": "MATPOWER case_ACTIVSg2000.m bus_name",
            "boundary": "Texas outline from US states GeoJSON (US Census-derived)",
            "projection": "equirectangular, cos(31 deg) longitude scaling",
            "placement_counts": method,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/processed/activsg2000_scenarios_v2_6h/2028/jan_jun"))
    parser.add_argument("--aux", type=Path, required=True)
    parser.add_argument("--matpower-case", type=Path, required=True)
    parser.add_argument("--boundary-geojson", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/teaching/activsg2000_geo_layout_v1.json"))
    args = parser.parse_args()
    layout = build_layout(args.artifact_dir, args.aux, args.matpower_case, args.boundary_geojson)
    args.output.write_text(json.dumps(layout, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output, layout["provenance"]["placement_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
