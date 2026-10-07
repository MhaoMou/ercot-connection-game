"""Validation and field-level diagnostics for the normalized artifact."""

from __future__ import annotations

import math


def validate_network(network: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    for kind in ("nodes", "branches", "plants", "generators"):
        ids = [item.get({"nodes": "node_id", "branches": "branch_id", "plants": "plant_id", "generators": "generator_id"}[kind]) for item in network[kind]]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            errors.append(f"duplicate {kind} IDs: {duplicates[:5]}")
    node_ids = {item["node_id"] for item in network["nodes"]}
    plant_ids = {item["plant_id"] for item in network["plants"]}
    for branch in network["branches"]:
        if branch.get("from_node_id") not in node_ids or branch.get("to_node_id") not in node_ids:
            errors.append(f"unresolved branch endpoint: {branch['branch_id']}")
        geometry = branch.get("geometry", [])
        if len(geometry) < 2:
            errors.append(f"short geometry: {branch['branch_id']}")
        for lon, lat in geometry:
            if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                errors.append(f"invalid coordinate: {branch['branch_id']}")
    for generator in network["generators"]:
        if generator.get("plant_id") not in plant_ids:
            errors.append(f"unresolved generator plant: {generator['generator_id']}")
    for node in network["nodes"]:
        if node.get("latitude") is None or node.get("longitude") is None:
            warnings.append(f"node without coordinates: {node['node_id']}")
    invalid_voltage = [b["branch_id"] for b in network["branches"] if b.get("nominal_kv") is not None and not (0 < b["nominal_kv"] <= 1000)]
    if invalid_voltage:
        warnings.append(f"unusual voltage values: {invalid_voltage[:5]}")
    return {"valid": not errors, "errors": errors, "warnings": warnings}
