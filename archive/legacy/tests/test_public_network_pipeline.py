import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ercot_public_network.geography import clean_line_coordinates
from tools.ercot_public_network.normalize import normalize_lines
from tools.ercot_public_network.topology import build_endpoint_nodes, graph_diagnostics, stable_id
from tools.ercot_public_network.validate import validate_network


def feature(source_id, coordinates, voltage=138):
    return {
        "type": "Feature",
        "properties": {"ID": source_id, "VOLTAGE": voltage},
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def test_line_crossing_does_not_create_electrical_connectivity():
    collection = {
        "type": "FeatureCollection",
        "features": [
            feature("horizontal", [[-100, 30], [-99, 30]]),
            feature("vertical", [[-99.5, 29.5], [-99.5, 30.5]]),
        ],
    }
    branches, _ = normalize_lines(collection)
    nodes = build_endpoint_nodes(branches)
    diagnostics = graph_diagnostics(nodes, branches)
    assert diagnostics["branch_count"] == 2
    assert diagnostics["connected_component_count"] == 2
    assert diagnostics["spatially_merged_endpoint_count"] == 0


def test_duplicate_source_records_are_removed_and_ids_are_stable():
    collection = {"type": "FeatureCollection", "features": [feature("same", [[-100, 30], [-99, 30]]), feature("same", [[-100, 30], [-99, 30]])]}
    branches, stats = normalize_lines(collection)
    assert len(branches) == 1
    assert stats["deduplicated"] == 1
    assert branches[0]["branch_id"] == stable_id("line", "hifld", "same")


def test_invalid_geometry_and_coordinates_are_reported():
    assert clean_line_coordinates({"type": "LineString", "coordinates": [[-100, 30], [float("nan"), 30]]}) == [[-100.0, 30.0]]
    collection = {"type": "FeatureCollection", "features": [feature("short", [[-100, 30]])]}
    branches, stats = normalize_lines(collection)
    assert branches == []
    assert stats["invalid_geometry"] == 1


def test_outside_boundary_is_not_silently_included():
    collection = {"type": "FeatureCollection", "features": [feature("outside", [[-120, 40], [-119, 40]])]}
    branches, _ = normalize_lines(collection)
    assert branches == []


def test_provenance_and_unresolved_electrical_connection_are_preserved():
    branches, _ = normalize_lines({"type": "FeatureCollection", "features": [feature("one", [[-100, 30], [-99, 30]], voltage=-999999)]})
    nodes = build_endpoint_nodes(branches)
    network = {"nodes": nodes, "branches": branches, "plants": [], "generators": []}
    assert branches[0]["nominal_kv"] is None
    assert branches[0]["source_refs"][0]["source"] == "hifld_transmission_lines"
    assert branches[0]["topology_confidence"] == "source_endpoint"
    assert validate_network(network)["valid"] is True
