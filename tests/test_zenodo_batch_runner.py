from __future__ import annotations

import csv
import json
from types import SimpleNamespace
import pytest

pytest.importorskip("highspy")

from tools.zenodo_texas.batch_runner import (
    BatchScoringRules,
    evaluate_csv_batch,
    write_batch_outputs,
)
from ercot_game.csv_submission import CSV_COLUMNS


def _submission(path, team_id: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow({
            "team_id": team_id,
            "submission_id": "week-1",
            "period": 1,
            "site_id": "PANHANDLE",
            "load_mw": 2,
            "generator_id": "14023",
            "generator_capacity_mw": 1,
            "storage_id": "",
            "storage_power_mw": "",
            "storage_energy_mwh": "",
        })


def test_batch_runner_scores_and_writes_audit_outputs(tmp_path):
    first = tmp_path / "team-1.csv"
    second = tmp_path / "team-2.csv"
    _submission(first, "team-1")
    _submission(second, "team-2")
    rules = BatchScoringRules(
        rules_version="test-v1",
        it_value_per_mwh=(200.0,),
        energy_price_per_mwh=(50.0,),
        generator_capital_cost_per_mw=10.0,
        site_cost_per_site=5.0,
    )

    result = evaluate_csv_batch(
        (first, second),
        artifact_dir="data/processed/texas_dispatch_source_v1",
        region_to_source_bus={"PANHANDLE": "3001003"},
        horizon=1,
        rules=rules,
    )
    write_batch_outputs(result, tmp_path / "out")

    assert [score.team_id for score in result.team_scores] == ["team-1", "team-2"]
    assert all(score.feasible for score in result.team_scores)
    assert all(score.served_load_mwh == 2.0 for score in result.team_scores)
    assert (tmp_path / "out" / "leaderboard.csv").exists()
    payload = json.loads((tmp_path / "out" / "evaluation.json").read_text())
    assert payload["rules_version"] == "test-v1"
    assert set(payload["input_sha256_by_team"]) == {"team-1", "team-2"}


def test_batch_runner_writer_forwards_all_fallback_period_indices(monkeypatch, tmp_path):
    captured = {}

    def capture_write(evaluation, output_dir, **kwargs):
        captured["evaluation"] = evaluation
        captured["output_dir"] = output_dir
        captured.update(kwargs)

    monkeypatch.setattr("tools.zenodo_texas.batch_runner._write_batch_outputs", capture_write)
    evaluation = SimpleNamespace(
        dispatch=None,
        dispatch_records=(
            SimpleNamespace(
                dispatch=SimpleNamespace(
                    periods=(SimpleNamespace(period_index=2), SimpleNamespace(period_index=0))
                )
            ),
            SimpleNamespace(
                dispatch=SimpleNamespace(
                    periods=(SimpleNamespace(period_index=1), SimpleNamespace(period_index=2))
                )
            ),
        ),
    )

    write_batch_outputs(evaluation, tmp_path / "out")

    assert captured["period_indices"] == (0, 1, 2)


def test_batch_runner_scores_moderate_team_and_isolates_oversized_team(tmp_path):
    moderate = tmp_path / "team-a.csv"
    oversized = tmp_path / "team-b.csv"
    _submission(moderate, "team-a")
    _submission(oversized, "team-b")
    rules = BatchScoringRules(
        rules_version="test-v1",
        it_value_per_mwh=(200.0,),
        energy_price_per_mwh=(50.0,),
        infeasible_score=-123.0,
    )

    rows = list(csv.DictReader(oversized.open(newline="", encoding="utf-8")))
    rows[0]["load_mw"] = "1000000"
    with oversized.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    result = evaluate_csv_batch(
        (moderate, oversized),
        artifact_dir="data/processed/texas_dispatch_source_v1",
        region_to_source_bus={"PANHANDLE": "3001003"},
        horizon=1,
        rules=rules,
    )

    scores = {score.team_id: score for score in result.team_scores}
    assert result.competition_scope == "joint_projection"
    assert scores["team-a"].feasible is True
    assert scores["team-a"].score != rules.infeasible_score
    assert 0.0 < scores["team-a"].served_load_mwh < 2.0
    assert scores["team-b"].feasible is True
    assert scores["team-b"].score != rules.infeasible_score
    recovery = next(
        event for event in result.isolation_events if event.outcome == "joint_projected"
    )
    assert recovery.removed_team_id is None
    assert result.dispatch is not None
