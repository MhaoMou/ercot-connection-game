import json
from pathlib import Path

import pytest

from ercot_game.planning_adapter import load_teaching_scenario
from ercot_game.io import plan_from_dict
from ercot_game import practice_server
from ercot_game.cli import _load_scenario


ROOT = Path(__file__).parents[1]
MODEL_PATH = ROOT / "data/processed/ercot_planning_model_v1.json"
TEACHING_PATH = ROOT / "data/teaching/ercot_connection_scenario_v2.json"
REPORT_PATH = ROOT / "docs/ERCOT_PLANNING_MODEL_GATE5.md"


def test_gate5_report_records_compatibility_boundary():
    report = REPORT_PATH.read_text(encoding="utf-8")
    for phrase in (
        "Public Network",
        "Planning Model",
        "Teaching Scenario",
        "existing Evaluator",
        "evaluator mathematics",
        "hard stop",
        "Planning Region",
        "Planning Interface",
    ):
        assert phrase in report


def test_production_planning_model_is_promoted_without_teaching_limits():
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    assert model["model_id"] == "ercot-public-derived-planning"
    assert model["model_version"] == "1.0.0"
    assert model["planning_model_schema"] == "ercot.planning-model.v1"
    assert len(model["planning_nodes"]) == 12
    assert len(model["planning_interfaces"]) == 20
    assert all("teaching_transfer_limit_mw" not in item for item in model["planning_interfaces"])
    assert model["provenance"]["source_candidate"] == "data/processed/reduced/candidate_12_v2.json"


def test_teaching_scenario_matches_model_and_exposes_instructional_calibration():
    scenario = json.loads(TEACHING_PATH.read_text(encoding="utf-8"))
    assert scenario["scenario_schema"] == "ercot.teaching-scenario.v1"
    assert scenario["planning_model"]["model_id"] == "ercot-public-derived-planning"
    assert scenario["planning_model"]["model_version"] == "1.0.0"
    assert len(scenario["planning_regions"]) == 12
    assert len(scenario["planning_interfaces"]) == 20
    assert scenario["calibration"]["deterministic"] is True
    assert scenario["calibration"]["purpose"] == "instructional abstraction"


def test_adapter_emits_existing_evaluator_shape_with_planning_ids():
    scenario = load_teaching_scenario(TEACHING_PATH, MODEL_PATH)
    assert len(scenario.buses) == 12
    assert len(scenario.corridors) == 20
    assert {bus.bus_id for bus in scenario.buses} == {
        item["planning_node_id"] for item in json.loads(MODEL_PATH.read_text())["planning_nodes"]
    }
    assert {corridor.corridor_id for corridor in scenario.corridors} == {
        item["planning_interface_id"] for item in json.loads(MODEL_PATH.read_text())["planning_interfaces"]
    }
    assert scenario.metadata["planning_model_version"] == "1.0.0"


def test_practice_server_default_is_versioned_teaching_scenario():
    default_path = practice_server._default_scenario_path()
    assert default_path == TEACHING_PATH
    scenario = _load_scenario(default_path)
    assert scenario.scenario_id == "ercot-planning-teaching-v2"
    assert len(scenario.buses) == 12


def test_adapter_rejects_mismatched_model_version(tmp_path):
    scenario_payload = json.loads(TEACHING_PATH.read_text(encoding="utf-8"))
    scenario_payload["planning_model"]["model_version"] = "9.9.9"
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="planning model version"):
        load_teaching_scenario(path, MODEL_PATH)


def test_planning_plan_aliases_require_explicit_versions():
    payload = {
        "team_id": "team-a",
        "connections": [{
            "connection_id": "site-a",
            "connection_region_id": "NORTH",
            "planning_interface_ids": [],
            "capacity_mw": 20.0,
            "profile": [20.0] * 6,
        }],
        "generators": [],
        "intervention_budget_k": 0,
        "curtailment_depth_mu": 0.0,
        "flexibility_fee_per_mwh": 0.0,
    }
    with pytest.raises(ValueError, match="planning_model_version"):
        plan_from_dict(payload)
    payload["plan_schema_version"] = "planning-plan.v1"
    payload["planning_model_version"] = "1.0.0"
    plan = plan_from_dict(payload)
    assert plan.connections[0].bus_id == "NORTH"
    assert plan.connections[0].path_corridors == ()
