"""Build the IEEE-14 teaching-demo scenario package (representative-day format).

The demo is a deliberately small stand-in for the released ACTIVSg2000
representative-day package.  It uses the canonical IEEE 14-bus topology,
branch reactances, base loads, and generator locations/nameplates.  Thermal
limits and linear generator costs are instructional choices (the canonical
case has no line ratings and quadratic costs); they are listed below and in
the package README.

Days and weights are copied from the main package
(``data/processed/activsg2000_representative_v1``): the same five days
(four k-medoids days of 2028 plus the peak day) with the same day weights,
24 one-hour periods each, 120 periods in total.  Every bus base load is
multiplied by ``scenario_profiles.demand_multiplier`` for that day and hour
of the 2028 source year (the mechanism ``hourly_state`` uses for the main
package), and the rows are materialized in ``demand_bus.csv``.

Run from the repository root (``highspy`` is required because every period
is validated with the DCOPF before the manifest is marked ``passed``)::

    python -m tools.build_ieee14_demo_package

This rewrites ``data/teaching/ieee14_demo_representative/`` (except
README.md) and ``data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json``.
The rules are exactly the main release economics
(``scripts/create_representative_scoring_rules.py``) with the demo's day
weights.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from ercot_game.scenario_package import (
    IEEE14_DEMO_PACKAGE_VERSION,
    REPRESENTATIVE_BLOCK,
    REPRESENTATIVE_DAY_COUNT,
    REPRESENTATIVE_HORIZON,
    REPRESENTATIVE_TIME_STEP_HOURS,
    require_validated_block,
    sha256_file,
)
from ercot_game.scenario_profiles import block_offset, demand_multiplier


REPO_ROOT = Path(__file__).resolve().parents[1]
HOURS_PER_DAY = 24
HORIZON = REPRESENTATIVE_HORIZON
TIME_STEP_HOURS = REPRESENTATIVE_TIME_STEP_HOURS
PROFILE_YEAR = 2028
MAIN_PACKAGE = REPO_ROOT / "data" / "processed" / "activsg2000_representative_v1"
BASE_MVA = 100.0

# Canonical IEEE-14 active-power demand (MW), buses 1..14.
BASE_LOAD_MW = (0.0, 21.7, 94.2, 47.8, 7.6, 11.2, 0.0, 0.0, 29.5, 9.0, 3.5, 6.1, 13.5, 14.9)

# bus_id -> MATPOWER bus type (3 = reference, 2 = generator, 1 = load).
BUS_TYPES = {1: 3, 2: 2, 3: 2, 6: 2, 8: 2}

# (generator_id, bus, p_max_mw, instructional linear cost $/MWh).  Nameplates
# are canonical; the gens at buses 3, 6 and 8 are condensers in the AC case
# but keep their 100 MW MATPOWER PMAX here.  Costs rise away from the slack
# bus so LMPs separate when lines bind while the uncongested price stays at
# the cheap bus-1 unit, in the range of the ACTIVSg2000 linear costs.
GENERATORS = (
    ("g1", 1, 332.4, 14.0),
    ("g2", 2, 140.0, 18.0),
    ("g3", 3, 100.0, 24.0),
    ("g6", 6, 100.0, 27.0),
    ("g8", 8, 100.0, 30.0),
)

# (from, to, canonical reactance p.u., instructional thermal limit MVA).
# 230/132 kV-side lines (buses 1-5, 7-9) get 1.3-2x headroom over peak flow;
# the 33 kV-style feeders on the low-voltage side (buses 6, 9-14) are tight.
# Lines 6-13, 9-14 and 13-14 feed buses 13 and 14 and form the shared
# bottleneck used in the two-team projection demo.
BRANCHES = (
    (1, 2, 0.05917, 250.0),
    (1, 5, 0.22304, 130.0),
    (2, 3, 0.19797, 120.0),
    (2, 4, 0.17632, 100.0),
    (2, 5, 0.17388, 80.0),
    (3, 4, 0.17103, 70.0),
    (4, 5, 0.04211, 120.0),
    (4, 7, 0.20912, 70.0),
    (4, 9, 0.55618, 40.0),
    (5, 6, 0.25202, 80.0),
    (6, 11, 0.19890, 30.0),
    (6, 12, 0.25581, 30.0),
    (6, 13, 0.13027, 45.0),
    (7, 8, 0.17615, 100.0),
    (7, 9, 0.11001, 80.0),
    (9, 10, 0.08450, 30.0),
    (9, 14, 0.27038, 30.0),
    (10, 11, 0.19207, 25.0),
    (12, 13, 0.19988, 20.0),
    (13, 14, 0.34802, 25.0),
)

_NETWORK_FILES = (
    "bus.csv",
    "bus_load_base.csv",
    "demand_bus.csv",
    "branch_limits.csv",
    "generator_catalog.csv",
    "generator_limits.csv",
    "dcline.csv",
)


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[Any, ...]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main_package_days(main_package: str | Path = MAIN_PACKAGE) -> list[dict[str, Any]]:
    """Return the representative days (date, source block/start, weight) of the main package."""
    manifest = require_validated_block(main_package)
    days = sorted(manifest["representative_days"], key=lambda day: day["day_position"])
    if len(days) != REPRESENTATIVE_DAY_COUNT:
        raise ValueError("main package must list five representative days")
    year = int(manifest["selection"]["source_year"])
    if year != PROFILE_YEAR:
        raise ValueError(f"main package source year {year} != {PROFILE_YEAR}")
    return [
        {
            "day_position": int(day["day_position"]),
            "date": day["date"],
            "source_block": day["source_block"],
            "source_period_start": int(day["source_period_start"]),
            "is_peak_day": bool(day["is_peak_day"]),
            "represented_days": day["represented_days"],
            "weight": float(day["weight"]),
            "first_period": int(day["day_position"]) * HOURS_PER_DAY,
        }
        for day in days
    ]


def period_multipliers(days: list[dict[str, Any]]) -> tuple[float, ...]:
    """Return the hourly system load multiplier of every demo period."""
    return tuple(
        round(
            demand_multiplier(
                block_offset(PROFILE_YEAR, day["source_block"]) + day["source_period_start"] + hour,
                year=PROFILE_YEAR,
            ),
            8,
        )
        for day in days
        for hour in range(HOURS_PER_DAY)
    )


def demand_rows(days: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [
        {str(bus): round(load * multiplier, 6) for bus, load in enumerate(BASE_LOAD_MW, start=1)}
        for multiplier in period_multipliers(days)
    ]


def _validate_periods(rows: list[dict[str, float]]) -> tuple[str, list[dict[str, Any]]]:
    from tools.activsg2000.dcopf import Branch, Bus, Generator, solve_dcopf

    generators = tuple(
        Generator(generator_id, str(bus), 0.0, p_max, cost)
        for generator_id, bus, p_max, cost in GENERATORS
    )
    branches = tuple(
        Branch(f"br{index:02d}", str(source), str(target), 1.0 / reactance, limit)
        for index, (source, target, reactance, limit) in enumerate(BRANCHES, start=1)
    )
    digest = hashlib.sha256()
    summaries = []
    for period_index, demand in enumerate(rows):
        result = solve_dcopf(
            buses=tuple(Bus(bus_id, value, reference=bus_id == "1") for bus_id, value in demand.items()),
            generators=generators,
            branches=branches,
            base_mva=BASE_MVA,
        )
        digest.update(_hash_payload(demand).encode("ascii"))
        summaries.append(
            {
                "period_index": period_index,
                "total_load_mw": round(sum(demand.values()), 4),
                "max_loading_fraction": round(
                    max(
                        abs(result.flow_mw_by_branch[branch.branch_id]) / branch.thermal_limit_mw
                        for branch in branches
                    ),
                    4,
                ),
            }
        )
    return digest.hexdigest(), summaries


def build_package(output_dir: str | Path, main_package: str | Path = MAIN_PACKAGE) -> dict[str, Any]:
    output = Path(output_dir)
    days = main_package_days(main_package)
    multipliers = period_multipliers(days)
    output.mkdir(parents=True, exist_ok=True)
    # Never leave a stale "passed" manifest next to regenerated tables.
    (output / "manifest.json").unlink(missing_ok=True)
    bus_ids = [str(bus) for bus in range(1, len(BASE_LOAD_MW) + 1)]
    _write_csv(output / "bus.csv", ("bus_id", "type"), [(bus, BUS_TYPES.get(int(bus), 1)) for bus in bus_ids])
    _write_csv(
        output / "bus_load_base.csv",
        ("bus_id", "base_load_mw"),
        [(bus, load) for bus, load in zip(bus_ids, BASE_LOAD_MW)],
    )
    rows = demand_rows(days)
    _write_csv(
        output / "demand_bus.csv",
        ("period", *bus_ids),
        [(period, *(row[bus] for bus in bus_ids)) for period, row in enumerate(rows)],
    )
    _write_csv(
        output / "branch_limits.csv",
        ("branch_id", "from_bus_id", "to_bus_id", "reactance_pu", "thermal_limit_mva", "status"),
        [
            (f"br{index:02d}", source, target, reactance, limit, 1)
            for index, (source, target, reactance, limit) in enumerate(BRANCHES, start=1)
        ],
    )
    generator_rows = [
        (generator_id, bus, 0.0, p_max, cost, 1, "thermal")
        for generator_id, bus, p_max, cost in GENERATORS
    ]
    generator_header = (
        "generator_id", "bus_id", "p_min_mw", "p_max_mw",
        "marginal_cost_c1_per_mwh", "status", "profile_type",
    )
    _write_csv(output / "generator_catalog.csv", generator_header, generator_rows)
    _write_csv(output / "generator_limits.csv", generator_header, generator_rows)
    _write_csv(output / "dcline.csv", ("status", "from_bus_id", "to_bus_id", "Pt"), [])

    state_hash, period_summaries = _validate_periods(rows)
    day_weights = [day["weight"] for day in days]
    period_day_weights = [day["weight"] for day in days for _hour in range(HOURS_PER_DAY)]
    representative_days = []
    for day in days:
        totals = [period_summaries[day["first_period"] + hour]["total_load_mw"] for hour in range(HOURS_PER_DAY)]
        peak_hour = max(range(HOURS_PER_DAY), key=totals.__getitem__)
        representative_days.append(
            {
                **day,
                "peak_period": day["first_period"] + peak_hour,
                "peak_load_mw": max(totals),
                "daily_energy_mwh": round(sum(totals) * TIME_STEP_HOURS, 4),
            }
        )
    block_entry = {
        "horizon": HORIZON,
        "time_step_hours": TIME_STEP_HOURS,
        "days": REPRESENTATIVE_DAY_COUNT,
        "validation_status": "passed",
        "validated_state_hash": state_hash,
        "sha256": _hash_payload(
            {
                "package_version": IEEE14_DEMO_PACKAGE_VERSION,
                "horizon": HORIZON,
                "time_step_hours": TIME_STEP_HOURS,
                "day_weights": day_weights,
            }
        ),
    }
    manifest = {
        "package_version": IEEE14_DEMO_PACKAGE_VERSION,
        "validation_status": "passed",
        "description": (
            "IEEE 14-bus teaching demo in the representative-day format: the five days and "
            "weights of activsg2000-representative-v1, 24 one-hour periods each. "
            "Not the game network; see README.md."
        ),
        "block": REPRESENTATIVE_BLOCK,
        **block_entry,
        "blocks": {REPRESENTATIVE_BLOCK: block_entry},
        "day_weights": day_weights,
        "day_weights_sum": round(sum(day_weights), 9),
        "period_day_weights": period_day_weights,
        "representative_days": representative_days,
        "load_profile": {
            "mechanism": (
                "canonical IEEE-14 bus base load x ercot_game.scenario_profiles.demand_multiplier"
                "(block_offset(2028, source_block) + source_period_start + hour), hourly values"
            ),
            "profile_year": PROFILE_YEAR,
            "days_and_weights_from": "activsg2000-representative-v1 (manifest representative_days)",
            "period_multipliers": list(multipliers),
        },
        "network": {
            "bus_count": len(bus_ids),
            "generator_count": len(GENERATORS),
            "branch_count": len(BRANCHES),
            "base_mva": BASE_MVA,
            "files": list(_NETWORK_FILES),
            "sha256": {name: sha256_file(output / name) for name in _NETWORK_FILES},
        },
        "validation": {
            "method": "single-period DCOPF (HiGHS) of every demo period",
            "passed_period_count": len(period_summaries),
            "expected_period_count": HORIZON,
            "periods": period_summaries,
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _representative_rules_module():
    path = REPO_ROOT / "scripts" / "create_representative_scoring_rules.py"
    spec = importlib.util.spec_from_file_location("create_representative_scoring_rules", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_rules(package_dir: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Write the demo scoring rules: the main release economics with the demo's day weights."""
    payload = _representative_rules_module().build_rules(package_dir)
    payload["rules_version"] = "dispatch-scoring-ieee14-demo-representative-v1"
    payload["status"] = "teaching_demo"
    payload["description"] = (
        "Scoring rules for the IEEE-14 teaching demo (5 representative days x 24 one-hour "
        "periods). Identical to dispatch-scoring-representative-v1 (ten-year present value, "
        "r = 7%, IT value 1000 $/MWh, capital charged once, daily_exact_cycle storage); "
        "the period weights come from the demo package's day weights."
    )
    Path(output_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output-dir", type=Path, default=Path("data/teaching/ieee14_demo_representative"))
    parser.add_argument("--main-package", type=Path, default=MAIN_PACKAGE)
    parser.add_argument(
        "--rules-output",
        type=Path,
        default=Path("data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json"),
    )
    args = parser.parse_args(argv)
    manifest = build_package(args.output_dir, args.main_package)
    build_rules(args.output_dir, args.rules_output)
    print(json.dumps({key: manifest[key] for key in ("package_version", "block", "horizon", "validation_status")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
