from __future__ import annotations

import json
from pathlib import Path

from ercot_game.batch_evaluation import load_scoring_rules


ROOT = Path(__file__).parents[1]


def test_half_year_rules_have_complete_hourly_vectors_and_storage_costs():
    for filename, horizon in (
        ("dispatch_scoring_rules_jan_jun_v1.json", 4368),
        ("dispatch_scoring_rules_jul_dec_v1.json", 4416),
    ):
        path = ROOT / "data" / "teaching" / filename
        rules = load_scoring_rules(path)
        assert len(rules.energy_price_per_mwh) == horizon
        assert len(rules.it_value_per_mwh) == horizon
        assert rules.time_step_hours == 1.0
        assert rules.storage_capital_cost_per_mw == 200_000.0
        assert rules.storage_capital_cost_per_mwh == 300_000.0
        assert rules.storage_operating_cost_per_mwh == 8.0


def test_half_year_rules_record_storage_provenance_and_generation_method():
    path = ROOT / "data" / "teaching" / "dispatch_scoring_rules_jan_jun_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["time_step_hours_provenance"]["interpretation"] == "literal hourly interval"
    assert payload["storage_cost_provenance"]["fixed_om_reference_per_kw_year"] == 40.0
    assert payload["vector_generation"]["method"] == "repeat six-hour instructional profile"

