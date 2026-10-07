import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ercot_reduced_network.audit import candidate_audit
from tools.ercot_reduced_network.build import build_candidate


ROOT = Path(__file__).resolve().parents[1]


def load_network():
    return json.loads((ROOT / "data/processed/ercot_public_network.json").read_text(encoding="utf-8"))


def test_candidate_scales_are_deterministic_and_topology_conservative():
    network = load_network()
    first = build_candidate(network, 8)
    second = build_candidate(network, 8)
    assert first == second
    assert first["metrics"]["planning_node_count"] == 8
    assert first["metrics"]["teaching_transfer_limits_assigned"] is False
    assert all(node["planning_node_id"].startswith("R") for node in first["planning_nodes"])
    assert all("ERCOT bus" not in node["label"] for node in first["planning_nodes"])


def test_candidate_preserves_public_resource_mappings_and_generation_totals():
    network = load_network()
    candidate = build_candidate(network, 12)
    transmission_ids = {branch["branch_id"] for branch in network["branches"]}
    mapped_ids = {item for node in candidate["planning_nodes"] for item in node["member_public_resources"]["transmission"]}
    assert mapped_ids == transmission_ids
    assert candidate["metrics"]["transmission_representation_fraction"] == 1.0
    assert sum(node["generation"]["generator_count"] for node in candidate["planning_nodes"]) == len(network["generators"])
    assert sum(node["generation"]["plant_count"] for node in candidate["planning_nodes"]) == len(network["plants"])


def test_interfaces_are_supported_by_source_geometry_and_do_not_claim_mw():
    candidate = build_candidate(load_network(), 20)
    assert candidate["planning_corridors"]
    for corridor in candidate["planning_corridors"]:
        assert corridor["public_crossing_count"] > 0
        assert corridor["supporting_public_transmission"]
        assert corridor["teaching_transfer_limit_mw"] is None
        assert "not inferred electrical connectivity" in corridor["provenance"]["method"]


def test_gate45_audit_reports_reconstructed_candidate_without_structural_failures():
    network = load_network()
    from tools.ercot_reduced_network.regionalize import SEEDS, build_regional_candidate

    audit = candidate_audit(network, build_regional_candidate(network))
    assert audit["planning_node_count"] == 12
    assert audit["public_transmission_geometries_unassigned"] > 0
    assert audit["plants_assigned"] >= len(network["plants"]) - 5
    assert audit["generators_assigned"] <= len(network["generators"])
    assert audit["weak_interfaces"] == []
    assert audit["zero_transmission_density_nodes"] == 0
    assert all(value == 1 for value in audit["region_component_counts"].values())
    assert audit["generation_capacity_imbalance_ratio"] < 20


def test_reconstructed_candidate_has_stable_geographic_ids_and_interface_provenance():
    from tools.ercot_reduced_network.regionalize import SEEDS, build_regional_candidate

    network = load_network()
    first = build_regional_candidate(network)
    second = build_regional_candidate(network)
    assert first == second
    assert [node["planning_node_id"] for node in first["planning_nodes"]] == [seed[0] for seed in SEEDS]
    assert all(node["cell_count"] > 0 for node in first["planning_nodes"])
    assert all(interface["teaching_transfer_limit_mw"] is None for interface in first["planning_interfaces"])
    assert all(interface["support"]["source_resource_ids"] for interface in first["planning_interfaces"])
    assert all("electrical connectivity" in interface["provenance"]["method"] for interface in first["planning_interfaces"])
