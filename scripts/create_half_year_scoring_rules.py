#!/usr/bin/env python3
"""Generate the two literal-hour scoring-rule files for the course game."""

from __future__ import annotations

import json
from pathlib import Path


PROFILE_PRICES = (68.02, 39.16, 19.99, 18.42, 53.14, 46.49)
PROFILE_IT_VALUE = (118.0, 121.0, 127.0, 135.0, 129.0, 115.0)


def build_rules(*, label: str, horizon: int) -> dict[str, object]:
    repetitions, remainder = divmod(horizon, len(PROFILE_PRICES))
    assert remainder == 0
    return {
        "rules_version": f"dispatch-scoring-{label}-v1",
        "status": "instructor_review_required",
        "description": (
            "Literal one-hour scoring rules for the Zenodo Texas dispatch game. "
            "The price/value profile is a reproducible instructional diurnal "
            "profile repeated across the selected half-year; it is not a claim "
            "of an hourly ERCOT market forecast."
        ),
        "it_value_per_mwh": list(PROFILE_IT_VALUE) * repetitions,
        "energy_price_per_mwh": list(PROFILE_PRICES) * repetitions,
        "time_step_hours": 1.0,
        "generator_capital_cost_per_mw": 85000.0,
        "site_cost_per_site": 50000.0,
        "infeasible_score": 0.0,
        "default_generator_cost_per_mwh": 100.0,
        "storage_capital_cost_per_mw": 200000.0,
        "storage_capital_cost_per_mwh": 300000.0,
        "storage_operating_cost_per_mwh": 8.0,
        "time_step_hours_provenance": {
            "interpretation": "literal hourly interval",
            "horizon_hours": horizon,
            "calendar_block": label,
        },
        "vector_generation": {
            "method": "repeat six-hour instructional profile",
            "profile_hours": [1, 6, 11, 13, 20, 23],
            "note": "The repeated profile is a teaching assumption pending an approved hourly market-price series.",
        },
        "storage_cost_provenance": {
            "currency_year": "2022 USD for capital benchmarks; nominal instructional coefficients",
            "power_capital_cost_per_kw": 200.0,
            "energy_capital_cost_per_kwh": 300.0,
            "four_hour_total_cost_per_kw": 1400.0,
            "fixed_om_reference_per_kw_year": 40.0,
            "variable_om_proxy_per_mwh": 8.0,
            "basis": "rounded teaching split calibrated to EIA and NREL utility-scale battery benchmarks",
            "sources": [
                "https://www.eia.gov/electricity/generatorcosts/",
                "https://www.eia.gov/analysis/studies/powerplants/capitalcost/pdf/capcost_assumption.pdf",
                "https://atb.nrel.gov/electricity/2021/utility-scale_battery_storage",
                "https://atb.nrel.gov/electricity/2024/2023/utility-scale_battery_storage",
            ],
            "evaluator_mapping": "The current evaluator charges storage operation per discharged MWh; fixed O&M is retained as a reference rather than double-counted.",
        },
        "energy_price_provenance": {
            "market_anchor": "ERCOT Day-Ahead Market HB_HUBAVG representative observations",
            "source_url": "https://www.ercot.com/content/cdr/html/dam_spp.html",
            "profile": list(PROFILE_PRICES),
            "profile_hour_ending": [1, 6, 11, 13, 20, 23],
        },
        "it_value_provenance": {
            "basis": "instructional value of computational service",
            "profile": list(PROFILE_IT_VALUE),
        },
    }


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "data" / "teaching"
    for label, horizon in (("jan_jun", 4368), ("jul_dec", 4416)):
        path = output_dir / f"dispatch_scoring_rules_{label}_v1.json"
        path.write_text(json.dumps(build_rules(label=label, horizon=horizon), indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
