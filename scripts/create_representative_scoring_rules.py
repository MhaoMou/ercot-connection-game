#!/usr/bin/env python3
"""Generate the ten-year present-value scoring rules for the representative package.

Every energy-based term (IT value, energy cost at LMP when enabled, private
generator operating cost) of period ``t`` is weighted by

    w_t = time_step_hours x weight(day of t) x A,   A = sum_{y=1..10} (1 + r)^-y,

so one representative period stands for its day's share of a year, repeated
for ten years and discounted to the present.  Capital costs are charged
once, undiscounted.  The day weights are read from the package manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ercot_game.scenario_package import (
    REPRESENTATIVE_HORIZON,
    REPRESENTATIVE_TIME_STEP_HOURS,
    require_validated_block,
)


IT_VALUE_PER_MWH = 1000.0
DISCOUNT_RATE = 0.07
PLANNING_YEARS = 10
SITE_COST_PER_MW = 25_000_000.0
MAX_GENERATOR_TO_CONNECTION_RATIO = 0.5
GENERATOR_CAPITAL_COST_PER_MW = 2_000_000.0
# Daily run-hour budget: a team generator of capacity G may produce at most
# GENERATOR_DAILY_ENERGY_HOURS x G MWh per representative day.
GENERATOR_DAILY_ENERGY_HOURS = 2.0
TEAM_GENERATOR_COST_CURVE = (
    (0.25, 80.0),
    (0.50, 150.0),
    (0.25, 250.0),
)


def annuity_factor(rate: float = DISCOUNT_RATE, years: int = PLANNING_YEARS) -> float:
    """Return the present value of 1 $/year for ``years`` years at ``rate``."""
    return sum((1.0 + rate) ** -year for year in range(1, years + 1))


def build_rules(package_dir: str | Path) -> dict[str, object]:
    manifest = require_validated_block(package_dir)
    day_weights = [float(value) for value in manifest["day_weights"]]
    period_day_weights = [float(value) for value in manifest["period_day_weights"]]
    if len(period_day_weights) != REPRESENTATIVE_HORIZON:
        raise ValueError("package must list one day weight per period")
    factor = annuity_factor()
    step = float(REPRESENTATIVE_TIME_STEP_HOURS)
    period_weights = [round(step * weight * factor, 9) for weight in period_day_weights]
    annual_hours = round(step * sum(period_day_weights), 6)
    break_even_fraction = SITE_COST_PER_MW / (IT_VALUE_PER_MWH * annual_hours * factor)
    return {
        "rules_version": "dispatch-scoring-representative-v1",
        "status": "released",
        "description": (
            "Ten-year present-value scoring rules for the ACTIVSg2000 representative-day "
            "package (5 days x 24 one-hour periods). Each energy-based term of period t "
            "is weighted by period_weight_hours[t] = time_step_hours x day weight x "
            "present_value_annuity_factor; capital costs are charged once, undiscounted. "
            "Energy purchases (when enabled for the week) settle at joint-dispatch LMPs; "
            "these are instructional model outputs, not an ERCOT price forecast."
        ),
        "scenario_package": manifest["package_version"],
        "it_value_per_mwh": [IT_VALUE_PER_MWH] * REPRESENTATIVE_HORIZON,
        "time_step_hours": step,
        "discount_rate": DISCOUNT_RATE,
        "planning_years": PLANNING_YEARS,
        "present_value_annuity_factor": round(factor, 12),
        "day_weights": day_weights,
        "period_day_weights": period_day_weights,
        "period_weight_hours": period_weights,
        "max_generator_to_connection_ratio": MAX_GENERATOR_TO_CONNECTION_RATIO,
        "generator_capital_cost_per_mw": GENERATOR_CAPITAL_COST_PER_MW,
        "generator_daily_energy_hours": GENERATOR_DAILY_ENERGY_HOURS,
        "site_cost_per_mw": SITE_COST_PER_MW,
        "infeasible_score": 0.0,
        "default_generator_cost_per_mwh": 150.0,
        "team_generator_cost_curve": [
            {"capacity_fraction": fraction, "marginal_cost_per_mwh": marginal_cost}
            for fraction, marginal_cost in TEAM_GENERATOR_COST_CURVE
        ],
        "storage_capital_cost_per_mw": 400_000.0,
        "storage_capital_cost_per_mwh": 250_000.0,
        "storage_boundary_mode": "daily_exact_cycle",
        "weighting_provenance": {
            "formula": "w_t = time_step_hours * day_weight(t) * A, A = sum_{y=1}^{10} (1 + r)^(-y)",
            "applies_to": [
                "IT value on served load",
                "energy purchase cost at LMP (weeks with energy cost enabled)",
                "private generator operating cost (80/150/250 $/MWh over 25/50/25% of capacity)",
            ],
            "not_weighted": "site, generator and storage capital costs (charged once, undiscounted)",
            "day_weights": "represented calendar days of each representative day, scaled to sum to 365 (see the package manifest)",
            "annual_hours_represented": annual_hours,
            "discount_rate_note": "instructor-chosen real discount rate of 7% over a ten-year planning life",
            "served_load_mwh_note": "reported served load is in MWh per represented year (weighted energy / A)",
        },
        "it_value_provenance": {
            "basis": "instructor-chosen net margin of served computational load",
            "base_value_per_mwh": IT_VALUE_PER_MWH,
            "units": "USD/MWh of served data-center load",
            "context": (
                "Between colocation rent (about $270/MWh of IT load) and GPU-cloud "
                "revenue (about $1,700/MWh); 1,000 $/MWh is a round instructional net margin."
            ),
            "break_even_served_fraction": round(break_even_fraction, 4),
            "break_even_note": (
                "site cost / (IT value x 8760 h x A) = 25e6 / (1000 x 8760 x A): a site must be "
                "served about 41% of its connection capacity on average to recover its site cost."
            ),
        },
        "generator_provenance": {
            "capital_cost_per_kw": GENERATOR_CAPITAL_COST_PER_MW / 1000.0,
            "capital_cost_basis": (
                "Installed on-site gas engines and aeroderivative turbines cost about "
                "$1,700-2,000/kW (Rabobank 2026, https://www.rabobank.com/knowledge/"
                "d011524694-the-sprint-data-centers-are-building-a-parallel-energy-system-in-the-us); "
                "EIA-based figures in a Texas PUC filing give about $1,430/kW for aeroderivative "
                "turbines and $2,240/kW for internal-combustion engines. $2,000/kW is a round "
                "instructional value in that range."
            ),
            "operating_cost": "piecewise 80/150/250 $/MWh over 25/50/25% of capacity (unchanged)",
            "max_generator_to_connection_ratio_basis": (
                "G <= 0.5 x C. Texas SB 6 (2025) treats on-site backup generation that can serve "
                "at least 50% of a large load's demand as backup ERCOT may call on in emergencies "
                "(https://www.utilitydive.com/news/texas-law-gives-grid-operator-power-to-"
                "disconnect-data-centers-during-crisis/751587)."
            ),
            "daily_energy_hours": GENERATOR_DAILY_ENERGY_HOURS,
            "daily_energy_rule": (
                "sum over the 24 periods of each representative day of g_t x time_step_hours "
                "<= generator_daily_energy_hours x G, for every team generator; the evaluator "
                "dispatches budgeted generators in one coupled LP per day."
            ),
            "daily_energy_basis": (
                "Air permits cap the run hours of on-site engines: federal emergency-engine rules "
                "allow 100 h/yr of maintenance and testing, of which at most 50 h non-emergency "
                "operation, and state permits often cap total operation (e.g. under 500 h/yr in a "
                "Georgia EPD draft permit). A 2 h/day budget (about 730 h/yr) is a teaching choice "
                "in that range that makes the generator a peak-shaving device rather than baseload."
            ),
        },
        "storage_cost_provenance": {
            "currency_year": "2022 USD for capital benchmarks; nominal instructional coefficients",
            "power_capital_cost_per_kw": 400.0,
            "energy_capital_cost_per_kwh": 250.0,
            "basis": "rounded 2028 moderate four-hour projection from NREL's 2023 utility-scale battery cost update",
            "evaluator_mapping": "Storage operating cost is not charged; one exact daily cycle per representative day, starting and ending at half energy.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--package-dir", type=Path, default=Path("data/processed/activsg2000_representative_v1"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/teaching/dispatch_scoring_rules_representative_v1.json"),
    )
    args = parser.parse_args(argv)
    payload = build_rules(args.package_dir)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "rules_version": payload["rules_version"],
                "present_value_annuity_factor": payload["present_value_annuity_factor"],
                "break_even_served_fraction": payload["it_value_provenance"]["break_even_served_fraction"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
