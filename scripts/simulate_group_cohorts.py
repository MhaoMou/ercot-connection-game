"""Generate reproducible complete-horizon cohorts for instructor-side simulation.

This is intentionally a small strategy generator, not a student strategy
recommendation. It creates valid CSV submissions with geographically spread
sites and a mixture of grid-only, generator-backed, and storage-backed teams.
The production batch evaluator remains responsible for all dispatch and score
calculation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path


HEADER = (
    "team_id", "submission_id", "period", "bus_id", "load_mw",
    "generator_id", "generator_capacity_mw", "storage_id",
    "storage_power_mw", "storage_energy_mwh",
)


def read_catalog(artifact_dir: Path) -> tuple[list[str], list[dict[str, str]]]:
    with (artifact_dir / "bus.csv").open(newline="", encoding="utf-8") as handle:
        buses = [row["bus_id"] for row in csv.DictReader(handle)]
    with (artifact_dir / "generator_limits.csv").open(newline="", encoding="utf-8") as handle:
        generators = list(csv.DictReader(handle))
    return buses, generators


def select_sites(
    buses: list[str], generators: list[dict[str, str]], *, count: int, seed: int
) -> list[tuple[str, dict[str, str] | None]]:
    rng = random.Random(seed)
    by_bus: dict[str, list[dict[str, str]]] = {}
    for generator in generators:
        if float(generator.get("p_max_mw", "0") or 0) >= 2.0:
            by_bus.setdefault(generator["bus_id"], []).append(generator)
    generator_buses = [bus for bus in buses if bus in by_bus]
    rng.shuffle(generator_buses)
    plain_buses = list(buses)
    rng.shuffle(plain_buses)
    chosen: list[tuple[str, dict[str, str] | None]] = []
    used: set[str] = set()
    for bus in generator_buses:
        if len(chosen) >= count:
            break
        if bus not in used:
            chosen.append((bus, by_bus[bus][0]))
            used.add(bus)
    for bus in plain_buses:
        if len(chosen) >= count:
            break
        if bus not in used:
            chosen.append((bus, None))
            used.add(bus)
    if len(chosen) != count:
        raise RuntimeError(f"could not select {count} distinct buses")
    return chosen


def write_cohort(
    output_dir: Path,
    *,
    cohort_size: int,
    repetition: int,
    horizon: int,
    artifact_dir: Path,
    seed: int,
) -> dict[str, object]:
    buses, generators = read_catalog(artifact_dir)
    sites = select_sites(buses, generators, count=cohort_size, seed=seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed + 1009)
    teams: list[dict[str, object]] = []
    for index, (bus_id, generator) in enumerate(sites, start=1):
        team_id = f"sim-{cohort_size:02d}-r{repetition:02d}-team-{index:02d}"
        submission_id = f"sim-{cohort_size:02d}-r{repetition:02d}"
        # Keep demand modest but heterogeneous; this represents a deliberately
        # exploratory class exercise rather than an adversarial stress test.
        base_load = round(4.0 + rng.random() * 6.0, 3)
        has_generator = generator is not None and index % 3 == 1
        has_storage = index % 3 == 2
        generator_id = generator["generator_id"] if has_generator and generator else ""
        generator_capacity = round(min(base_load * 0.35, float(generator["p_max_mw"]) * 0.25), 3) if has_generator and generator else 0.0
        storage_power = round(min(base_load * 0.25, 3.0), 3) if has_storage else 0.0
        storage_energy = round(storage_power * 2.0, 3) if has_storage else 0.0
        storage_id = f"{team_id}-storage" if has_storage else ""
        path = output_dir / f"{team_id}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADER)
            for period in range(1, horizon + 1):
                # A bounded daily-like variation avoids identical plans while
                # preserving complete coverage and easy reproducibility.
                phase = ((period - 1) % 24) / 24.0
                load = max(0.5, base_load * (0.9 + 0.15 * (0.5 + 0.5 * math.sin(2 * math.pi * phase))))
                writer.writerow([
                    team_id, submission_id, period, bus_id, f"{load:.6f}",
                    generator_id, f"{generator_capacity:.6f}" if generator_id else "",
                    storage_id, f"{storage_power:.6f}" if storage_id else "",
                    f"{storage_energy:.6f}" if storage_id else "",
                ])
        teams.append({
            "team_id": team_id,
            "bus_id": bus_id,
            "generator_id": generator_id or None,
            "storage_id": storage_id or None,
            "base_load_mw": base_load,
        })
    metadata = {
        "cohort_size": cohort_size,
        "repetition": repetition,
        "horizon": horizon,
        "seed": seed,
        "teams": teams,
    }
    (output_dir / "cohort_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--horizon", type=int, default=4368)
    parser.add_argument("--cohort-sizes", type=int, nargs="+", default=[4, 8, 16])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261007)
    args = parser.parse_args()
    manifest = []
    for cohort_size in args.cohort_sizes:
        for repetition in range(1, args.repetitions + 1):
            directory = args.output_root / f"groups_{cohort_size:02d}_rep_{repetition:02d}"
            manifest.append(write_cohort(
                directory,
                cohort_size=cohort_size,
                repetition=repetition,
                horizon=args.horizon,
                artifact_dir=args.artifact_dir,
                seed=args.seed + cohort_size * 100 + repetition,
            ))
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "simulation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"generated {len(manifest)} cohorts under {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
