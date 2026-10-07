"""Gate 4.6 deterministic, Texas-constrained regionalization.

The production candidate uses fixed geographic seeds and a fine Texas-footprint
raster as a lightweight spatially constrained Voronoi partition. Public line
geometry remains evidence only; no electrical connectivity is inferred.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from .build import geometry_length_km, voltage_class


ROOT = Path(__file__).resolve().parents[2]
BOUNDARY_PATH = ROOT / "web/texas-boundary.json"

SEEDS = [
    ("PANHANDLE", "Panhandle", -101.8, 35.4),
    ("HIGH_PLAINS", "High Plains", -102.7, 33.7),
    ("PERMIAN", "Permian Basin", -102.3, 31.6),
    ("NORTHWEST", "Northwest Texas", -104.0, 34.1),
    ("NORTH", "North Texas", -97.4, 33.5),
    ("NORTH_CENTRAL", "North Central Texas", -97.6, 32.1),
    ("EAST", "East Texas", -94.9, 32.3),
    ("WEST_CENTRAL", "West Central Texas", -100.0, 32.0),
    ("CENTRAL_HIGHLANDS", "Central Highlands", -99.0, 30.7),
    ("HOUSTON_GULF", "Houston / Gulf", -95.4, 29.8),
    ("SOUTH_TEXAS", "South Texas", -98.2, 28.4),
    ("RIO_GRANDE", "Rio Grande", -98.5, 26.5),
]


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for first, second in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = first
        x2, y2 = second
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_texas(point: list[float], rings: list[list[list[float]]]) -> bool:
    return any(point_in_ring(point, ring) for ring in rings)


def nearest_seed(point: list[float]) -> str:
    lon, lat = point
    return min(SEEDS, key=lambda seed: ((lon - seed[2]) * math.cos(math.radians(lat))) ** 2 + (lat - seed[3]) ** 2)[0]


def grid_cells(rings: list[list[list[float]]], step: float = 0.1) -> dict[str, list[list[float]]]:
    min_lon = min(point[0] for ring in rings for point in ring)
    max_lon = max(point[0] for ring in rings for point in ring)
    min_lat = min(point[1] for ring in rings for point in ring)
    max_lat = max(point[1] for ring in rings for point in ring)
    cells: dict[str, list[list[float]]] = defaultdict(list)
    lat = min_lat
    while lat < max_lat:
        lon = min_lon
        while lon < max_lon:
            center = [lon + step / 2, lat + step / 2]
            if point_in_texas(center, rings):
                cells[nearest_seed(center)].append([round(lon, 4), round(lat, 4), round(lon + step, 4), round(lat + step, 4)])
            lon += step
        lat += step
    return repair_contiguity(dict(cells), step)


def repair_contiguity(cells: dict[str, list[list[float]]], step: float = 0.1) -> dict[str, list[list[float]]]:
    """Move disconnected non-primary components to adjacent regions deterministically."""
    owner = {(round(cell[0], 4), round(cell[1], 4)): region for region, region_cells in cells.items() for cell in region_cells}
    seed_position = {seed[0]: (seed[2], seed[3]) for seed in SEEDS}
    for region in [seed[0] for seed in SEEDS]:
        members = [key for key, value in owner.items() if value == region]
        remaining = set(members)
        components = []
        while remaining:
            component = {remaining.pop()}
            stack = list(component)
            while stack:
                lon, lat = stack.pop()
                for neighbor in ((round(lon + step, 4), lat), (round(lon - step, 4), lat), (lon, round(lat + step, 4)), (lon, round(lat - step, 4))):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
            components.append(component)
        if len(components) <= 1:
            continue
        components.sort(key=lambda component: (-len(component), min(component)))
        for component in components[1:]:
            adjacent_counts = defaultdict(int)
            for lon, lat in component:
                for neighbor in ((round(lon + step, 4), lat), (round(lon - step, 4), lat), (lon, round(lat + step, 4)), (lon, round(lat - step, 4))):
                    neighbor_region = owner.get(neighbor)
                    if neighbor_region and neighbor_region != region:
                        adjacent_counts[neighbor_region] += 1
            if not adjacent_counts:
                # A one-cell artifact can occur at a narrow boundary sliver;
                # exclude it rather than creating a disconnected planning
                # island. The source geometry remains in the public artifact.
                for cell in component:
                    owner.pop(cell, None)
                continue
            replacement = min(adjacent_counts, key=lambda candidate: (-adjacent_counts[candidate], (seed_position[candidate][0] - sum(point[0] for point in component) / len(component)) ** 2 + (seed_position[candidate][1] - sum(point[1] for point in component) / len(component)) ** 2, candidate))
            for cell in component:
                owner[cell] = replacement
    repaired: dict[str, list[list[float]]] = defaultdict(list)
    for (lon, lat), region in owner.items():
        repaired[region].append([lon, lat, round(lon + step, 4), round(lat + step, 4)])
    return dict(repaired)


def region_for_point(point: list[float], rings: list[list[list[float]]]) -> str | None:
    return nearest_seed(point) if point_in_texas(point, rings) else None


def source_region_sequence(geometry: list[list[float]], rings: list[list[list[float]]]) -> list[str]:
    regions: list[str] = []
    for first, second in zip(geometry, geometry[1:]):
        midpoint = [(first[0] + second[0]) / 2, (first[1] + second[1]) / 2]
        region = region_for_point(midpoint, rings)
        if region and (not regions or regions[-1] != region):
            regions.append(region)
    return regions


def line_region_lengths(geometry: list[list[float]], rings: list[list[list[float]]]) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for first, second in zip(geometry, geometry[1:]):
        midpoint = [(first[0] + second[0]) / 2, (first[1] + second[1]) / 2]
        region = region_for_point(midpoint, rings)
        if region:
            result[region] += geometry_length_km([first, second])
    return dict(result)


def polygon_from_cells(cells: list[list[float]]) -> dict:
    return {"type": "MultiPolygon", "coordinates": [[[[cell[0], cell[1]], [cell[2], cell[1]], [cell[2], cell[3]], [cell[0], cell[3]], [cell[0], cell[1]]]] for cell in cells]}


def build_regional_candidate(network: dict, boundary: dict | None = None) -> dict:
    boundary = boundary or json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    # Use the largest mainland ring for the planning footprint. The bundled
    # boundary also contains a small disconnected coastal/island ring; keeping
    # it as a separate planning island would violate the contiguous-region
    # objective and is not material to this regional planning abstraction.
    rings = [max((ring for ring in boundary["rings"] if len(ring) >= 3), key=len)]
    cells = grid_cells(rings)
    regions = {}
    for region_id, label, lon, lat in SEEDS:
        region_cells = cells.get(region_id, [])
        regions[region_id] = {"planning_node_id": region_id, "label": label, "derived": True, "anchor": [lon, lat], "geometry": polygon_from_cells(region_cells), "cell_count": len(region_cells), "member_public_resources": {"transmission": [], "plants": [], "generators": []}, "transmission": {"geometry_count": 0, "length_km": 0.0, "voltage_distribution": {}}, "generation": {"plant_count": 0, "generator_count": 0, "nameplate_capacity_mw": 0.0, "technology_capacity_mw": {}}, "provenance": {"method": "fixed-seed spatially constrained Voronoi assignment over 0.1-degree cells inside the Texas boundary asset", "source_artifact": "data/processed/ercot_public_network.json", "boundary_asset": "web/texas-boundary.json"}}

    interfaces: dict[tuple[str, str], dict] = {}
    for branch in network["branches"]:
        geometry = branch.get("geometry", [])
        lengths = line_region_lengths(geometry, rings)
        if not lengths:
            continue
        source_regions = list(lengths)
        branch_id = branch["branch_id"]
        for region_id, length in lengths.items():
            node = regions[region_id]
            node["member_public_resources"]["transmission"].append(branch_id)
            node["transmission"]["geometry_count"] += 1
            node["transmission"]["length_km"] += length
            klass = voltage_class(branch.get("nominal_kv"))
            node["transmission"]["voltage_distribution"][klass] = node["transmission"]["voltage_distribution"].get(klass, 0) + 1
        sequence = source_region_sequence(geometry, rings)
        for first, second in zip(sequence, sequence[1:]):
            if first == second or lengths.get(first, 0) < 5 or lengths.get(second, 0) < 5:
                continue
            key = tuple(sorted((first, second)))
            interface = interfaces.setdefault(key, {"planning_interface_id": f"{key[0]}__{key[1]}", "from_region": key[0], "to_region": key[1], "support": {"public_geometry_count": 0, "high_voltage_geometry_count": 0, "voltage_distribution": {"230+ kV": 0, "115–229 kV": 0, "below 115 kV": 0, "unknown": 0}, "source_resource_ids": []}, "teaching_transfer_limit_mw": None, "provenance": {"method": "source geometry has at least 5 km of sampled path in each adjacent geographic region; no electrical connectivity inferred"}})
            if branch_id not in interface["support"]["source_resource_ids"]:
                interface["support"]["source_resource_ids"].append(branch_id)
                interface["support"]["public_geometry_count"] += 1
                klass = voltage_class(branch.get("nominal_kv"))
                interface["support"]["voltage_distribution"][klass] += 1
                if (branch.get("nominal_kv") or 0) >= 230:
                    interface["support"]["high_voltage_geometry_count"] += 1

    for plant in network["plants"]:
        if not isinstance(plant.get("longitude"), (int, float)) or not isinstance(plant.get("latitude"), (int, float)):
            continue
        region_id = region_for_point([plant["longitude"], plant["latitude"]], rings)
        if region_id:
            regions[region_id]["member_public_resources"]["plants"].append(plant["plant_id"])
            regions[region_id]["generation"]["plant_count"] += 1
    plant_region = {plant_id: region_id for region_id, node in regions.items() for plant_id in node["member_public_resources"]["plants"]}
    for generator in network["generators"]:
        region_id = plant_region.get(generator.get("plant_id"))
        if not region_id:
            continue
        capacity = float(generator.get("nameplate_capacity_mw") or 0)
        node = regions[region_id]
        node["member_public_resources"]["generators"].append(generator["generator_id"])
        node["generation"]["generator_count"] += 1
        node["generation"]["nameplate_capacity_mw"] += capacity
        technology = generator.get("technology") or "Not reported"
        node["generation"]["technology_capacity_mw"][technology] = node["generation"]["technology_capacity_mw"].get(technology, 0) + capacity

    for node in regions.values():
        node["transmission"]["length_km"] = round(node["transmission"]["length_km"], 2)
        node["generation"]["nameplate_capacity_mw"] = round(node["generation"]["nameplate_capacity_mw"], 2)
    for interface in interfaces.values():
        interface["support"]["source_resource_ids"].sort()
    return {"schema_version": "gate4.reduced-planning-candidate.v2", "candidate_id": "candidate_12_v2", "derived": True, "target_region_count": 12, "source_artifact": "data/processed/ercot_public_network.json", "method": {"strategy": "hybrid seeded regionalization", "feature_inputs": ["geography and Texas contiguity", "public transmission geometry density", "voltage class", "EIA generation geography and technology"], "feature_normalization": "geography is the hard assignment constraint; public evidence is summarized after assignment and does not override spatial coherence", "seed_configuration": [[region_id, label, lon, lat] for region_id, label, lon, lat in SEEDS], "grid_resolution_degrees": 0.1, "interface_minimum_path_km_per_region": 5, "contiguity_repair": "disconnected non-primary raster components are reassigned to the adjacent region with the strongest shared edge, then nearest-seed tie break", "topology_policy": "No endpoint merging, line-crossing connectivity, electrical bus identity, impedance, ratings, or MW limits are inferred."}, "planning_nodes": list(regions.values()), "planning_interfaces": sorted(interfaces.values(), key=lambda value: value["planning_interface_id"]), "metrics": {"planning_node_count": 12, "planning_interface_count": len(interfaces), "footprint": "largest mainland ring from Texas boundary asset; not an ERCOT boundary", "teaching_transfer_limits_assigned": False}, "limitations": ["The Texas boundary is a geographic constraint, not an official ERCOT footprint.", "The boundary asset's small disconnected coastal/island ring is excluded from the contiguous mainland planning footprint.", "The 0.1-degree raster is a reproducibility device; boundaries are not official zones.", "Public crossing evidence is not electrical connectivity or thermal capacity.", "Load allocation remains a future teaching-scenario assumption."]}


def main() -> None:
    input_path = ROOT / "data/processed/ercot_public_network.json"
    output_path = ROOT / "data/processed/reduced/candidate_12_v2.json"
    network = json.loads(input_path.read_text(encoding="utf-8"))
    output_path.write_text(json.dumps(build_regional_candidate(network), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
