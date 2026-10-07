"""Normalize public HIFLD and EIA records without inventing electrical fields."""

from __future__ import annotations

from .geography import clean_line_coordinates, geometry_crosses_bbox, in_texas_bbox
from .topology import stable_id


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def normalize_lines(feature_collection: dict) -> tuple[list[dict], dict]:
    branches = []
    stats = {"source_features": len(feature_collection.get("features", [])), "invalid_geometry": 0, "deduplicated": 0, "boundary_crossing": 0}
    seen = set()
    for feature in feature_collection.get("features", []):
        props = feature.get("properties") or {}
        geometry = clean_line_coordinates(feature.get("geometry") or {})
        if len(geometry) < 2:
            stats["invalid_geometry"] += 1
            continue
        source_id = props.get("ID") or props.get("OBJECTID") or feature.get("id")
        if source_id in seen:
            stats["deduplicated"] += 1
            continue
        seen.add(source_id)
        if not any(in_texas_bbox(p[0], p[1]) for p in geometry):
            continue
        branch_id = stable_id("line", "hifld", source_id)
        crossing = geometry_crosses_bbox(geometry)
        if crossing:
            stats["boundary_crossing"] += 1
        voltage = _number(props.get("VOLTAGE") or props.get("VOLTAGE_KV") or props.get("VOLTAGE1"))
        if voltage is not None and voltage <= 0:
            voltage = None
        branches.append(
            {
                "branch_id": branch_id,
                "from_node_id": None,
                "to_node_id": None,
                "branch_type": "transmission_line",
                "nominal_kv": voltage,
                "geometry": geometry,
                "source_refs": [{"source": "hifld_transmission_lines", "record_id": str(source_id)}],
                "topology_confidence": "unresolved",
                "boundary_crossing": crossing,
                "properties": {key: props.get(key) for key in ("ID", "TYPE", "STATUS", "OWNER", "VOLTAGE", "VOLTAGE1", "VOLTAGE2", "SUB_1", "SUB_2") if key in props},
            }
        )
    branches.sort(key=lambda item: item["branch_id"])
    return branches, stats


def normalize_eia(eia_plants: list[dict], eia_generators: list[dict]) -> tuple[list[dict], list[dict], dict]:
    plants_by_id = {plant["plant_id"]: plant for plant in eia_plants}
    plants = []
    for plant in eia_plants:
        if plant["state"] != "TX" or plant["balancing_authority_code"] != "ERCO":
            continue
        plants.append(
            {
                "plant_id": f"eia_plant_{plant['plant_id']}",
                "name": plant["plant_name"],
                "latitude": plant["latitude"],
                "longitude": plant["longitude"],
                "network_node_id": None,
                "source_refs": [{"source": "eia860_2025", "record_id": plant["plant_id"], "field_scope": "plant"}],
            }
        )
    plants.sort(key=lambda item: item["plant_id"])
    allowed = {plant["plant_id"] for plant in plants}
    generators = []
    for generator in eia_generators:
        parent = f"eia_plant_{generator['plant_id']}"
        if parent not in allowed:
            continue
        generators.append(
            {
                "generator_id": stable_id("gen", "eia860_2025", generator["plant_id"], generator["generator_id"]),
                "plant_id": parent,
                "name": generator["plant_name"],
                "technology": generator["technology"],
                "prime_mover": generator["prime_mover"],
                "nameplate_capacity_mw": generator["capacity_mw"],
                "latitude": None,
                "longitude": None,
                "network_node_id": None,
                "source_refs": [{"source": "eia860_2025", "record_id": f"{generator['plant_id']}:{generator['generator_id']}", "field_scope": "generator"}],
            }
        )
    generators.sort(key=lambda item: item["generator_id"])
    return plants, generators, {"eia_plant_rows": len(eia_plants), "ercot_eia_plants": len(plants), "eia_generator_rows": len(eia_generators), "ercot_eia_generators": len(generators)}
