"""Command-line interface for the deterministic offline evaluator."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys

from .evaluator import (
    DEFAULT_EVALUATION_CONFIG,
    EvaluationInputError,
    evaluate_week,
    resolve_evaluation_config,
)
from .io import plan_from_dict, scenario_from_dict
from .models import EvaluationConfig, EvaluationResult, Scenario, TeamPlan
from .planning_adapter import load_teaching_scenario


def _read_json(path: Path, label: str) -> object:
    try:
        with path.open(encoding="utf-8") as input_file:
            return json.load(input_file)
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationInputError((f"could not load {label} {path}: {error}",)) from None


def _load_scenario(path: Path) -> Scenario:
    payload = _read_json(path, "scenario")
    if not isinstance(payload, Mapping):
        raise EvaluationInputError(("scenario JSON must be an object",))
    try:
        if payload.get("scenario_schema") == "ercot.teaching-scenario.v1":
            model_path = path.resolve().parents[1] / "processed" / "ercot_planning_model_v1.json"
            if not model_path.exists():
                model_path = Path(__file__).resolve().parents[2] / "data/processed/ercot_planning_model_v1.json"
            return load_teaching_scenario(path, model_path)
        return scenario_from_dict(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationInputError((f"scenario payload is malformed: {error}",)) from None


def _load_submissions(path: Path) -> tuple[tuple[TeamPlan, ...], Mapping[str, object] | None]:
    payload = _read_json(path, "submissions")
    embedded_config: Mapping[str, object] | None = None
    if isinstance(payload, list):
        plan_payloads: object = payload
    elif isinstance(payload, Mapping) and "plans" in payload:
        plan_payloads = payload["plans"]
        candidate_config = payload.get("configuration", payload.get("config"))
        if candidate_config is not None:
            if not isinstance(candidate_config, Mapping):
                raise EvaluationInputError(("submissions configuration must be an object",))
            embedded_config = candidate_config
    else:
        raise EvaluationInputError(
            ("submissions JSON must be an array or an object containing plans",)
        )
    if not isinstance(plan_payloads, list):
        raise EvaluationInputError(("submissions plans must be an array",))

    plans: list[TeamPlan] = []
    errors: list[str] = []
    for index, plan_payload in enumerate(plan_payloads):
        if not isinstance(plan_payload, Mapping):
            errors.append(f"submission[{index}] must be an object")
            continue
        try:
            plans.append(plan_from_dict(plan_payload))
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"submission[{index}] payload is malformed: {error}")
    if errors:
        raise EvaluationInputError(errors)
    return tuple(plans), embedded_config


def _configuration_from_inputs(
    scenario: Scenario, embedded_config: Mapping[str, object] | None
) -> EvaluationConfig:
    return resolve_evaluation_config(scenario, embedded_config)


def _result_to_dict(result: EvaluationResult) -> dict[str, object]:
    return {
        "scenario_id": result.scenario_id,
        "input_hash": result.input_hash,
        "team_results": result.team_results,
        "aggregate_diagnostics": result.aggregate_diagnostics,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic ERCOT offline evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate a scenario and submissions")
    validate_parser.add_argument("--scenario", required=True, type=Path)
    validate_parser.add_argument("--submissions", required=True, type=Path)

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate a scenario and submissions")
    evaluate_parser.add_argument("--scenario", required=True, type=Path)
    evaluate_parser.add_argument("--submissions", required=True, type=Path)
    evaluate_parser.add_argument("--output", required=True, type=Path)
    return parser


def _run(args: argparse.Namespace) -> None:
    scenario = _load_scenario(args.scenario)
    plans, embedded_config = _load_submissions(args.submissions)
    config = _configuration_from_inputs(scenario, embedded_config)
    result = evaluate_week(scenario, config, plans)
    if args.command == "validate":
        print("valid")
        return

    output_payload = _result_to_dict(result)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output_payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as error:
        raise EvaluationInputError((f"could not write output {args.output}: {error}",)) from None


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _run(args)
    except EvaluationInputError as error:
        for message in error.errors:
            print(f"error: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
