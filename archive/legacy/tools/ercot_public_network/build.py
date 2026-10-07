"""Build the deterministic Gate 2 canonical and browser public network."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ercot_public_network.geography import TEXAS_BBOX
from tools.ercot_public_network.normalize import normalize_eia, normalize_lines
from tools.ercot_public_network.sources import read_eia_generators, read_eia_plants, read_geojson
from tools.ercot_public_network.topology import build_endpoint_nodes, graph_diagnostics
from tools.ercot_public_network.validate import validate_network


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def geometry_bbox(points: list[list[float]]) -> list[float]:
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/ercot_public_network.json")
    parser.add_argument("--browser-output", type=Path, default=ROOT / "web/data/ercot-public-network.json")
    parser.add_argument("--build-date", default="source-defined", help="Stable metadata value; pass an audit date for a release build.")
    args = parser.parse_args()
    hifld_path = args.raw_dir / "hifld_transmission_lines_texas.geojson"
    eia_path = args.raw_dir / "eia8602025.zip"
    missing = [str(path) for path in (hifld_path, eia_path) if not path.exists()]
    if missing:
        raise SystemExit("Missing required raw source(s): " + ", ".join(missing) + ". Run the documented acquisition commands first.")
    lines, line_stats = normalize_lines(read_geojson(hifld_path))
    plants_raw = read_eia_plants(eia_path)
    generators_raw = read_eia_generators(eia_path)
    plants, generators, eia_stats = normalize_eia(plants_raw, generators_raw)
    nodes = build_endpoint_nodes(lines)
    diagnostics = graph_diagnostics(nodes, lines)
    network = {
        "metadata": {
            "schema_version": "gate2.public-network.v1",
            "build_date": args.build_date,
            "geographic_inclusion": "HIFLD line features intersecting the documented Texas bounding box; EIA plants in TX with balancing authority code ERCO",
            "texas_bbox_wgs84": list(TEXAS_BBOX),
            "transformation": "HIFLD line endpoints become geographic derived_endpoint nodes; no visual crossing is treated as electrical connectivity; EIA plants/generators remain separate",
            "source_checksums": {path.name: sha256(path) for path in (hifld_path, eia_path)},
            "limitations": [
                "This is a public geographic network approximation, not the full ERCOT electrical network.",
                "HIFLD does not establish ERCOT bus identity, branch electrical endpoints, impedance, or ratings.",
                "The Texas bounding box is an inclusion approximation for lines because the public line source has no ERCOT membership field.",
                "EIA generators are not connected to geographic endpoints unless an authoritative source establishes that relationship.",
                "Boundary-crossing source geometries are retained and flagged; clipping-generated nodes are not invented.",
            ],
            "line_ingest": line_stats,
            "eia_ingest": eia_stats,
            "diagnostics": diagnostics,
        },
        "sources": [
            {"source_id": "hifld_transmission_lines", "publisher": "HIFLD / DHS", "url": "https://catalog.data.gov/dataset/electric-power-transmission-lines", "artifact": hifld_path.name, "format": "GeoJSON queried from public ArcGIS FeatureServer", "coverage": "Texas bounding box approximation", "access": "public"},
            {"source_id": "eia860_2025", "publisher": "U.S. Energy Information Administration", "url": "https://www.eia.gov/electricity/data/eia860/index.php", "artifact": eia_path.name, "format": "ZIP containing XLSX", "coverage": "US plants/generators; filtered to TX / ERCO", "access": "public"},
        ],
        "nodes": nodes,
        "branches": lines,
        "plants": plants,
        "generators": generators,
    }
    validation = validate_network(network)
    network["metadata"]["validation"] = validation
    if not validation["valid"]:
        raise SystemExit(json.dumps(validation, indent=2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(network, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    browser = {"metadata": network["metadata"], "sources": network["sources"], "nodes": network["nodes"], "branches": [{**{key: branch[key] for key in ("branch_id", "from_node_id", "to_node_id", "branch_type", "nominal_kv", "geometry", "source_refs", "topology_confidence", "boundary_crossing")}, "bbox": geometry_bbox(branch["geometry"])} for branch in network["branches"]], "plants": network["plants"], "generators": network["generators"]}
    args.browser_output.parent.mkdir(parents=True, exist_ok=True)
    args.browser_output.write_text(json.dumps(browser, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"canonical": str(args.output), "browser": str(args.browser_output), "diagnostics": diagnostics, "validation": validation}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
