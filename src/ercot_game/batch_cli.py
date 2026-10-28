"""Command line entry point for the official CSV batch evaluation."""

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
    BaseLoadValidationError,
    materialize_base_load_artifact,
    net_withdrawal_by_bus,
    read_site_net_withdrawal,
    site_ids_by_team,
)
from .round_coordinator import ClassroomRoundInput, evaluate_classroom
from .release_config import (
    canonical_release_artifact_dir,
    canonical_release_rules_path,
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
    run_parser.add_argument(
        "--submission-number",
        type=int,
        choices=(1, 2),
        default=1,
        help="weekly submission number (default 1); Submission 2 needs --base-load-from",
    )
    run_parser.add_argument(
        "--energy-cost",
        choices=("on", "off"),
        help="charge grid purchases at the joint-dispatch LMP (on) or not (off); required unless --week is given",
    )
    run_parser.add_argument(
        "--week",
        type=int,
        choices=(1, 2, 3),
        help="game week; sets the energy charge (weeks 1-2 off, week 3 on)",
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
        "--roster",
        type=Path,
        help="optional class roster (one team_id per line, or a CSV with a team_id column); "
        "teams without a submission are listed in the summary and roster_check.json",
    )
    run_parser.add_argument(
        "--region-map",
        required=False,
        type=Path,
        help="deprecated legacy region map; new submissions use artifact bus IDs directly",
    )
    base_load_parser = subparsers.add_parser(
        "base-load",
        help="build and validate the Submission 2 release data from a Submission 1 output",
    )
    base_load_parser.add_argument(
        "--base-load-from",
        required=True,
        type=Path,
        help="Submission 1 output directory (its site_net_withdrawal.csv becomes base load)",
    )
    base_load_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="where to write the derived Submission 2 scenario artifact",
    )
    base_load_parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="source scenario artifact (default: the released representative package)",
    )
    base_load_parser.add_argument("--horizon", type=_positive_int)
    base_load_parser.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help="parallel period validations",
    )
    classroom_parser = subparsers.add_parser(
        "classroom",
        help="evaluate the three weekly two-submission classroom schedule",
    )
    classroom_parser.add_argument("--manifest", required=True, type=Path)
    classroom_parser.add_argument("--state-path", required=False, type=Path)
    classroom_parser.add_argument("--output-dir", required=True, type=Path)
    classroom_parser.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help="parallel dispatch workers per round (as for run)",
    )
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
        if not artifact_dir.is_dir():
            raise ValueError(
                f"classroom manifest round {index} ({round_key}) artifact_dir does not exist "
                f"or is not a directory: {artifact_dir}"
            )
        if "horizon" in raw_round:
            horizon = _positive_int(str(raw_round["horizon"]))
        else:
            horizon = _manifest_horizon(artifact_dir)
            if horizon is None:
                raise ValueError(
                    f"classroom manifest round {index} ({round_key}): artifact_dir {artifact_dir} "
                    "declares no horizon in its manifest.json (is it a scenario block such as "
                    "data/processed/activsg2000_representative_v1?); give \"horizon\" in the round"
                )
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


CLASSROOM_INSTRUCTOR_DIR = "instructor"
_TEAM_FOLDER_SECRET_FILE = "team_folder_secret.txt"
_GRADED_ROUNDS = (
    ("week-2-submission-1", "week2_s1"),
    ("week-2-submission-2", "week2_s2"),
    ("week-3-submission-1", "week3_s1"),
    ("week-3-submission-2", "week3_s2"),
)


def _team_folder_key(instructor_dir: Path) -> bytes:
    """Per-class secret salting the private team folder names.

    Created once (random) under the instructor-only directory and reused on
    resume, so a team's folder name is stable within a class but cannot be
    derived from its team ID without the secret.
    """
    import secrets

    path = instructor_dir / _TEAM_FOLDER_SECRET_FILE
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if len(text) < 32:
            raise ValueError(f"team folder secret {path} is too short")
        return text.encode("utf-8")
    instructor_dir.mkdir(parents=True, exist_ok=True)
    text = secrets.token_hex(32)
    path.write_text(text + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return text.encode("utf-8")


def _write_round_scores(instructor_dir: Path, round_result, folders: Mapping[str, str]) -> None:
    """Persist one round's per-team scores (instructor-only, resume-safe)."""
    rows_dir = instructor_dir / "round_scores"
    rows_dir.mkdir(parents=True, exist_ok=True)
    scores = tuple(getattr(round_result.evaluation, "team_scores", ()) or ())
    with (rows_dir / f"{round_result.round_key}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("team_id", "team_folder", "valid", "feasible", "score", "failure_reason"))
        for score in sorted(scores, key=lambda item: item.team_id):
            writer.writerow(
                (
                    score.team_id,
                    folders.get(score.team_id, ""),
                    score.valid,
                    score.feasible,
                    repr(float(score.score)),
                    getattr(score, "failure_reason", None) or "",
                )
            )


def _write_final_leaderboard(instructor_dir: Path) -> Path:
    """Write final_leaderboard.csv: the four graded scores and their total.

    Built from every persisted graded round (also those of earlier, resumed
    runs).  A team without a scored file in a round gets 0 for it; rounds
    not yet evaluated are left empty and listed in ``missing_rounds``.
    """
    rows_dir = instructor_dir / "round_scores"
    by_team: dict[str, dict[str, float]] = {}
    folders: dict[str, str] = {}
    present = []
    for round_key, column in _GRADED_ROUNDS:
        path = rows_dir / f"{round_key}.csv"
        if not path.is_file():
            continue
        present.append(column)
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                by_team.setdefault(row["team_id"], {})[column] = float(row["score"])
                if row.get("team_folder"):
                    folders[row["team_id"]] = row["team_folder"]
    missing = [column for _key, column in _GRADED_ROUNDS if column not in present]
    totals = {
        team_id: sum(values.get(column, 0.0) for column in present)
        for team_id, values in by_team.items()
    }
    ordered = sorted(totals, key=lambda team_id: (-totals[team_id], team_id))
    instructor_dir.mkdir(parents=True, exist_ok=True)
    path = instructor_dir / "final_leaderboard.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ("rank", "team_id", "team_folder", *(column for _key, column in _GRADED_ROUNDS), "total", "missing_rounds")
        )
        for rank, team_id in enumerate(ordered, start=1):
            values = by_team[team_id]
            writer.writerow(
                (
                    rank,
                    team_id,
                    folders.get(team_id, ""),
                    *(
                        repr(values.get(column, 0.0)) if column in present else ""
                        for _key, column in _GRADED_ROUNDS
                    ),
                    repr(totals[team_id]),
                    ";".join(missing),
                )
            )
    return path


def _run_classroom(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    round_inputs = _classroom_round_inputs(manifest_path)
    output_dir = args.output_dir
    state_path = args.state_path or output_dir / "classroom_state.json"
    result = evaluate_classroom(
        state_path=state_path,
        rounds=round_inputs,
        evaluator_kwargs={"dispatch_workers": args.workers} if args.workers != 1 else None,
    )
    instructor_dir = output_dir / CLASSROOM_INSTRUCTOR_DIR
    folder_key = _team_folder_key(instructor_dir)

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
        folders = write_classroom_outputs(
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
            team_folder_key=folder_key,
        )
        _write_round_scores(instructor_dir, round_result, folders or {})
        round_output_dirs.append(round_output_dir.relative_to(output_dir).as_posix())
    leaderboard_path = _write_final_leaderboard(instructor_dir)

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
    print(f"final leaderboard (instructor-only): {leaderboard_path.resolve()}")
    processed_count = len(result.submissions)
    submission_label = "submission" if processed_count == 1 else "submissions"
    print(f"summary: {processed_count} {submission_label} evaluated")
    return 0


def _energy_cost_setting(args: argparse.Namespace) -> bool:
    explicit = None if args.energy_cost is None else args.energy_cost == "on"
    from_week = None if args.week is None else week_energy_cost_enabled(args.week)
    if explicit is not None and from_week is not None and explicit != from_week:
        raise ValueError(f"--energy-cost {args.energy_cost} contradicts week {args.week}")
    setting = explicit if explicit is not None else from_week
    if setting is None:
        raise ValueError(
            "provide --energy-cost on|off or --week 1|2|3 "
            "(weeks 1-2: off, week 3: on)"
        )
    return setting


def _rejection_lines(result) -> list[str]:
    """One line per rejected file, so an all-rejected folder is explained."""
    lines = []
    for record in getattr(result, "rejected_submissions", ()) or ():
        name = getattr(getattr(record, "path", None), "name", None) or record.team_id
        lines.append(f"rejected {name} (team {record.team_id}): {record.failure_reason}")
    return lines


def _build_base_load(
    artifact_dir: Path,
    base_load_from: Path,
    derived_dir: Path,
    *,
    horizon: int,
    validate: bool,
    workers: int = 1,
) -> list[dict]:
    """Write (and validate) the Submission 2 base-load artifact; return the withdrawal rows."""
    withdrawal_rows = read_site_net_withdrawal(base_load_from)
    try:
        manifest = materialize_base_load_artifact(
            artifact_dir,
            net_withdrawal_by_bus(withdrawal_rows, horizon),
            derived_dir,
            provenance={"submission_1_output": str(base_load_from)},
            validate=validate,
            workers=workers,
        )
    except BaseLoadValidationError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"Submission 2 base-load validation ({derived_dir}): {exc}") from exc
    validation = manifest.get("validation", {})
    print(f"submission 2 base load artifact: {derived_dir.resolve()}")
    if not validate:
        print("submission 2 base load validation: skipped (--skip-base-load-validation)")
    else:
        adjusted = validation.get("tolerance_adjusted_period_count", 0)
        line = (
            f"submission 2 base load validation: passed {validation.get('passed_period_count')} periods"
        )
        if adjusted:
            line += (
                f"; {adjusted} periods within tolerance after "
                f"{validation.get('tolerance_adjusted_total_mw'):.3g} MW of demand change "
                "(recorded in manifest.json)"
            )
        print(line)
    return withdrawal_rows


def _run_base_load(args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir or canonical_release_artifact_dir()
    if not Path(artifact_dir).is_dir():
        raise ValueError(f"artifact directory does not exist or is not a directory: {artifact_dir}")
    horizon = args.horizon or _manifest_horizon(artifact_dir)
    if horizon is None:
        raise ValueError("provide --horizon (the artifact manifest declares none)")
    _build_base_load(
        artifact_dir,
        args.base_load_from,
        args.output_dir,
        horizon=horizon,
        validate=True,
        workers=args.workers,
    )
    return 0


def _read_roster(path: Path) -> tuple[str, ...]:
    """Team IDs of a roster: one per line, or a CSV with a ``team_id`` column."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read roster {path}: {exc}") from None
    rows = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if rows and "team_id" in [cell.strip() for cell in rows[0].split(",")]:
        reader = csv.DictReader(rows)
        team_ids = [str(row.get("team_id") or "").strip() for row in reader]
    else:
        team_ids = [row.split(",")[0].strip() for row in rows]
    team_ids = [team_id for team_id in team_ids if team_id]
    if not team_ids:
        raise ValueError(f"roster {path} lists no team_id")
    duplicates = sorted({team_id for team_id in team_ids if team_ids.count(team_id) > 1})
    if duplicates:
        raise ValueError(f"roster {path} lists duplicate team_id: {', '.join(duplicates)}")
    return tuple(team_ids)


def _write_roster_check(roster: tuple[str, ...], result, output_dir: Path) -> str:
    """Write roster_check.json and return the summary line."""
    submitted = {score.team_id for score in result.team_scores}
    missing = sorted(set(roster) - submitted)
    payload = {
        "roster_team_count": len(roster),
        "submitted_roster_team_count": len(set(roster) & submitted),
        "missing_team_ids": missing,
        "not_on_roster_team_ids": sorted(submitted - set(roster)),
    }
    (Path(output_dir) / "roster_check.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    line = f"roster: {payload['submitted_roster_team_count']} of {len(roster)} teams submitted"
    line += f"; missing: {', '.join(missing)}" if missing else "; none missing"
    if payload["not_on_roster_team_ids"]:
        line += f"; not on roster: {', '.join(payload['not_on_roster_team_ids'])}"
    return line


def _run(args: argparse.Namespace) -> int:
    if not Path(args.submissions_dir).is_dir():
        raise ValueError(f"submissions directory not found: {args.submissions_dir}")
    if args.artifact_dir is None and args.rules is None:
        args.artifact_dir = canonical_release_artifact_dir()
        args.rules = canonical_release_rules_path()
    elif args.rules is None and args.artifact_dir is not None and _is_representative(args.artifact_dir):
        args.rules = canonical_release_rules_path()
    elif args.artifact_dir is None or args.rules is None:
        raise ValueError(
            "provide --artifact-dir and --rules, or omit both for the released "
            "representative-day package"
        )
    if not args.artifact_dir.is_dir():
        raise ValueError(
            f"artifact directory does not exist or is not a directory: {args.artifact_dir}"
        )
    representative = _is_representative(args.artifact_dir)
    if args.horizon is None:
        horizon = _manifest_horizon(args.artifact_dir)
        if horizon is None:
            raise ValueError("provide --horizon (the artifact manifest declares none)")
    else:
        horizon = args.horizon
    energy_cost_enabled = _energy_cost_setting(args)
    roster = _read_roster(args.roster) if args.roster is not None else None
    reserved_site_ids = None
    if args.base_load_from is not None:
        if args.submission_number != 2:
            raise ValueError("--base-load-from applies to --submission-number 2")
        derived_dir = args.base_load_artifact_dir or args.output_dir / "base_load_artifact"
        withdrawal_rows = _build_base_load(
            args.artifact_dir,
            args.base_load_from,
            derived_dir,
            horizon=horizon,
            validate=not args.skip_base_load_validation,
            workers=args.workers,
        )
        reserved_site_ids = site_ids_by_team(withdrawal_rows)
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
    result = evaluate_csv_batch(
        args.submissions_dir,
        artifact_dir=args.artifact_dir,
        region_to_source_bus=region_to_source_bus,
        horizon=horizon,
        rules=rules,
        period_indices=period_indices,
        source_period_offset=0,
        dispatch_workers=args.workers,
        projection_iterations=args.projection_iterations,
        storage_solver_backend=args.solver_backend,
        storage_solver_threads=args.solver_threads,
        submission_number=args.submission_number,
        energy_cost_enabled=energy_cost_enabled,
        reserved_site_ids_by_team=reserved_site_ids,
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
    for line in _rejection_lines(result):
        print(line)
    print(_summary(result))
    if roster is not None:
        print(_write_roster_check(roster, result, args.output_dir))
    else:
        (Path(args.output_dir) / "roster_check.json").unlink(missing_ok=True)
    if not any(score.valid for score in result.team_scores):
        print("no valid CSV submissions were found", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "classroom":
            return _run_classroom(args)
        if args.command == "base-load":
            return _run_base_load(args)
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
