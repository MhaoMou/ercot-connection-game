"""Instructor-facing command line entry point for CSV batch evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import NoReturn

from .batch_evaluation import (
    evaluate_csv_batch,
    load_scoring_rules,
    write_classroom_outputs,
    write_batch_outputs,
)
from .base_load import (
    materialize_base_load_artifact,
    net_withdrawal_by_bus,
    read_site_net_withdrawal,
    site_ids_by_team,
)
from .calendars import HALF_YEAR_SCHEDULE_ID, half_year_calendar, round_sequence
from .temporal_aggregation import aggregated_horizon
from .round_coordinator import ClassroomRoundInput, evaluate_classroom
from .release_config import (
    LEGACY_TIME_STEP_HOURS,
    canonical_artifact_dir,
    canonical_release_artifact_dir,
    canonical_release_rules_path,
    canonical_rules_path,
    week_energy_cost_enabled,
)
from .scenario_package import REPRESENTATIVE_PACKAGE_VERSIONS


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
        raise argparse.ArgumentTypeError("must be 0, 4344, or 4368") from None
    if parsed not in (0, 4344, 4368):
        raise argparse.ArgumentTypeError("must be 0, 4344, or 4368")
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


def _artifact_manifest(artifact_dir: Path) -> Mapping[str, object]:
    path = artifact_dir / "manifest.json"
    if not path.is_file():
        return {}
    payload = _read_json(path, "artifact manifest")
    return payload if isinstance(payload, Mapping) else {}


def _is_representative(artifact_dir: Path) -> bool:
    return _artifact_manifest(artifact_dir).get("package_version") in REPRESENTATIVE_PACKAGE_VERSIONS


def _manifest_horizon(artifact_dir: Path) -> int | None:
    """Horizon of a single-block (demand_bus.csv) artifact, if declared."""
    if (artifact_dir / "scenario_profile.json").is_file():
        return None
    horizon = _artifact_manifest(artifact_dir).get("horizon")
    if isinstance(horizon, int) and not isinstance(horizon, bool) and horizon > 0:
        return horizon
    return None


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
    run_parser.add_argument("--artifact-dir", type=Path)
    run_parser.add_argument("--rules", type=Path)
    run_parser.add_argument("--output-dir", required=True, type=Path)
    run_parser.add_argument("--horizon", type=_positive_int)
    run_parser.add_argument("--year", type=int, choices=(2027, 2028, 2029), help="retired half-year release: scenario year")
    run_parser.add_argument("--round", dest="round_name", choices=("jan_jun", "jul_dec"), help="retired half-year release: half-year")
    run_parser.add_argument(
        "--time-step-hours",
        type=_positive_int,
        choices=(1, 6),
        default=LEGACY_TIME_STEP_HOURS,
        help="retired half-year release only: interval of one period with --year/--round (default 6)",
    )
    run_parser.add_argument(
        "--submission-number",
        type=int,
        choices=(1, 2),
        default=None,
        help=(
            "weekly submission number (default 1 for the representative release, 2 otherwise); "
            "for the retired half-year release it also sets the energy charge (1 = none, 2 = LMP)"
        ),
    )
    run_parser.add_argument(
        "--energy-cost",
        choices=("on", "off"),
        help="charge grid purchases at the joint-dispatch LMP (on) or not (off); required for the representative release unless --week is given",
    )
    run_parser.add_argument(
        "--week",
        type=int,
        choices=(1, 2, 3),
        help="representative release week; sets the energy charge (weeks 1-2 off, week 3 on)",
    )
    run_parser.add_argument(
        "--base-load-from",
        type=Path,
        help="Submission 2: Submission 1 output directory whose site_net_withdrawal.csv becomes base load",
    )
    run_parser.add_argument(
        "--base-load-artifact-dir",
        type=Path,
        help="where to write the derived Submission 2 artifact (default: <output-dir>/base_load_artifact)",
    )
    run_parser.add_argument(
        "--skip-base-load-validation",
        action="store_true",
        help="do not re-solve every period of the derived Submission 2 artifact",
    )
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
        "--output-mode",
        choices=("full", "compact"),
        default="full",
        help="full writes per-period dispatch JSON; compact writes scores, manifests, diagnostics, and hashes only",
    )
    run_parser.add_argument(
        "--solver-backend",
        choices=("auto", "highs", "gurobi"),
        default="auto",
        help="storage recourse LP backend; auto uses licensed Gurobi when available, otherwise HiGHS",
    )
    run_parser.add_argument(
        "--solver-threads",
        type=_positive_int,
        default=1,
        help="native solver threads per reusable recourse model; avoid combining large values with --workers",
    )
    run_parser.add_argument(
        "--region-map",
        required=False,
        type=Path,
        help="deprecated legacy region map; new submissions use artifact bus IDs directly",
    )
    classroom_parser = subparsers.add_parser(
        "classroom",
        help="evaluate the three weekly two-submission classroom schedule",
    )
    classroom_parser.add_argument("--manifest", required=True, type=Path)
    classroom_parser.add_argument("--state-path", required=False, type=Path)
    classroom_parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def _manifest_path(raw_value: object, *, base_dir: Path, label: str) -> Path:
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(f"classroom manifest {label} must be a non-empty path")
    path = Path(raw_value)
    return path if path.is_absolute() else base_dir / path


def _classroom_round_inputs(manifest_path: Path) -> tuple[ClassroomRoundInput, ...]:
    payload = _read_json(manifest_path, "classroom manifest")
    if isinstance(payload, Mapping):
        raw_rounds = payload.get("rounds")
    else:
        raw_rounds = payload
    if not isinstance(raw_rounds, list) or len(raw_rounds) != 6:
        raise ValueError("classroom manifest must contain exactly six rounds")

    base_dir = manifest_path.parent
    inputs: list[ClassroomRoundInput] = []
    for index, raw_round in enumerate(raw_rounds, start=1):
        if not isinstance(raw_round, Mapping):
            raise ValueError(f"classroom manifest round {index} must be an object")
        round_key = raw_round.get("round_key")
        if not isinstance(round_key, str) or not round_key:
            raise ValueError(f"classroom manifest round {index} must provide round_key")
        artifact_dir = _manifest_path(
            raw_round.get("artifact_dir"),
            base_dir=base_dir,
            label=f"round {index} artifact_dir",
        )
        rules_path = _manifest_path(
            raw_round.get("rules"),
            base_dir=base_dir,
            label=f"round {index} rules",
        )
        if "horizon" in raw_round:
            horizon = _positive_int(str(raw_round["horizon"]))
        elif round_key in round_sequence(HALF_YEAR_SCHEDULE_ID):
            year, round_name = round_key.split("_", 1)
            horizon = half_year_calendar(int(year), round_name).horizon
        else:
            horizon = _manifest_horizon(artifact_dir)
            if horizon is None:
                raise ValueError(f"classroom manifest round {index} must provide horizon")
        rules = load_scoring_rules(rules_path, artifact_dir=artifact_dir, horizon=horizon)
        inputs.append(
            ClassroomRoundInput(
                round_key=round_key,
                submissions=_manifest_path(
                    raw_round.get("submissions_dir"),
                    base_dir=base_dir,
                    label=f"round {index} submissions_dir",
                ),
                artifact_dir=artifact_dir,
                horizon=horizon,
                rules=rules,
            )
        )
    return tuple(inputs)


def _run_classroom(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    round_inputs = _classroom_round_inputs(manifest_path)
    output_dir = args.output_dir
    state_path = args.state_path or output_dir / "classroom_state.json"
    result = evaluate_classroom(
        state_path=state_path,
        rounds=round_inputs,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    round_inputs_by_key = {item.round_key: item for item in round_inputs}
    if len(round_inputs_by_key) != len(round_inputs):
        raise ValueError("classroom manifest contains duplicate round_key values")
    round_output_dirs: list[str] = []
    for round_result in result.submissions:
        round_input = round_inputs_by_key.get(round_result.round_key)
        if round_input is None:
            raise ValueError(
                f"classroom evaluation returned unknown round {round_result.round_key}"
            )
        dispatch = getattr(round_result.evaluation, "dispatch", None)
        periods = tuple(getattr(dispatch, "periods", ())) if dispatch is not None else ()
        period_indices = tuple(
            period.period_index for period in periods
        ) or tuple(range(round_input.horizon))
        round_output_dir = output_dir / round_result.week_id / f"submission-{round_result.submission_number}"
        write_classroom_outputs(
            round_result.evaluation,
            round_output_dir,
            week_id=round_result.week_id,
            submission_number=round_result.submission_number,
            feedback_only=round_result.feedback_only,
            scored=round_result.scored,
            scenario_version=Path(round_input.artifact_dir).name,
            evaluator_version=_evaluator_version(),
            period_indices=period_indices,
            source_period_indices=(
                getattr(round_result.evaluation, "source_period_indices", None) or None
            ),
        )
        round_output_dirs.append(round_output_dir.relative_to(output_dir).as_posix())

    public_payload = result.to_public_dict()
    public_payload["round_output_dirs"] = round_output_dirs
    serialized = json.dumps(public_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    evaluation_path = output_dir / "classroom_evaluation.json"
    evaluation_path.write_text(serialized, encoding="utf-8")
    (output_dir / "classroom_evaluation_sha256.txt").write_text(
        hashlib.sha256(serialized.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8",
    )
    print(f"output directory: {output_dir.resolve()}")
    processed_count = len(result.submissions)
    submission_label = "submission" if processed_count == 1 else "submissions"
    print(f"summary: {processed_count} half-year {submission_label}")
    return 0


def _energy_cost_setting(args: argparse.Namespace, representative: bool) -> bool | None:
    explicit = None if args.energy_cost is None else args.energy_cost == "on"
    from_week = None if args.week is None else week_energy_cost_enabled(args.week)
    if explicit is not None and from_week is not None and explicit != from_week:
        raise ValueError(f"--energy-cost {args.energy_cost} contradicts week {args.week}")
    setting = explicit if explicit is not None else from_week
    if setting is None and representative:
        raise ValueError(
            "the representative release needs --energy-cost on|off or --week 1|2|3 "
            "(weeks 1-2: off, week 3: on)"
        )
    return setting


def _run(args: argparse.Namespace) -> int:
    uses_half_year = args.year is not None or args.round_name is not None
    if args.artifact_dir is None and args.rules is None and not uses_half_year:
        args.artifact_dir = canonical_release_artifact_dir()
        args.rules = canonical_release_rules_path()
    elif args.rules is None and args.artifact_dir is not None and _is_representative(args.artifact_dir):
        args.rules = canonical_release_rules_path()
    elif args.artifact_dir is None or args.rules is None:
        if args.year is None or args.round_name is None:
            raise ValueError(
                "provide --artifact-dir and --rules, omit both for the representative release, "
                "or provide --year and --round for the retired six-hour release"
            )
        args.artifact_dir = canonical_artifact_dir(args.year, args.round_name)
        args.rules = canonical_rules_path(args.round_name)
    if not args.artifact_dir.is_dir():
        raise ValueError(
            f"artifact directory does not exist or is not a directory: {args.artifact_dir}"
        )
    representative = _is_representative(args.artifact_dir)
    if args.horizon is None and not uses_half_year:
        horizon = _manifest_horizon(args.artifact_dir)
        if horizon is None:
            raise ValueError("provide --horizon or both --year and --round")
        calendar = None
    elif args.horizon is None:
        if args.year is None or args.round_name is None:
            raise ValueError("provide --horizon or both --year and --round")
        calendar = half_year_calendar(args.year, args.round_name)
        horizon = aggregated_horizon(calendar.horizon, args.time_step_hours)
    else:
        if args.year is not None or args.round_name is not None:
            raise ValueError("--year/--round cannot be combined with --horizon")
        calendar = None
        horizon = args.horizon
    if args.submission_number is None:
        args.submission_number = 1 if representative else 2
    energy_cost_enabled = _energy_cost_setting(args, representative)
    reserved_site_ids = None
    if args.base_load_from is not None:
        if args.submission_number != 2:
            raise ValueError("--base-load-from applies to --submission-number 2")
        withdrawal_rows = read_site_net_withdrawal(args.base_load_from)
        reserved_site_ids = site_ids_by_team(withdrawal_rows)
        derived_dir = args.base_load_artifact_dir or args.output_dir / "base_load_artifact"
        materialize_base_load_artifact(
            args.artifact_dir,
            net_withdrawal_by_bus(withdrawal_rows, horizon),
            derived_dir,
            provenance={"submission_1_output": str(args.base_load_from)},
            validate=not args.skip_base_load_validation,
        )
        print(f"submission 2 base load artifact: {derived_dir.resolve()}")
        args.artifact_dir = derived_dir
    elif representative and args.submission_number == 2:
        raise ValueError(
            "Submission 2 needs --base-load-from <Submission 1 output dir>, so that "
            "Submission 1 sites are part of the base load"
        )
    region_to_source_bus = _load_region_map(args.region_map) if args.region_map else None
    rules = load_scoring_rules(
        args.rules,
        artifact_dir=args.artifact_dir,
        horizon=horizon,
    )
    period_indices = (
        tuple(range(horizon))
        if args.period_indices is None
        else args.period_indices
    )
    # A validated ACTIVSg2000 scenario block is indexed locally from hour 0.
    # The legacy calendar offset applies only to the retired contiguous-source
    # artifacts and must not shift a half-year block into a different block.
    scenario_block_offset = (
        0
        if (args.artifact_dir / "scenario_profile.json").is_file()
        and args.source_period_offset is None
        else None
    )
    result = evaluate_csv_batch(
        args.submissions_dir,
        artifact_dir=args.artifact_dir,
        region_to_source_bus=region_to_source_bus,
        horizon=horizon,
        rules=rules,
        period_indices=period_indices,
        source_period_offset=(
            args.source_period_offset
            if args.source_period_offset is not None
            else scenario_block_offset
            if scenario_block_offset is not None
            else calendar.source_row_start
            if calendar is not None
            else None
        ),
        dispatch_workers=args.workers,
        projection_iterations=args.projection_iterations,
        storage_solver_backend=args.solver_backend,
        storage_solver_threads=args.solver_threads,
        submission_number=args.submission_number,
        **(
            {}
            if energy_cost_enabled is None and reserved_site_ids is None
            else {
                "energy_cost_enabled": energy_cost_enabled,
                "reserved_site_ids_by_team": reserved_site_ids,
            }
        ),
    )
    write_batch_outputs(
        result,
        args.output_dir,
        scenario_version=args.artifact_dir.name,
        evaluator_version=_evaluator_version(),
        period_indices=period_indices,
        source_period_indices=result.source_period_indices,
        output_mode=args.output_mode,
    )
    print(f"output directory: {args.output_dir.resolve()}")
    print(_summary(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "classroom":
            return _run_classroom(args)
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
