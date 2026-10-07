"""Join the public planning model to the instructional evaluator scenario."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .io import scenario_from_dict
from .models import Scenario


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _anchor(node: Mapping[str, object]) -> tuple[float, float]:
    point = node.get("anchor")
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError(f"planning region {node.get('planning_node_id')} has invalid anchor")
    return float(point[0]), float(point[1])


def _teaching_payload(scenario: Mapping[str, object], model: Mapping[str, object]) -> dict[str, object]:
    scenario_model = scenario.get("planning_model")
    if not isinstance(scenario_model, Mapping):
        raise ValueError("teaching scenario is missing planning_model reference")
    if scenario_model.get("model_id") != model.get("model_id"):
        raise ValueError("teaching scenario planning model id does not match")
    if scenario_model.get("model_version") != model.get("model_version"):
        raise ValueError("teaching scenario planning model version does not match")

    nodes = {str(node["planning_node_id"]): node for node in model["planning_nodes"]}
    model_interfaces = {str(item["planning_interface_id"]): item for item in model["planning_interfaces"]}
    regions = scenario.get("planning_regions")
    interfaces = scenario.get("planning_interfaces")
    if not isinstance(regions, list) or not isinstance(interfaces, list):
        raise ValueError("teaching scenario must contain planning regions and interfaces")
    if set(nodes) != {str(region["planning_node_id"]) for region in regions}:
        raise ValueError("teaching scenario planning regions do not match model")

    buses: list[dict[str, object]] = []
    for region in regions:
        region_id = str(region["planning_node_id"])
        longitude, latitude = _anchor(nodes[region_id])
        buses.append({
            "bus_id": region_id,
            "headroom_mw_by_time": list(region["headroom_mw_by_time"]),
            "presentation": {
                "longitude": longitude,
                "latitude": latitude,
                "coordinates": [longitude, latitude],
                "zone": region_id,
                "label": region["label"],
                "resource_type": "planning_region",
                "planning_region_id": region_id,
                "public_evidence": {
                    "transmission_geometry_count": nodes[region_id]["transmission"]["geometry_count"],
                    "transmission_length_km": nodes[region_id]["transmission"]["length_km"],
                    "plant_count": nodes[region_id]["generation"]["plant_count"],
                    "generator_count": nodes[region_id]["generation"]["generator_count"],
                    "generation_nameplate_mw": nodes[region_id]["generation"]["nameplate_capacity_mw"],
                },
            },
        })

    corridors: list[dict[str, object]] = []
    for interface in interfaces:
        interface_id = str(interface["planning_interface_id"])
        from_id = str(interface["from_region"])
        to_id = str(interface["to_region"])
        from_point = _anchor(nodes[from_id])
        to_point = _anchor(nodes[to_id])
        corridors.append({
            "corridor_id": interface_id,
            "capacity_mw_by_time": list(interface["capacity_mw_by_time"]),
            "presentation": {
                "path": [list(from_point), list(to_point)],
                "geometry": {"type": "LineString", "coordinates": [list(from_point), list(to_point)]},
                "from_bus_id": from_id,
                "to_bus_id": to_id,
                "from_region": from_id,
                "to_region": to_id,
                "label": interface_id.replace("__", " ↔ "),
                "resource_type": "planning_interface",
                "planning_interface_id": interface_id,
                "public_evidence": model_interfaces[interface_id].get("support", {}),
            },
        })

    presentation = dict(scenario.get("presentation", {}))
    presentation["planning_model"] = dict(scenario_model)
    return {
        "scenario_id": scenario["scenario_id"],
        "evaluator_version": scenario["evaluator_version"],
        "buses": buses,
        "corridors": corridors,
        "energy_price_per_mwh": scenario["energy_price_per_mwh"],
        "it_value_per_mwh": scenario["it_value_per_mwh"],
        "time_step_hours": scenario["time_step_hours"],
        "base_load_mw_by_time": scenario.get("base_load_mw_by_time", []),
        "metadata": {
            "source_description": "Versioned public planning model joined to a deterministic instructional teaching scenario.",
            "planning_model_id": model["model_id"],
            "planning_model_version": model["model_version"],
            "scenario_version": scenario["scenario_version"],
            "plan_schema_version": scenario["plan_schema_version"],
            "calibration": scenario["calibration"],
            "evaluation_config": scenario["evaluation_config"],
        },
        "presentation": presentation,
    }


def load_teaching_scenario(scenario_path: Path, model_path: Path) -> Scenario:
    """Load a version-matched teaching scenario as the existing evaluator Scenario."""
    scenario = _load(scenario_path)
    model = _load(model_path)
    return scenario_from_dict(_teaching_payload(scenario, model))


def load_teaching_payload(scenario_path: Path, model_path: Path) -> dict[str, object]:
    """Return the joined JSON-safe payload for HTTP serialization and audits."""
    return _teaching_payload(_load(scenario_path), _load(model_path))
