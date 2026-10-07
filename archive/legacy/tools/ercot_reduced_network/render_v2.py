"""Generate Gate 4.6 analysis-only overlays for the reconstructed model."""

from __future__ import annotations

import json
from pathlib import Path

from .regionalize import SEEDS

ROOT = Path(__file__).resolve().parents[2]


def project(point, bounds, width=1000, height=620):
    west, south, east, north = bounds
    return ((point[0] - west) / (east - west) * width, (north - point[1]) / (north - south) * height)


def lines(network, bounds, opacity=0.16):
    output = []
    for branch in network["branches"]:
        geometry = branch.get("geometry", [])
        if len(geometry) < 2:
            continue
        d = " ".join(("M" if index == 0 else "L") + "%.1f,%.1f" % project(point, bounds) for index, point in enumerate(geometry))
        output.append(f'<path d="{d}" fill="none" stroke="#6f4e37" stroke-opacity="{opacity}" stroke-width="0.7"/>')
    return output


def cells(candidate, bounds, colors=True):
    palette = ["#5f8d4e", "#d99b45", "#b85450", "#78909c", "#8d6e63", "#9aaa58"]
    output = []
    nodes = {node["planning_node_id"]: node for node in candidate["planning_nodes"]}
    for index, (region_id, _, _, _) in enumerate(SEEDS):
        node = nodes[region_id]
        fill = palette[index % len(palette)] if colors else "#5f8d4e"
        for polygon in node["geometry"]["coordinates"]:
            ring = polygon[0]
            west = min(point[0] for point in ring)
            east = max(point[0] for point in ring)
            south = min(point[1] for point in ring)
            north = max(point[1] for point in ring)
            x, y = project([west, north], bounds)
            x2, y2 = project([east, south], bounds)
            output.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{x2-x:.1f}" height="{y2-y:.1f}" fill="{fill}" fill-opacity="0.13" stroke="#6f4e37" stroke-opacity="0.35" stroke-width="0.6"/>')
    return output


def nodes_and_interfaces(candidate, bounds):
    nodes = {node["planning_node_id"]: node for node in candidate["planning_nodes"]}
    centers = {node_id: project(node["anchor"], bounds) for node_id, node in nodes.items()}
    output = []
    for interface in candidate["planning_interfaces"]:
        start = centers[interface["from_region"]]
        end = centers[interface["to_region"]]
        output.append(f'<path d="M{start[0]:.1f},{start[1]:.1f} L{end[0]:.1f},{end[1]:.1f}" stroke="#b85450" stroke-width="2.5" stroke-dasharray="7 4" stroke-opacity="0.8"/>')
    for node_id, (x, y) in centers.items():
        output.append(f'<rect x="{x-6:.1f}" y="{y-6:.1f}" width="12" height="12" fill="#fff4d6" stroke="#46372d" stroke-width="2"/>')
        output.append(f'<text x="{x+9:.1f}" y="{y+4:.1f}" font-family="sans-serif" font-size="12" fill="#46372d">{node_id}</text>')
    return output


def plants(candidate, network, bounds):
    nodes = {node["planning_node_id"]: node for node in candidate["planning_nodes"]}
    output = []
    for node_id, node in nodes.items():
        x, y = project(node["anchor"], bounds)
        capacity = node["generation"]["nameplate_capacity_mw"]
        radius = 4 + min(12, capacity / 4000)
        output.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="#d99b45" fill-opacity="0.72" stroke="#46372d" stroke-width="1.2"/>')
        output.append(f'<text x="{x+10:.1f}" y="{y+3:.1f}" font-family="sans-serif" font-size="11" fill="#46372d">{node_id} · {capacity:,.0f} MW</text>')
    return output


def write_svg(path, title, body):
    path.write_text('\n'.join(['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 620" role="img" aria-label="%s">' % title, '<rect width="1000" height="620" fill="#fff8e8"/>', '<text x="18" y="26" font-family="sans-serif" font-size="18" font-weight="700" fill="#46372d">%s</text>' % title, '<text x="18" y="47" font-family="sans-serif" font-size="12" fill="#765f4f">Analysis artifact only; public geometry is not electrical topology.</text>', *body, '</svg>']) + '\n', encoding='utf-8')


def main():
    network = json.loads((ROOT / "data/processed/ercot_public_network.json").read_text())
    candidate = json.loads((ROOT / "data/processed/reduced/candidate_12_v2.json").read_text())
    bounds = network["metadata"]["texas_bbox_wgs84"]
    output = ROOT / "data/processed/reduced"
    write_svg(output / "candidate_12_v2_public_regions.svg", "Candidate 12 v2 — public transmission and Texas-constrained regions", lines(network, bounds) + cells(candidate, bounds))
    write_svg(output / "candidate_12_v2_interfaces.svg", "Candidate 12 v2 — planning nodes and public-supported interfaces", lines(network, bounds, 0.08) + cells(candidate, bounds, False) + nodes_and_interfaces(candidate, bounds))
    write_svg(output / "candidate_12_v2_generation.svg", "Candidate 12 v2 — generation geography by planning region", cells(candidate, bounds) + plants(candidate, network, bounds))
    write_svg(output / "candidate_12_v2_vs_rectangular.svg", "Candidate 12 v2 versus rectangular 12-node baseline", cells(candidate, bounds) + nodes_and_interfaces(candidate, bounds))
    print(output)


if __name__ == "__main__":
    main()
