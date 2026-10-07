"""Create the isolated Gate 4C batch from Teaching Scenario V2."""

from __future__ import annotations

import argparse
from pathlib import Path

from ercot_game.cli import _load_scenario
from ercot_game.evaluation_jobs import create_local_job


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    scenario_path = Path("data/teaching/ercot_connection_scenario_v2.json")
    scenario = _load_scenario(scenario_path)
    submissions = [
        {
            "team_id": "team-v2-bravo",
            "connections": [
                {
                    "connection_id": "v2-bravo-site",
                    "bus_id": "HIGH_PLAINS",
                    "path_corridors": ["HIGH_PLAINS__PERMIAN"],
                    "capacity_mw": 24.0,
                    "profile": [0.8, 0.9, 1.0, 0.9, 0.8, 0.7],
                }
            ],
            "generators": [
                {
                    "generator_id": "v2-bravo-generator",
                    "connection_id": "v2-bravo-site",
                    "capacity_mw": 4.0,
                    "marginal_cost_per_mwh": 30.0,
                }
            ],
            "intervention_budget_k": 1,
            "curtailment_depth_mu": 0.2,
            "flexibility_fee_per_mwh": 2.0,
        },
        {
            "team_id": "team-v2-alpha",
            "connections": [
                {
                    "connection_id": "v2-alpha-north",
                    "bus_id": "HIGH_PLAINS",
                    "path_corridors": ["HIGH_PLAINS__PERMIAN"],
                    "capacity_mw": 30.0,
                    "profile": [1.0, 1.0, 0.9, 0.9, 1.0, 1.0],
                },
            ],
            "generators": [],
            "intervention_budget_k": 0,
            "curtailment_depth_mu": 0.0,
            "flexibility_fee_per_mwh": 0.0,
        },
        {
            "team_id": "team-v2-gulf",
            "connections": [
                {
                    "connection_id": "v2-gulf-site",
                    "bus_id": "SOUTH_TEXAS",
                    "path_corridors": ["CENTRAL_HIGHLANDS__SOUTH_TEXAS"],
                    "capacity_mw": 20.0,
                    "profile": [0.6, 0.7, 0.8, 0.8, 0.7, 0.6],
                }
            ],
            "generators": [],
            "intervention_budget_k": 2,
            "curtailment_depth_mu": 0.25,
            "flexibility_fee_per_mwh": 1.5,
        },
    ]
    package = create_local_job(
        args.root,
        scenario,
        submissions,
        round_id="phase4c-shadow-v2-20261001",
        job_id="shadow-v2c",
        policy_version="phase3-canonical-v1",
        seed=23,
    )
    print(package.path)


if __name__ == "__main__":
    main()
