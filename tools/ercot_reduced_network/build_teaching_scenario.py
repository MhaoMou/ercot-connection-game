"""Create the deterministic instructional scenario joined to Gate 5 planning IDs."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .promote import DEFAULT_OUTPUT, promote_candidate


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/teaching/ercot_connection_scenario_v2.json"
PERIOD_MULTIPLIERS = (0.92, 1.00, 1.05, 0.88, 0.96, 1.02)
REGION_MODIFIERS = {
    "HOUSTON_GULF": 0.78,
    "NORTH_CENTRAL": 0.86,
    "NORTHWEST": 0.88,
    "RIO_GRANDE": 0.92,
}
INTERFACE_MODIFIERS = {
    "HIGH_PLAINS__PERMIAN": 0.68,
    "HOUSTON_GULF__NORTH_CENTRAL": 0.72,
    "NORTHWEST__PERMIAN": 0.76,
}


def _region_headroom(node: dict[str, object]) -> float:
    transmission = node["transmission"]
    generation = node["generation"]
    raw = 48.0 + 0.0018 * float(transmission["length_km"]) + 0.00055 * float(generation["nameplate_capacity_mw"])
    return round(raw * REGION_MODIFIERS.get(str(node["planning_node_id"]), 1.0), 2)


def _interface_capacity(interface: dict[str, object]) -> float:
    support = interface["support"]
    raw = 18.0 + 2.8 * math.sqrt(float(support["public_geometry_count"])) + 3.2 * float(support["high_voltage_geometry_count"])
    return round(raw * INTERFACE_MODIFIERS.get(str(interface["planning_interface_id"]), 1.0), 2)


def build_teaching_scenario(model: dict[str, object]) -> dict[str, object]:
    nodes = model["planning_nodes"]
    interfaces = model["planning_interfaces"]
    regions = []
    for node in nodes:
        headroom = _region_headroom(node)
        regions.append(
            {
                "planning_node_id": node["planning_node_id"],
                "label": node["label"],
                "anchor": node["anchor"],
                "geometry": node["geometry"],
                "headroom_mw_by_time": [round(headroom * multiplier, 2) for multiplier in PERIOD_MULTIPLIERS],
                "calibration": {"base_headroom_mw": headroom, "modifier": REGION_MODIFIERS.get(str(node["planning_node_id"]), 1.0)},
            }
        )
    teaching_interfaces = []
    for interface in interfaces:
        capacity = _interface_capacity(interface)
        teaching_interfaces.append(
            {
                "planning_interface_id": interface["planning_interface_id"],
                "from_region": interface["from_region"],
                "to_region": interface["to_region"],
                "capacity_mw_by_time": [round(capacity * multiplier, 2) for multiplier in PERIOD_MULTIPLIERS],
                "calibration": {"base_capacity_mw": capacity, "modifier": INTERFACE_MODIFIERS.get(str(interface["planning_interface_id"]), 1.0)},
            }
        )
    boundary = json.loads((ROOT / "web/texas-boundary.json").read_text(encoding="utf-8"))
    mainland_ring = max((ring for ring in boundary["rings"] if len(ring) >= 3), key=len)
    return {
        "scenario_schema": "ercot.teaching-scenario.v1",
        "scenario_id": "ercot-planning-teaching-v2",
        "scenario_version": "2.0.0",
        "plan_schema_version": "planning-plan.v1",
        "evaluator_version": "0.3.0",
        "planning_model": {"model_id": model["model_id"], "model_version": model["model_version"]},
        "time_step_hours": 1.0,
        "period_labels": ["Period 1", "Period 2", "Period 3", "Period 4", "Period 5", "Period 6"],
        "energy_price_per_mwh": [42.0, 45.0, 51.0, 58.0, 49.0, 40.0],
        "it_value_per_mwh": [118.0, 121.0, 127.0, 135.0, 129.0, 115.0],
        "base_load_mw_by_time": [12.0, 13.0, 14.0, 15.0, 14.0, 12.0],
        "evaluation_config": {"curtailment_cost_per_mwh": 5.0, "unserved_penalty_per_mwh": 500.0, "emergency_energy_cost_per_mwh": 80.0},
        "planning_regions": regions,
        "planning_interfaces": teaching_interfaces,
        "calibration": {
            "deterministic": True,
            "purpose": "instructional abstraction",
            "method": "public transmission geometry and generation evidence set relative scales; explicit modifiers create teachable headroom and bottleneck variation",
            "not_operational_rating": True,
            "source_model": "data/processed/ercot_planning_model_v1.json",
            "period_multipliers": list(PERIOD_MULTIPLIERS),
        },
        "presentation": {
            "map_version": "ercot-planning-model-v1",
            "title": "ERCOT planning model",
            "educational_use_only": True,
            "disclaimer": "Instructional planning abstraction derived from public ERCOT-region evidence; not an operational ERCOT model or interconnection study.",
            "footprint": {"type": "Polygon", "coordinates": [mainland_ring]},
            "zone_labels": [{"zone": node["planning_node_id"], "label": f"{node['label']} planning region"} for node in nodes],
            "legend": {"planning_region": "Instructional geographic planning region", "planning_interface": "Instructional transfer interface", "planning_anchor": "Reference point for a planning region"},
            "tutorial_hints": ["Inspect a planning region to compare instructional headroom across periods.", "Select planning interfaces when a connection depends on shared transfer capacity.", "Use the planning model for teaching decisions; public transmission remains contextual evidence only."],
        },
        "provenance": {"planning_model": "data/processed/ercot_planning_model_v1.json", "gate": "Gate 5", "public_evidence_role": "calibration evidence only"},
    }


def main() -> None:
    model = promote_candidate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_teaching_scenario(model), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
