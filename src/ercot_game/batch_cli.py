"""Instructor-facing command line entry point for CSV batch evaluation."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import NoReturn

from .batch_evaluation import (
    evaluate_csv_batch,
    load_scoring_rules,
    write_batch_outputs,
)


class _ParserExit(Exception):
    def __init__(self, status: int) -> None:
        self.status = status


class _ArgumentParser(argparse.ArgumentParser):
    """Argument parser whose exits can be returned by ``main`` in tests."""

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if message:
            self._print_message(message, sys.stderr if status else sys.stdout)
        raise _ParserExit(status)

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _period_indices(value: str) -> tuple[int, ...]:
    pieces = [piece.strip() for piece in value.split(",")]
    if not value.strip() or any(not piece for piece in pieces):
        raise argparse.ArgumentTypeError(
            "must be a comma-separated list of non-negative integers"
        )
    try:
        indices = tuple(int(piece) for piece in pieces)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "must be a comma-separated list of non-negative integers"
        ) from None
    if any(index < 0 for index in indices):
        raise argparse.ArgumentTypeError("must contain only non-negative integers")
    if len(set(indices)) != len(indices):
        raise argparse.ArgumentTypeError("must not contain duplicate indices")
    return indices


def _source_period_offset(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be 0 or 4368") from None
    if parsed not in (0, 4368):
        raise argparse.ArgumentTypeError("must be 0 or 4368")
    return parsed


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load {label} {path}: {exc}") from None


def _load_region_map(path: Path) -> dict[str, str]:
    payload = _read_json(path, "region map")
    if not isinstance(payload, Mapping):
        raise ValueError("region map JSON must be an object")
    regions = payload.get("regions", payload)
    if not isinstance(regions, Mapping) or not regions:
        raise ValueError("region map must contain a non-empty object of regions")

    result: dict[str, str] = {}
    for region, value in regions.items():
        if not isinstance(region, str) or not region:
            raise ValueError("region map keys must be non-empty strings")
        if isinstance(value, Mapping):
            source_bus = value.get("source_bus_id", value.get("source_bus"))
        else:
            source_bus = value
        if not isinstance(source_bus, str) or not source_bus:
            raise ValueError(f"region map entry {region!r} must provide source_bus_id")
        result[region] = source_bus
    return result


def _evaluator_version() -> str:
    try:
        return importlib.metadata.version("ercot-game")
    except importlib.metadata.PackageNotFoundError:
        return "0.3.0"


def _summary(result) -> str:
    scored = sum(score.valid for score in result.team_scores)
    rejected = sum(not score.valid for score in result.team_scores)
    scored_label = "team" if scored == 1 else "teams"
    return (
        f"summary: {scored} {scored_label} scored, {rejected} rejected, "
        f"scope={result.competition_scope}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Run the instructor-side ERCOT CSV batch evaluator"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="evaluate a directory of submissions")
    run_parser.add_argument("--submissions-dir", required=True, type=Path)
    run_parser.add_argument("--artifact-dir", required=True, type=Path)
    run_parser.add_argument("--rules", required=True, type=Path)
    run_parser.add_argument("--output-dir", required=True, type=Path)
    run_parser.add_argument("--horizon", required=True, type=_positive_int)
    run_parser.add_argument(
        "--workers",
        required=False,
        type=_positive_int,
        default=1,
        help="parallel hourly DCOPF workers; output order remains deterministic",
    )
    run_parser.add_argument(
        "--projection-iterations",
        required=False,
        type=_positive_int,
        default=10,
        help="bisection iterations for fair continuous projection",
    )
    run_parser.add_argument(
        "--period-indices",
        required=False,
        type=_period_indices,
        help="optional comma-separated zero-based local scoring periods; defaults to the full horizon",
    )
    run_parser.add_argument(
        "--source-period-offset",
        required=False,
        type=_source_period_offset,
        default=None,
        help="source-artifact row offset: 0 for Jan-Jun or 4368 for Jul-Dec; inferred from horizon when omitted",
    )
    run_parser.add_argument(
        "--region-map",
        required=False,
        type=Path,
        help="deprecated legacy region map; new submissions use artifact bus IDs directly",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    if not args.artifact_dir.is_dir():
        raise ValueError(
            f"artifact directory does not exist or is not a directory: {args.artifact_dir}"
        )
    region_to_source_bus = _load_region_map(args.region_map) if args.region_map else None
    rules = load_scoring_rules(args.rules)
    period_indices = (
        tuple(range(args.horizon))
        if args.period_indices is None
        else args.period_indices
    )
    result = evaluate_csv_batch(
        args.submissions_dir,
        artifact_dir=args.artifact_dir,
        region_to_source_bus=region_to_source_bus,
        horizon=args.horizon,
        rules=rules,
        period_indices=period_indices,
        source_period_offset=args.source_period_offset,
        dispatch_workers=args.workers,
        projection_iterations=args.projection_iterations,
    )
    write_batch_outputs(
        result,
        args.output_dir,
        scenario_version=args.artifact_dir.name,
        evaluator_version=_evaluator_version(),
        period_indices=period_indices,
        source_period_indices=result.source_period_indices,
    )
    print(f"output directory: {args.output_dir.resolve()}")
    print(_summary(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command != "run":
            parser.error("a command is required")
        return _run(args)
    except _ParserExit as exc:
        return exc.status
    except (OSError, UnicodeDecodeError, csv.Error, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
