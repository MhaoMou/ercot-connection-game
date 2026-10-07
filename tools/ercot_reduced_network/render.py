"""Render analysis-only SVG overlays for Gate 4 candidate inspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import DEFAULT_INPUT, DEFAULT_OUTPUT, grid_shape


def project(point: list[float], bounds: list[float], width: int, height: int) -> tuple[float, float]:
    min_lon, min_lat, max_lon, max_lat = bounds
    return ((point[0] - min_lon) / (max_lon - min_lon) * width, (max_lat - point[1]) / (max_lat - min_lat) * height)


def render(network: dict, candidate: dict, output: Path) -> None:
    width, height = 1000, 620
    bounds = network["metadata"]["texas_bbox_wgs84"]
    rows, columns = grid_shape(candidate["target_region_count"])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Gate 4 {candidate["candidate_id"]} geographic planning abstraction">', '<rect width="1000" height="620" fill="#fff8e8"/>']
    for branch in network["branches"]:
        points = branch.get("geometry", [])
        if len(points) < 2:
            continue
        d = " ".join(("M" if i == 0 else "L") + f"{project(point, bounds, width, height)[0]:.1f},{project(point, bounds, width, height)[1]:.1f}" for i, point in enumerate(points))
        opacity = 0.32 if (branch.get("nominal_kv") or 0) >= 230 else 0.1
        parts.append(f'<path d="{d}" fill="none" stroke="#8d725d" stroke-opacity="{opacity}" stroke-width="0.7"/>')
    for node in candidate["planning_nodes"]:
        row, column = node["grid_position"]["row"], node["grid_position"]["column"]
        x = column * width / columns
        y = row * height / rows
        w, h = width / columns, height / rows
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#5f8d4e" fill-opacity="0.06" stroke="#6f4e37" stroke-width="1.5"/>')
        cx, cy = project(node["centroid"], bounds, width, height)
        parts.append(f'<rect x="{cx - 5:.1f}" y="{cy - 5:.1f}" width="10" height="10" fill="#d99b45" stroke="#46372d" stroke-width="2"/>')
        parts.append(f'<text x="{cx + 8:.1f}" y="{cy + 4:.1f}" font-family="sans-serif" font-size="12" fill="#46372d">{node["planning_node_id"]}</text>')
    centers = {node["planning_node_id"]: project(node["centroid"], bounds, width, height) for node in candidate["planning_nodes"]}
    for corridor in candidate["planning_corridors"]:
        start = centers[corridor["from_planning_node"]]
        end = centers[corridor["to_planning_node"]]
        parts.append(f'<path d="M{start[0]:.1f},{start[1]:.1f} L{end[0]:.1f},{end[1]:.1f}" stroke="#b85450" stroke-width="2" stroke-dasharray="5 4" stroke-opacity="0.7"/>')
    parts.append(f'<text x="18" y="26" font-family="sans-serif" font-size="18" font-weight="700" fill="#46372d">{candidate["candidate_id"]}: {rows}×{columns} geographic planning regions</text>')
    parts.append('<text x="18" y="47" font-family="sans-serif" font-size="12" fill="#765f4f">Public line geometry is context; interfaces are geographic evidence, not inferred electrical branches.</text>')
    parts.append("</svg>")
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    network = json.loads(args.input.read_text(encoding="utf-8"))
    for target_count in (8, 12, 20):
        candidate_path = args.candidates / f"candidate_{target_count:02d}.json"
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        output = args.candidates / f"candidate_{target_count:02d}.svg"
        render(network, candidate, output)
        print(output)


if __name__ == "__main__":
    main()
