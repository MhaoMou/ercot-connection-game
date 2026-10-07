"""Compare local and remote Gate 4C shadow summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


COMPARISON_KEYS = (
    "status",
    "scenario_id",
    "planning_model_version",
    "batch_input_hash",
    "output_hash",
    "replayed_output_hash",
    "ranked_results",
)


def load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"summary must be an object: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("local", type=Path)
    parser.add_argument("remote", type=Path)
    args = parser.parse_args()
    local = load(args.local)
    remote = load(args.remote)

    mismatches = [key for key in COMPARISON_KEYS if local.get(key) != remote.get(key)]
    artifact_match = local.get("artifact_sha256") == remote.get("artifact_sha256")
    print(json.dumps({"comparison_mismatches": mismatches, "artifact_sha256_match": artifact_match}))
    print(
        "rank_order:",
        [
            (item["rank"], item["team_id"], item["official_revenue"], item["validation"]["valid"])
            for item in local["ranked_results"]
        ],
    )
    print(
        "binding_diagnostics:",
        [
            (
                item["team_id"],
                (item["evaluator_result"] or {}).get("diagnostics"),
            )
            for item in local["ranked_results"]
        ],
    )
    if mismatches or not artifact_match:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
