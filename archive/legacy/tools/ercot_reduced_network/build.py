"""Build candidate geographic planning abstractions from the Gate 2 artifact.

This module deliberately treats public transmission geometries as geographic
evidence only. It never turns endpoint proximity or line intersections into
electrical connectivity.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data/processed/ercot_public_network.json"
DEFAULT_OUTPUT = ROOT / "data/processed/reduced"


def haversine_km(a: list[float], b: list[float]) -> float:
    radius = 6371.0088
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def geometry_length_km(geometry: list[list[float]]) -> float:
    return sum(haversine_km(a, b) for a, b in zip(geometry, geometry[1:]))


def grid_shape(target_count: int) -> tuple[int, int]:
    return {8: (2, 4), 12: (3, 4), 20: (4, 5)}[target_count]


def region_for(point: list[float], bounds: list[float], rows: int, columns: int) -> tuple[int, int]:
    min_lon, min_lat, max_lon, max_lat = bounds
    lon, lat = point
    column = min(columns - 1, max(0, int((lon - min_lon) / (max_lon - min_lon) * columns)))
    row = min(rows - 1, max(0, int((max_lat - lat) / (max_lat - min_lat) * rows)))
    return row, column


def region_id(row: int, column: int, columns: int) -> str:
    return f"R{row + 1:02d}C{column + 1:02d}"


def region_label(row: int, column: int, rows: int, columns: int) -> str:
    vertical = ["North", "North-Central", "Central", "South"] if rows == 4 else ["North", "Central", "South"] if rows == 3 else ["North", "South"]
    horizontal = ["West", "West-Central", "Central", "East", "Gulf"] if columns == 5 else ["West", "West-Central", "Central", "East"]
    return f"{vertical[row]} {horizontal[column]}"


def voltage_class(value: object) -> str:
    try:
        voltage = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(voltage):
        return "unknown"
    if voltage >= 230:
        return "230+ kV"
    if voltage >= 115:
        return "115–229 kV"
    return "below 115 kV"


def line_regions(branch: dict, bounds: list[float], rows: int, columns: int) -> list[tuple[int, int]]:
    seen: list[tuple[int, int]] = []
    for point in branch.get("geometry", []):
        if len(point) != 2:
            continue
        cell = region_for(point, bounds, rows, columns)
        if cell not in seen:
            seen.append(cell)
    return seen


def build_candidate(network: dict, target_count: int) -> dict:
    rows, columns = grid_shape(target_count)
    bounds = network["metadata"]["texas_bbox_wgs84"]
    regions: dict[str, dict] = {}
    for row in range(rows):
        for column in range(columns):
            rid = region_id(row, column, columns)
            regions[rid] = {
                "planning_node_id": rid,
                "label": region_label(row, column, rows, columns),
                "derived": True,
                "grid_position": {"row": row, "column": column},
                "centroid": [
                    bounds[0] + (column + 0.5) * (bounds[2] - bounds[0]) / columns,
                    bounds[3] - (row + 0.5) * (bounds[3] - bounds[1]) / rows,
                ],
                "member_public_resources": {"transmission": [], "plants": [], "generators": []},
                "transmission": {"geometry_count": 0, "length_km": 0.0, "voltage_distribution": {}},
                "generation": {"plant_count": 0, "generator_count": 0, "nameplate_capacity_mw": 0.0, "technology_capacity_mw": {}},
                "provenance": {"method": "deterministic longitude/latitude grid over Gate 2 study bounds", "source_artifact": "data/processed/ercot_public_network.json"},
            }

    interfaces: dict[tuple[str, str], dict] = {}
    assigned_branch_ids: set[str] = set()
    for branch in network["branches"]:
        cells = line_regions(branch, bounds, rows, columns)
        if not cells:
            continue
        branch_id = branch["branch_id"]
        assigned_branch_ids.add(branch_id)
        length = geometry_length_km(branch.get("geometry", []))
        classes = voltage_class(branch.get("nominal_kv"))
        for row, column in cells:
            rid = region_id(row, column, columns)
            region = regions[rid]
            region["member_public_resources"]["transmission"].append(branch_id)
            region["transmission"]["geometry_count"] += 1
            region["transmission"]["length_km"] += length / len(cells)
            distribution = region["transmission"]["voltage_distribution"]
            distribution[classes] = distribution.get(classes, 0) + 1
        for first, second in zip(cells, cells[1:]):
            first_id, second_id = region_id(*first, columns), region_id(*second, columns)
            if first_id == second_id:
                continue
            key = tuple(sorted((first_id, second_id)))
            interface = interfaces.setdefault(key, {"planning_corridor_id": "{}_{}".format(*key), "from_planning_node": key[0], "to_planning_node": key[1], "supporting_public_transmission": [], "public_crossing_count": 0, "public_length_km": 0.0, "voltage_distribution": {"230+ kV": 0, "115–229 kV": 0, "below 115 kV": 0, "unknown": 0}, "teaching_transfer_limit_mw": None, "provenance": {"method": "source geometry traverses two geographic planning cells; not inferred electrical connectivity"}})
            interface["supporting_public_transmission"].append(branch_id)
            interface["public_crossing_count"] += 1
            interface["public_length_km"] += length
            interface["voltage_distribution"][classes] += 1

    plant_region: dict[str, str] = {}
    for plant in network["plants"]:
        if not isinstance(plant.get("longitude"), (int, float)) or not isinstance(plant.get("latitude"), (int, float)):
            continue
        row, column = region_for([plant["longitude"], plant["latitude"]], bounds, rows, columns)
        rid = region_id(row, column, columns)
        plant_region[plant["plant_id"]] = rid
        regions[rid]["member_public_resources"]["plants"].append(plant["plant_id"])
        regions[rid]["generation"]["plant_count"] += 1

    for generator in network["generators"]:
        rid = plant_region.get(generator.get("plant_id"))
        if not rid:
            continue
        region = regions[rid]
        capacity = float(generator.get("nameplate_capacity_mw") or 0)
        region["member_public_resources"]["generators"].append(generator["generator_id"])
        region["generation"]["generator_count"] += 1
        region["generation"]["nameplate_capacity_mw"] += capacity
        technology = generator.get("technology") or "Not reported"
        region["generation"]["technology_capacity_mw"][technology] = region["generation"]["technology_capacity_mw"].get(technology, 0.0) + capacity

    for interface in interfaces.values():
        interface["supporting_public_transmission"] = sorted(set(interface["supporting_public_transmission"]))
        interface["public_length_km"] = round(interface["public_length_km"], 3)
    represented = len(assigned_branch_ids)
    high_voltage = sum(1 for branch in network["branches"] if (branch.get("nominal_kv") or 0) >= 230)
    represented_high_voltage = sum(1 for branch in network["branches"] if branch["branch_id"] in assigned_branch_ids and (branch.get("nominal_kv") or 0) >= 230)
    total_capacity = sum(float(generator.get("nameplate_capacity_mw") or 0) for generator in network["generators"])
    return {
        "schema_version": "gate4.reduced-planning-candidate.v1",
        "candidate_id": f"grid_{target_count:02d}",
        "derived": True,
        "target_region_count": target_count,
        "source_artifact": "data/processed/ercot_public_network.json",
        "method": {"strategy": "hybrid geography + engineering hierarchy", "partition": {"type": "deterministic rectangular grid", "rows": rows, "columns": columns, "bounds_wgs84": bounds}, "topology_policy": "No endpoint merging, line-crossing connectivity, electrical bus identity, impedance, ratings, or MW limits are inferred."},
        "planning_nodes": list(regions.values()),
        "planning_corridors": sorted(interfaces.values(), key=lambda value: value["planning_corridor_id"]),
        "metrics": {"planning_node_count": len(regions), "planning_corridor_count": len(interfaces), "public_transmission_geometry_count": len(network["branches"]), "assigned_transmission_geometry_count": represented, "transmission_representation_fraction": represented / len(network["branches"]), "high_voltage_geometry_count": high_voltage, "assigned_high_voltage_geometry_count": represented_high_voltage, "high_voltage_representation_fraction": represented_high_voltage / high_voltage if high_voltage else None, "generation_capacity_mw": total_capacity, "generation_plant_count": len(network["plants"]), "generation_generator_count": len(network["generators"]), "teaching_transfer_limits_assigned": False},
        "limitations": ["Planning nodes are geographic regions, not ERCOT buses.", "Planning corridors are aggregate geographic interfaces supported by source geometries, not electrical branches.", "Public crossing counts and voltage classes are not thermal transfer capacity.", "Load allocation is not represented; future teaching-scenario assumptions must remain separate."],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    network = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    for target_count in (8, 12, 20):
        candidate = build_candidate(network, target_count)
        path = args.output / f"candidate_{target_count:02d}.json"
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"candidate": candidate["candidate_id"], **candidate["metrics"]}, sort_keys=True))


if __name__ == "__main__":
    main()
