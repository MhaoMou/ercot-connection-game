"""Conservative geographic topology construction.

HIFLD line geometry does not establish electrical endpoint connectivity. The
pipeline therefore creates one geographic node per source line endpoint and
does not merge visually crossing lines. Endpoint spatial merging is disabled
by default and is exposed only as an explicit future option.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict


def stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def endpoint_node_id(branch_id: str, endpoint: str) -> str:
    return stable_id("geo", branch_id, endpoint)


def build_endpoint_nodes(branches: list[dict]) -> list[dict]:
    nodes = []
    for branch in branches:
        geometry = branch["geometry"]
        if len(geometry) < 2:
            continue
        for endpoint, point in (("from", geometry[0]), ("to", geometry[-1])):
            node_id = endpoint_node_id(branch["branch_id"], endpoint)
            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": "derived_endpoint",
                    "name": None,
                    "latitude": point[1],
                    "longitude": point[0],
                    "nominal_kv": branch.get("nominal_kv"),
                    "source_refs": branch["source_refs"],
                    "topology_confidence": "source_endpoint",
                }
            )
        branch["from_node_id"] = endpoint_node_id(branch["branch_id"], "from")
        branch["to_node_id"] = endpoint_node_id(branch["branch_id"], "to")
        branch["topology_confidence"] = "source_endpoint"
    return nodes


def graph_diagnostics(nodes: list[dict], branches: list[dict]) -> dict:
    adjacency = defaultdict(set)
    for node in nodes:
        adjacency[node["node_id"]]
    for branch in branches:
        a, b = branch.get("from_node_id"), branch.get("to_node_id")
        if a and b:
            adjacency[a].add(b)
            adjacency[b].add(a)
    seen = set()
    component_sizes = []
    for node_id in sorted(adjacency):
        if node_id in seen:
            continue
        stack = [node_id]
        seen.add(node_id)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        component_sizes.append(size)
    degrees = sorted(len(neighbors) for neighbors in adjacency.values())
    return {
        "node_count": len(nodes),
        "branch_count": len(branches),
        "connected_component_count": len(component_sizes),
        "largest_component_node_count": max(component_sizes, default=0),
        "isolated_node_count": sum(1 for degree in degrees if degree == 0),
        "degree_min": min(degrees, default=0),
        "degree_max": max(degrees, default=0),
        "degree_mean": round(sum(degrees) / len(degrees), 4) if degrees else 0,
        "spatially_merged_endpoint_count": 0,
        "boundary_derived_node_count": 0,
        "unresolved_endpoint_count": 0,
    }
