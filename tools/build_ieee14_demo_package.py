"""Build the IEEE-14 teaching-demo scenario package.

The demo is a deliberately small stand-in for one ACTIVSg2000 scenario block.
It uses the canonical IEEE 14-bus topology, branch reactances, base loads,
and generator locations/nameplates.  Thermal limits and linear generator
costs are instructional choices (the canonical case has no line ratings and
quadratic costs); they are listed below and in the package README.

Loads follow the same daily shape as the ACTIVSg2000 packages: every bus
base load is multiplied by ``scenario_profiles.demand_multiplier`` for the
first week (168 hours) of the 2028 jul_dec calendar block, giving 168
one-hour periods (no averaging).  The demand rows are materialized in ``demand_bus.csv`` so the package does not
depend on the half-year calendar.

Run from the repository root (``highspy`` is required because every period
is validated with the DCOPF before the manifest is marked ``passed``)::

    python -m tools.build_ieee14_demo_package

This rewrites ``data/teaching/ieee14_demo_1h/`` (except README.md) and
``data/teaching/dispatch_scoring_rules_ieee14_demo_1h_v1.json``, derived from
the released jul_dec six-hour rules (operating coefficients and the
``daily_exact_cycle`` storage mode) with one-hour periods and capital costs
prorated from the 4416-hour half-year to the 168-hour demo week.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from ercot_game.scenario_package import (
    IEEE14_DEMO_BLOCK,
    IEEE14_DEMO_EXPECTED_HORIZONS,
    IEEE14_DEMO_PACKAGE_VERSION,
    IEEE14_DEMO_TIME_STEP_HOURS,
    sha256_file,
)
from ercot_game.scenario_profiles import block_offset, demand_multiplier


HORIZON = IEEE14_DEMO_EXPECTED_HORIZONS[IEEE14_DEMO_BLOCK]
TIME_STEP_HOURS = IEEE14_DEMO_TIME_STEP_HOURS
PROFILE_YEAR = 2028
PROFILE_CALENDAR_BLOCK = "jul_dec"
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


def period_multipliers() -> tuple[float, ...]:
    """Return the per-period mean load multipliers of the demo week.

    With one-hour periods each value is the hourly multiplier itself.
    """
    start = block_offset(PROFILE_YEAR, PROFILE_CALENDAR_BLOCK)
    return tuple(
        round(
            sum(
                demand_multiplier(start + period * TIME_STEP_HOURS + hour, year=PROFILE_YEAR)
                for hour in range(TIME_STEP_HOURS)
            )
            / TIME_STEP_HOURS,
            8,
        )
        for period in range(HORIZON)
    )


def demand_rows() -> list[dict[str, float]]:
    return [
        {str(bus): round(load * multiplier, 6) for bus, load in enumerate(BASE_LOAD_MW, start=1)}
        for multiplier in period_multipliers()
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


def build_package(output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
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
    rows = demand_rows()
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
    block_entry = {
        "horizon": HORIZON,
        "time_step_hours": TIME_STEP_HOURS,
        "source_horizon_hours": HORIZON * TIME_STEP_HOURS,
        "validation_status": "passed",
        "validated_state_hash": state_hash,
        "sha256": _hash_payload(
            {"block": IEEE14_DEMO_BLOCK, "horizon": HORIZON, "time_step_hours": TIME_STEP_HOURS}
        ),
    }
    manifest = {
        "package_version": IEEE14_DEMO_PACKAGE_VERSION,
        "validation_status": "passed",
        "description": (
            "IEEE 14-bus teaching demo, one week of one-hour periods. "
            "Not the game network; see README.md."
        ),
        "block": IEEE14_DEMO_BLOCK,
        **block_entry,
        "blocks": {IEEE14_DEMO_BLOCK: block_entry},
        "load_profile": {
            "mechanism": "ercot_game.scenario_profiles.demand_multiplier, hourly values",
            "profile_year": PROFILE_YEAR,
            "profile_calendar_block": PROFILE_CALENDAR_BLOCK,
            "profile_source_hours": [0, HORIZON * TIME_STEP_HOURS],
            "period_multipliers": list(period_multipliers()),
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


def build_rules(source_rules: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Derive the one-hour demo scoring rules from the released rules.

    Operating coefficients ($/MWh values, the team generator cost curve and
    the ``daily_exact_cycle`` storage mode) are copied unchanged; the period
    length becomes one hour.  Capital costs (site, generator, storage) are
    scaled by demo hours / source half-year hours (168/4416 for jul_dec) so
    that one demo week has the same economics as one half-year submission;
    without this every demo score is dominated by half a year of capital.
    """
    payload = json.loads(Path(source_rules).read_text(encoding="utf-8"))
    source_step_hours = float(payload.get("time_step_hours", 0))
    if source_step_hours <= 0 or 24 % TIME_STEP_HOURS:
        raise ValueError("source rules need a positive time_step_hours and the demo step must divide 24")
    values = {float(value) for value in payload["it_value_per_mwh"]}
    if len(values) != 1:
        raise ValueError("source rules must use a constant IT value")
    it_value = values.pop()
    source_version = payload["rules_version"]
    source_horizon_hours = round(len(payload["it_value_per_mwh"]) * source_step_hours)
    capital_scale = HORIZON * TIME_STEP_HOURS / source_horizon_hours
    for key in (
        "site_cost_per_mw",
        "generator_capital_cost_per_mw",
        "storage_capital_cost_per_mw",
        "storage_capital_cost_per_mwh",
    ):
        payload[key] = round(float(payload[key]) * capital_scale, 2)
    payload["rules_version"] = "dispatch-scoring-ieee14-demo-1h-v1"
    payload["status"] = "teaching_demo"
    payload["description"] = (
        f"One-hour scoring rules for the IEEE-14 teaching demo (one week, {HORIZON} periods). "
        f"Operating coefficients are copied from {source_version}; capital costs are "
        f"prorated by {HORIZON * TIME_STEP_HOURS}/{source_horizon_hours} hours so that one "
        "demo week has the same economics as one half-year submission."
    )
    payload["capital_cost_scale"] = capital_scale
    payload["source_rules_version"] = source_version
    payload["it_value_per_mwh"] = [it_value] * HORIZON
    payload["time_step_hours"] = float(TIME_STEP_HOURS)
    payload["storage_boundary_mode"] = "daily_exact_cycle"
    payload["time_step_hours_provenance"] = {
        "interpretation": "one-hour interval; daily storage cycle of 24 periods",
        "horizon_hours": HORIZON * TIME_STEP_HOURS,
        "calendar_block": IEEE14_DEMO_BLOCK,
        "source_horizon_hours": HORIZON * TIME_STEP_HOURS,
        "horizon_periods": HORIZON,
        "time_step_hours": float(TIME_STEP_HOURS),
        "capital_cost_source_horizon_hours": source_horizon_hours,
    }
    payload["it_value_provenance"]["horizon_hours"] = HORIZON
    payload.pop("economic_profile_artifact", None)
    Path(output_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output-dir", type=Path, default=Path("data/teaching/ieee14_demo_1h"))
    parser.add_argument(
        "--source-rules",
        type=Path,
        default=Path("data/teaching/dispatch_scoring_rules_jul_dec_6h_v1.json"),
    )
    parser.add_argument(
        "--rules-output",
        type=Path,
        default=Path("data/teaching/dispatch_scoring_rules_ieee14_demo_1h_v1.json"),
    )
    args = parser.parse_args(argv)
    manifest = build_package(args.output_dir)
    build_rules(args.source_rules, args.rules_output)
    print(json.dumps({key: manifest[key] for key in ("package_version", "block", "horizon", "validation_status")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
