"""Promote the frozen Gate 4.6 candidate to a production planning model."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/processed/reduced/candidate_12_v2.json"
DEFAULT_OUTPUT = ROOT / "data/processed/ercot_planning_model_v1.json"


def promote_candidate(source: Path = SOURCE) -> dict[str, object]:
    candidate = json.loads(source.read_text(encoding="utf-8"))
    if candidate.get("candidate_id") != "candidate_12_v2":
        raise ValueError("Gate 5 promotion requires candidate_12_v2")
    if candidate.get("target_region_count") != 12:
        raise ValueError("Gate 5 promotion requires twelve planning regions")
    if len(candidate.get("planning_nodes", ())) != 12:
        raise ValueError("candidate must contain twelve planning nodes")
    if len(candidate.get("planning_interfaces", ())) != 20:
        raise ValueError("candidate must contain twenty planning interfaces")

    model = deepcopy(candidate)
    model.pop("candidate_id", None)
    model.pop("target_region_count", None)
    for interface in model["planning_interfaces"]:
        interface.pop("teaching_transfer_limit_mw", None)
    model.update(
        {
            "planning_model_schema": "ercot.planning-model.v1",
            "model_id": "ercot-public-derived-planning",
            "model_version": "1.0.0",
            "status": "production-teaching-input",
            "provenance": {
                "source_candidate": "data/processed/reduced/candidate_12_v2.json",
                "source_public_network": "data/processed/ercot_public_network.json",
                "boundary_asset": "web/texas-boundary.json",
                "gate": "Gate 4.6 approved regionalization",
                "public_evidence_only": True,
                "teaching_limits_included": False,
            },
        }
    )
    return model


def main() -> None:
    DEFAULT_OUTPUT.write_text(
        json.dumps(promote_candidate(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
