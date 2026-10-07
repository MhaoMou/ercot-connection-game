"""Black-box reproducibility checks for the Phase 1 evaluator CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


PROJECT_ROOT = Path(__file__).parents[1]
SCENARIO = PROJECT_ROOT / "data/fixtures/ercot_small.json"
SUBMISSIONS = PROJECT_ROOT / "examples/week_01_submissions.json"


def _run_evaluate(submissions: Path, output: Path) -> bytes:
    environment = {"PYTHONPATH": str(PROJECT_ROOT / "src")}
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "ercot_game.cli",
            "evaluate",
            "--scenario",
            str(SCENARIO),
            "--submissions",
            str(submissions),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode()
    assert process.stdout == b""
    assert process.stderr == b""
    return output.read_bytes()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_evaluate_is_byte_for_byte_reproducible(tmp_path: Path):
    first = _run_evaluate(SUBMISSIONS, tmp_path / "first.json")
    second = _run_evaluate(SUBMISSIONS, tmp_path / "second.json")

    assert first == second
    assert _sha256(first) == _sha256(second)


def test_evaluate_is_independent_of_submission_order(tmp_path: Path):
    submissions = json.loads(SUBMISSIONS.read_text(encoding="utf-8"))
    reversed_submissions = tmp_path / "reversed-submissions.json"
    reversed_submissions.write_text(
        json.dumps(list(reversed(submissions)), indent=2) + "\n", encoding="utf-8"
    )

    original = _run_evaluate(SUBMISSIONS, tmp_path / "original.json")
    reversed_order = _run_evaluate(reversed_submissions, tmp_path / "reversed.json")

    assert original == reversed_order
    assert _sha256(original) == _sha256(reversed_order)


def test_evaluation_output_contains_audit_and_score_contract(tmp_path: Path):
    output = _run_evaluate(SUBMISSIONS, tmp_path / "results.json")
    output_text = output.decode("utf-8")
    payload = json.loads(output_text)

    # The CLI contract is canonical pretty JSON: recursive sorted keys, two-space
    # indentation, and exactly one trailing newline.
    assert output_text == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert output_text.endswith("\n")
    assert not output_text.endswith("\n\n")

    assert payload["scenario_id"] == "ercot-small-week-01"
    assert re.fullmatch(r"[0-9a-f]{64}", payload["input_hash"])
    assert payload["aggregate_diagnostics"]["evaluator_version"] == "0.3.0"
    assert payload["aggregate_diagnostics"]["team_count"] == len(
        payload["team_results"]
    )
    assert payload["aggregate_diagnostics"]["binding_resource_diagnostics"]

    assert payload["team_results"]
    for team_result in payload["team_results"]:
        assert team_result["team_id"]
        assert "diagnostics" in team_result
        assert "score_breakdown" in team_result
        assert {
            "it_value",
            "energy_cost",
            "generator_cost",
            "flexibility_fee",
            "curtailment_cost",
            "unserved_penalty",
            "total",
        } <= team_result["score_breakdown"].keys()
