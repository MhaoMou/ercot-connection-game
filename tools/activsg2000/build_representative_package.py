"""Build the representative-day ACTIVSg2000 package for the ten-year game.

The game plans "the next ten years" on five representative days of 24
one-hour periods (120 periods).  The days are chosen from the 2028 hourly
source blocks of ``activsg2000-scenarios-v1`` (``jan_jun`` followed by
``jul_dec``, 366 days):

1. Every day's 24-hour system-load profile (sum of all bus demands from
   ``ercot_game.scenario_profiles.hourly_state``) is divided by the annual
   peak hourly system load, giving one per-unit 24-vector per day.
2. The vectors are clustered into four groups with PAM k-medoids (greedy
   BUILD, then SWAP until no exchange helps) on exact integer squared
   distances of the features quantized to 1e-6 per unit.  No random numbers
   are used, so the choice is identical on every machine.  Each medoid is a
   representative day.
3. The day containing the annual peak hourly system load is added as a fifth
   representative day.  It is removed from its cluster (when it was that
   cluster's medoid the medoid is recomputed from the remaining members).
4. The peak day has weight 1. Each other day's weight is the number of
   calendar days it represents (cluster size), scaled by 364/365 so that the
   weights of the leap source year sum to 365.

Bus demand is materialized in ``demand_bus.csv`` (one row per period), in
the same way as the IEEE-14 demo package, so the package does not depend on
the half-year calendar.  Generators, branches and DC lines are copied from
the source block (static limits).  The manifest is marked ``passed`` only
after every period has been solved with the single-period DCOPF.

Run from the repository root (``highspy`` is required for validation)::

    PYTHONPATH=src:. python3 -m tools.activsg2000.build_representative_package

The output is byte-identical across reruns on the same inputs.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from ercot_game.calendars import half_year_calendar
from ercot_game.scenario_package import (
    REPRESENTATIVE_DAY_COUNT,
    REPRESENTATIVE_HORIZON,
    REPRESENTATIVE_PACKAGE_VERSION,
    REPRESENTATIVE_TIME_STEP_HOURS,
    sha256_file,
)
from ercot_game.scenario_profiles import block_offset, hourly_state


SOURCE_YEAR = 2028
SOURCE_BLOCKS = ("jan_jun", "jul_dec")
CLUSTER_COUNT = REPRESENTATIVE_DAY_COUNT - 1
FEATURE_SCALE = 1_000_000
KMEDOIDS_MAX_ITERATIONS = 100
DAYS_PER_YEAR = 365
HOURS_PER_DAY = 24
DEMAND_DECIMALS = 6

_COPIED_FILES = (
    "bus.csv",
    "bus_load_base.csv",
    "branch_limits.csv",
    "generator_catalog.csv",
    "generator_limits.csv",
    "dcline.csv",
)
_NETWORK_FILES = (*_COPIED_FILES, "demand_bus.csv", "representative_days.csv")


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[Any, ...]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def source_days(source_package: str | Path, year: int = SOURCE_YEAR) -> list[dict[str, Any]]:
    """Return the calendar days of the concatenated source blocks.

    Each entry names the source block and the first local period of the day.
    ``profile_day_index`` is the day index the source load model uses; the
    ``jul_dec`` block starts at ``block_offset`` (half the year's hours), so
    in a leap year it is one day ahead of the calendar date.
    """
    days = []
    for block in SOURCE_BLOCKS:
        calendar = half_year_calendar(year, block)
        block_dir = Path(source_package) / str(year) / block
        if not (block_dir / "bus_load_base.csv").is_file():
            raise ValueError(f"source block is missing: {block_dir}")
        for local_day in range(calendar.horizon // HOURS_PER_DAY):
            days.append(
                {
                    "date": (calendar.start_date + timedelta(days=local_day)).isoformat(),
                    "source_block": block,
                    "source_block_dir": block_dir,
                    "source_period_start": local_day * HOURS_PER_DAY,
                    "profile_day_index": (block_offset(year, block) // HOURS_PER_DAY) + local_day,
                }
            )
    return days


def daily_system_load(source_package: str | Path, year: int = SOURCE_YEAR) -> tuple[list[dict[str, Any]], np.ndarray]:
    """Return the source days and their 24-hour system load (MW) matrix."""
    days = source_days(source_package, year)
    loads = np.empty((len(days), HOURS_PER_DAY))
    for row, day in enumerate(days):
        for hour in range(HOURS_PER_DAY):
            demand, _availability = hourly_state(
                day["source_block_dir"],
                year=year,
                calendar_block=day["source_block"],
                period_index=day["source_period_start"] + hour,
            )
            loads[row, hour] = sum(demand.values())
    return days, loads


def _integer_dissimilarity(features: np.ndarray, scale: float) -> np.ndarray:
    """Exact squared Euclidean distances of features quantized to integers.

    Integer arithmetic makes the clustering bit-for-bit reproducible across
    machines and NumPy versions; the daily profiles of the source load model
    are nearly symmetric around the seasonal peak, so floating-point
    near-ties would otherwise pick different (equally good) medoids.
    """
    quantized = np.rint(np.asarray(features, dtype=float) * scale).astype(np.int64)
    differences = quantized[:, None, :] - quantized[None, :, :]
    return (differences * differences).sum(axis=2)


def _assign(distances: np.ndarray, medoids: np.ndarray) -> np.ndarray:
    # Ties go to the lowest medoid position, which keeps the result stable.
    return np.argmin(distances[:, medoids], axis=1)


def _medoid_of(distances: np.ndarray, members: np.ndarray) -> int:
    within = distances[np.ix_(members, members)].sum(axis=1)
    return int(members[int(np.argmin(within))])


def k_medoids(
    features: np.ndarray,
    k: int,
    *,
    scale: float = FEATURE_SCALE,
    max_iterations: int = KMEDOIDS_MAX_ITERATIONS,
) -> tuple[np.ndarray, np.ndarray]:
    """Cluster rows of ``features`` with PAM k-medoids (BUILD then SWAP).

    The dissimilarity is the squared Euclidean distance of the features
    quantized to integers (``round(feature x scale)``), so every comparison
    is exact.  BUILD adds medoids greedily; SWAP applies the best
    medoid/non-medoid exchange until none lowers the total dissimilarity.
    Ties go to the lowest row index.  The procedure uses no random numbers,
    so the result is the same on every machine.

    Returns ``(medoids, labels)`` where ``medoids`` holds sorted row indices
    and ``labels[i]`` is the position of row ``i``'s medoid in ``medoids``.
    """
    distances = _integer_dissimilarity(features, scale)
    count = distances.shape[0]
    if not 1 <= k <= count:
        raise ValueError("k must be between 1 and the number of rows")
    medoids = [int(np.argmin(distances.sum(axis=1)))]
    nearest = distances[:, medoids[0]].copy()
    while len(medoids) < k:
        gains = np.maximum(nearest[:, None] - distances, 0).sum(axis=0)
        gains[medoids] = -1
        chosen = int(np.argmax(gains))
        medoids.append(chosen)
        nearest = np.minimum(nearest, distances[:, chosen])
    current = np.array(sorted(medoids))
    cost = int(distances[:, current].min(axis=1).sum())
    for _iteration in range(max_iterations):
        best: tuple[int, int, int] | None = None
        for position in range(k):
            others = np.delete(current, position)
            other_nearest = distances[:, others].min(axis=1) if others.size else np.full(count, np.iinfo(np.int64).max)
            candidate_costs = np.minimum(other_nearest[:, None], distances).sum(axis=0)
            candidate_costs[current] = np.iinfo(np.int64).max
            candidate = int(np.argmin(candidate_costs))
            value = int(candidate_costs[candidate])
            if value < cost and (best is None or value < best[0]):
                best = (value, position, candidate)
        if best is None:
            break
        cost, position, candidate = best
        current = np.array(sorted([*np.delete(current, position).tolist(), candidate]))
    return current, _assign(distances, current)


def select_representative_days(
    daily_load_mw: np.ndarray,
    *,
    clusters: int = CLUSTER_COUNT,
    days_per_year: int = DAYS_PER_YEAR,
) -> list[dict[str, Any]]:
    """Pick ``clusters`` medoid days plus the peak day, with day weights.

    Returns one record per representative day in chronological order with
    the source row (``day_row``), the represented day count and the weight.
    """
    daily_load_mw = np.asarray(daily_load_mw, dtype=float)
    annual_peak = float(daily_load_mw.max())
    features = daily_load_mw / annual_peak
    medoids, labels = k_medoids(features, clusters)
    peak_row = int(np.unravel_index(int(np.argmax(daily_load_mw)), daily_load_mw.shape)[0])
    distances = _integer_dissimilarity(features, FEATURE_SCALE)
    records = []
    for position, medoid in enumerate(medoids):
        members = np.flatnonzero(labels == position)
        members = members[members != peak_row]
        if members.size == 0:
            raise ValueError("the peak day formed a cluster on its own; choose fewer clusters")
        if int(medoid) == peak_row:
            medoid = _medoid_of(distances, members)
        records.append({"day_row": int(medoid), "cluster": position, "represented_days": int(members.size), "is_peak_day": False})
    records.append({"day_row": peak_row, "cluster": None, "represented_days": 1, "is_peak_day": True})
    total_days = sum(record["represented_days"] for record in records)
    if total_days != daily_load_mw.shape[0]:
        raise AssertionError("representative days must cover every source day")
    # The peak day stands for itself (weight 1); the clustered days share the
    # rest of the year, so the weights sum to days_per_year.
    scale = (days_per_year - 1) / (total_days - 1)
    for record in records:
        record["weight"] = 1.0 if record["is_peak_day"] else record["represented_days"] * scale
    return sorted(records, key=lambda record: record["day_row"])


def _validate_periods(output: Path) -> tuple[str, list[dict[str, Any]]]:
    from tools.activsg2000.dcopf import clear_prepared_artifact_cache, solve_prepared_period

    clear_prepared_artifact_cache()
    digest = hashlib.sha256()
    summaries = []
    with (output / "demand_bus.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for period_index, row in enumerate(rows):
        result = solve_prepared_period(output, period_index=period_index)
        if result.status != "optimal":
            raise ValueError(f"representative period {period_index} is not DCOPF-feasible: {result.status}")
        demand = {key: value for key, value in row.items() if key != "period"}
        digest.update(_hash_payload(demand).encode("ascii"))
        summaries.append(
            {
                "period_index": period_index,
                "solver_status": result.status,
                "total_load_mw": round(sum(float(value) for value in demand.values()), 3),
                "objective_cost": round(float(result.objective_cost)),
            }
        )
    return digest.hexdigest(), summaries


def build_package(
    source_package: str | Path,
    output_dir: str | Path,
    *,
    year: int = SOURCE_YEAR,
    validate: bool = True,
) -> dict[str, Any]:
    """Write the representative-day package and return its manifest."""
    source = Path(source_package)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # Never leave a stale "passed" manifest next to regenerated tables.
    (output / "manifest.json").unlink(missing_ok=True)
    days, daily_load = daily_system_load(source, year)
    selected = select_representative_days(daily_load)

    first_block = source / str(year) / SOURCE_BLOCKS[0]
    for name in _COPIED_FILES:
        for block in SOURCE_BLOCKS[1:]:
            if sha256_file(first_block / name) != sha256_file(source / str(year) / block / name):
                raise ValueError(f"source blocks disagree on static table {name}")
        shutil.copyfile(first_block / name, output / name)

    with (output / "bus.csv").open(newline="", encoding="utf-8") as handle:
        bus_ids = [row["bus_id"] for row in csv.DictReader(handle)]
    demand_rows = []
    day_rows = []
    period_weights = []
    annual_peak = float(daily_load.max())
    for day_position, record in enumerate(selected):
        day = days[record["day_row"]]
        for hour in range(HOURS_PER_DAY):
            demand, _availability = hourly_state(
                day["source_block_dir"],
                year=year,
                calendar_block=day["source_block"],
                period_index=day["source_period_start"] + hour,
            )
            demand_rows.append(
                (
                    day_position * HOURS_PER_DAY + hour,
                    *(f"{round(demand[bus_id], DEMAND_DECIMALS):.{DEMAND_DECIMALS}f}" for bus_id in bus_ids),
                )
            )
            period_weights.append(record["weight"])
        loads = daily_load[record["day_row"]]
        day_rows.append(
            {
                "day_position": day_position,
                "date": day["date"],
                "source_block": day["source_block"],
                "source_period_start": day["source_period_start"],
                "profile_day_index": day["profile_day_index"],
                "cluster": record["cluster"],
                "is_peak_day": record["is_peak_day"],
                "represented_days": record["represented_days"],
                "weight": round(record["weight"], 12),
                "first_period": day_position * HOURS_PER_DAY,
                "daily_energy_mwh": round(float(loads.sum()), 3),
                "peak_load_mw": round(float(loads.max()), 3),
                "min_load_mw": round(float(loads.min()), 3),
            }
        )
    if len(demand_rows) != REPRESENTATIVE_HORIZON:
        raise AssertionError("the representative package must contain 120 periods")
    _write_csv(output / "demand_bus.csv", ("period", *bus_ids), demand_rows)
    day_header = tuple(day_rows[0])
    _write_csv(
        output / "representative_days.csv",
        day_header,
        [tuple("" if row[key] is None else row[key] for key in day_header) for row in day_rows],
    )

    def write_manifest(status: str, validation: dict[str, Any], state_hash: str | None) -> dict[str, Any]:
        block_entry = {
            "horizon": REPRESENTATIVE_HORIZON,
            "time_step_hours": REPRESENTATIVE_TIME_STEP_HOURS,
            "days": REPRESENTATIVE_DAY_COUNT,
            "validation_status": status,
            "sha256": _hash_payload(
                {
                    "package_version": REPRESENTATIVE_PACKAGE_VERSION,
                    "horizon": REPRESENTATIVE_HORIZON,
                    "dates": [row["date"] for row in day_rows],
                }
            ),
        }
        if state_hash is not None:
            block_entry["validated_state_hash"] = state_hash
        manifest = {
            "package_version": REPRESENTATIVE_PACKAGE_VERSION,
            "validation_status": status,
            "description": (
                "ACTIVSg2000 representative days for the ten-year connection game: "
                "four k-medoids days of the 2028 source year plus its peak day, "
                "24 one-hour periods each."
            ),
            "block": "representative",
            **block_entry,
            "blocks": {"representative": block_entry},
            "day_weights": [row["weight"] for row in day_rows],
            "day_weights_sum": round(sum(row["weight"] for row in day_rows), 9),
            "period_day_weights": [round(value, 12) for value in period_weights],
            "representative_days": day_rows,
            "selection": {
                "source_package": "activsg2000-scenarios-v1",
                "source_year": year,
                "source_blocks": list(SOURCE_BLOCKS),
                "source_day_count": len(days),
                "load_mechanism": (
                    "ercot_game.scenario_profiles.hourly_state (bus base load times "
                    "demand_multiplier); jul_dec starts at block_offset, so its "
                    "profile_day_index is one day ahead of the calendar date in 2028"
                ),
                "feature": "24-hour system load divided by the annual peak hourly system load",
                "annual_peak_hourly_load_mw": round(annual_peak, 3),
                "annual_energy_mwh": round(float(daily_load.sum()), 3),
                "method": (
                    "PAM k-medoids (BUILD + SWAP, no random numbers) on squared Euclidean "
                    "distances of the features quantized to integers"
                ),
                "feature_scale": FEATURE_SCALE,
                "clusters": CLUSTER_COUNT,
                "peak_day": "day of the annual peak hourly system load, weight = 1 day, removed from its cluster",
                "weight_rule": f"peak day 1; other days: represented days x {DAYS_PER_YEAR - 1}/{len(days) - 1} so weights sum to {DAYS_PER_YEAR}",
                "weighted_annual_energy_mwh": round(
                    sum(row["weight"] * row["daily_energy_mwh"] for row in day_rows), 3
                ),
            },
            "network": {
                "bus_count": len(bus_ids),
                "files": list(_NETWORK_FILES),
                "sha256": {name: sha256_file(output / name) for name in _NETWORK_FILES},
                "generator_limits": "static source status, PMIN and PMAX",
            },
            "validation": validation,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    if not validate:
        return write_manifest(
            "pending",
            {"method": "not run", "expected_period_count": REPRESENTATIVE_HORIZON},
            None,
        )
    # Solving needs a manifest on disk; mark it pending until every period passes.
    write_manifest("pending", {"method": "in progress"}, None)
    state_hash, summaries = _validate_periods(output)
    return write_manifest(
        "passed",
        {
            "method": "single-period DCOPF (HiGHS) of every representative period",
            "passed_period_count": len(summaries),
            "expected_period_count": REPRESENTATIVE_HORIZON,
            "periods": summaries,
        },
        state_hash,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-package", type=Path, default=Path("data/processed/activsg2000_scenarios_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/activsg2000_representative_v1"))
    parser.add_argument("--year", type=int, default=SOURCE_YEAR)
    parser.add_argument("--skip-validation", action="store_true", help="write a pending manifest without DCOPF checks")
    args = parser.parse_args(argv)
    manifest = build_package(args.source_package, args.output_dir, year=args.year, validate=not args.skip_validation)
    print(
        json.dumps(
            {
                "package_version": manifest["package_version"],
                "horizon": manifest["horizon"],
                "validation_status": manifest["validation_status"],
                "dates": [row["date"] for row in manifest["representative_days"]],
                "weights": [round(value, 4) for value in manifest["day_weights"]],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
