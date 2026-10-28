"""End-to-end student workflow on the IEEE-14 teaching-demo package."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

from ercot_game import batch_cli, csv_validator, hosting_capacity_cli, student_preview
from ercot_game.batch_evaluation import load_scoring_rules
from ercot_game.csv_submission import CANONICAL_CSV_COLUMNS
from ercot_game.scenario_package import (
    IEEE14_DEMO_PACKAGE_VERSION,
    ScenarioPackageError,
    load_scenario_manifest,
    representative_day_weights,
    require_validated_block,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO = REPO_ROOT / "data" / "teaching" / "ieee14_demo_representative"
DEMO_RULES = REPO_ROOT / "data" / "teaching" / "dispatch_scoring_rules_ieee14_demo_representative_v1.json"
MAIN_PACKAGE = REPO_ROOT / "data" / "processed" / "activsg2000_representative_v1"
RELEASED_RULES = REPO_ROOT / "data" / "teaching" / "dispatch_scoring_rules_representative_v1.json"
HORIZON = 120
PEAK_PERIOD = 109  # 2028-09-15 (peak day), 13:00-14:00


def _write_plan(path: Path, team_id: str, sites: list[tuple[str, str, float, float, float]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CANONICAL_CSV_COLUMNS)
        for site_id, bus_id, capacity, storage_mw, storage_mwh in sites:
            writer.writerow((team_id, site_id, bus_id, capacity, 0, storage_mw, storage_mwh))
    return path


def _two_team_dir(root: Path, *, bus13_mw: float, bus14_mw: float) -> Path:
    root.mkdir()
    _write_plan(root / "team-a.csv", "team-a", [("site-a1", "13", bus13_mw, 0, 0)])
    _write_plan(root / "team-b.csv", "team-b", [("site-b1", "14", bus14_mw, 0, 0)])
    return root


def test_demo_package_uses_the_main_representative_days_and_weights():
    manifest = load_scenario_manifest(DEMO)
    assert manifest["package_version"] == IEEE14_DEMO_PACKAGE_VERSION
    assert set(manifest["blocks"]) == {"representative"}
    assert require_validated_block(DEMO)["horizon"] == HORIZON
    main = json.loads((MAIN_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert representative_day_weights(DEMO) == pytest.approx(main["day_weights"])
    assert manifest["period_day_weights"] == pytest.approx(main["period_day_weights"])
    assert [day["date"] for day in manifest["representative_days"]] == [
        "2028-01-03", "2028-05-10", "2028-07-12", "2028-09-10", "2028-09-15",
    ]
    with (DEMO / "demand_bus.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == HORIZON
    assert set(rows[0]) - {"period"} == {str(bus) for bus in range(1, 15)}
    totals = [sum(float(value) for key, value in row.items() if key != "period") for row in rows]
    assert max(range(HORIZON), key=totals.__getitem__) == PEAK_PERIOD
    assert manifest["validation"]["passed_period_count"] == HORIZON


def test_demo_manifest_rejects_a_wrong_horizon_or_block(tmp_path):
    payload = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
    payload["horizon"] = 168
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScenarioPackageError, match="representative block"):
        require_validated_block(tmp_path)
    payload["horizon"] = HORIZON
    payload["blocks"] = {"ieee14_demo_week": payload["blocks"]["representative"]}
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScenarioPackageError, match="representative block"):
        load_scenario_manifest(tmp_path)


def test_demo_rules_are_the_main_release_economics():
    demo = json.loads(DEMO_RULES.read_text(encoding="utf-8"))
    released = json.loads(RELEASED_RULES.read_text(encoding="utf-8"))
    differing = {key for key in set(demo) | set(released) if demo.get(key) != released.get(key)}
    assert differing <= {"rules_version", "status", "description", "scenario_package"}
    assert demo["scenario_package"] == IEEE14_DEMO_PACKAGE_VERSION
    assert demo["it_value_per_mwh"] == [1000.0] * HORIZON
    assert demo["site_cost_per_mw"] == 25_000_000.0
    assert demo["max_generator_to_connection_ratio"] == 0.5
    assert demo["it_value_provenance"]["break_even_served_fraction"] == pytest.approx(0.406, abs=0.001)
    rules = load_scoring_rules(DEMO_RULES, artifact_dir=DEMO, horizon=HORIZON)
    assert rules.storage_boundary_mode == "daily_exact_cycle"


def test_check_csv_accepts_two_site_plan_and_rejects_unknown_bus(tmp_path, capsys):
    valid = _write_plan(
        tmp_path / "team-a.csv",
        "team-a",
        [("site-a1", "13", 20, 0, 0), ("site-a2", "4", 40, 5, 20)],
    )
    assert csv_validator.main(["--file", str(valid), "--artifact-dir", str(DEMO)]) == 0
    assert "VALID" in capsys.readouterr().out
    invalid = _write_plan(tmp_path / "team-c.csv", "team-c", [("site-c1", "15", 10, 0, 0)])
    assert csv_validator.main(["--file", str(invalid), "--artifact-dir", str(DEMO)]) == 1
    assert "unknown scenario bus 15" in capsys.readouterr().out


def test_hosting_capacity_differs_by_bus_in_the_peak_period(tmp_path, capsys):
    pytest.importorskip("highspy")
    output_dir = tmp_path / "hc"
    code = hosting_capacity_cli.main(
        [
            "--artifact-dir", str(DEMO),
            "--start-period", str(PEAK_PERIOD),
            "--period-count", "1",
            "--solver-backend", "highs",
            "--output-dir", str(output_dir),
            "--write-long-form",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert code == 0
    assert summary["complete"] and summary["failed_point_count"] == 0
    with gzip.open(output_dir / "hosting_capacity_long.csv.gz", "rt", newline="", encoding="utf-8") as handle:
        by_bus = {row["bus_id"]: float(row["hosting_capacity_mw"]) for row in csv.DictReader(handle)}
    assert len(by_bus) == 14
    assert by_bus["2"] > 300.0
    assert by_bus["13"] == pytest.approx(50.8, abs=0.5)
    assert by_bus["14"] == pytest.approx(37.6, abs=0.5)
    assert 20.0 < by_bus["14"] < 60.0
    assert 20.0 < by_bus["13"] < 60.0
    # Buses 13 and 14 share the 9-14 / 6-13 bottleneck.
    assert by_bus["13"] + by_bus["14"] > 75.0


def test_preview_and_batch_run_end_to_end_on_a_fitting_plan(tmp_path, capsys):
    pytest.importorskip("highspy")
    submissions = _two_team_dir(tmp_path / "fit", bus13_mw=20, bus14_mw=20)
    # Storage exercises the daily_exact_cycle with 24 one-hour periods per day.
    _write_plan(submissions / "team-b.csv", "team-b", [("site-b1", "14", 20, 5, 20)])
    preview_path = tmp_path / "preview.json"
    assert student_preview.main(
        [
            "--submissions-dir", str(submissions),
            "--artifact-dir", str(DEMO),
            "--rules", str(DEMO_RULES),
            "--week", "3",
            "--workers", "1",
            "--output", str(preview_path),
        ]
    ) == 0
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    assert preview["checked_period_count"] == HORIZON
    assert {score["team_id"]: score["feasible"] for score in preview["team_scores"]} == {
        "team-a": True,
        "team-b": True,
    }

    output_dir = tmp_path / "batch"
    assert batch_cli.main(
        [
            "run",
            "--submissions-dir", str(submissions),
            "--artifact-dir", str(DEMO),
            "--rules", str(DEMO_RULES),
            "--output-dir", str(output_dir),
            "--week", "1",
        ]
    ) == 0
    capsys.readouterr()
    evaluation = json.loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert evaluation["competition_scope"] == "joint"
    served = {score["team_id"]: score["served_load_mwh"] for score in evaluation["team_scores"]}
    # Served load is reported per represented year.
    assert served == pytest.approx({"team-a": 20 * 8760, "team-b": 20 * 8760})
    storage_cost = {score["team_id"]: score["storage_capital_cost"] for score in evaluation["team_scores"]}
    assert storage_cost["team-a"] == 0.0 and storage_cost["team-b"] > 0.0


def test_batch_projects_joint_requests_at_the_shared_bottleneck(tmp_path, capsys):
    pytest.importorskip("highspy")
    submissions = _two_team_dir(tmp_path / "clash", bus13_mw=30, bus14_mw=30)
    output_dir = tmp_path / "batch"
    assert batch_cli.main(
        [
            "run",
            "--submissions-dir", str(submissions),
            "--artifact-dir", str(DEMO),
            "--rules", str(DEMO_RULES),
            "--output-dir", str(output_dir),
            "--week", "1",
        ]
    ) == 0
    assert "scope=joint_projection" in capsys.readouterr().out
    evaluation = json.loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
    projection = evaluation["projection_diagnostics"]
    assert projection["objective"] == "uniform_rule_max_min_capacity"
    projected = projection["projected_capacity_mw_by_team"]
    # Symmetric requests: the uniform rule gives both teams the same level.
    assert projected["team-a"] == pytest.approx(projected["team-b"], abs=0.1)
    assert 15.0 <= projected["team-a"] < 30.0
