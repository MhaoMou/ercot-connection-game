"""Team generator rules: G <= C, any hour, no daily run-hour budget."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ercot_game.batch_evaluation import BatchScoringRules, load_scoring_rules

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_released_rules_have_no_budget_and_allow_off_grid_sites() -> None:
    for name in (
        "dispatch_scoring_rules_representative_v1.json",
        "dispatch_scoring_rules_ieee14_demo_representative_v1.json",
    ):
        payload = json.loads((REPO_ROOT / "data" / "teaching" / name).read_text(encoding="utf-8"))
        assert payload.get("generator_daily_energy_hours") is None
        assert payload["generator_capital_cost_per_mw"] == 2_000_000.0
        assert payload["max_generator_to_connection_ratio"] == 1.0
        assert payload["max_team_connection_capacity_mw"] == 1_000.0
        assert "off the grid" in payload["generator_provenance"]["max_generator_to_connection_ratio_basis"]


def test_rules_reject_a_generator_run_hour_budget(tmp_path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"rules_version": "x"}), encoding="utf-8")
    assert isinstance(load_scoring_rules(path), BatchScoringRules)
    path.write_text(
        json.dumps({"rules_version": "x", "generator_daily_energy_hours": None}), encoding="utf-8"
    )
    assert isinstance(load_scoring_rules(path), BatchScoringRules)
    path.write_text(
        json.dumps({"rules_version": "x", "generator_daily_energy_hours": 2}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="generator_daily_energy_hours is no longer supported"):
        load_scoring_rules(path)


def test_auto_backend_skips_a_size_limited_gurobi_license(monkeypatch) -> None:
    # The free pip license starts an environment but cannot solve a full DCOPF;
    # "auto" must then fall back to HiGHS instead of failing mid-evaluation.
    gp = pytest.importorskip("gurobipy")
    from tools.activsg2000 import dcopf

    def size_limited(self):
        raise gp.GurobiError(10010, "Model too large for size-limited license")

    monkeypatch.setattr(gp.Model, "optimize", size_limited)
    assert dcopf.gurobi_is_available() is False
    assert dcopf.resolve_solver_backend("auto") == "highs"
