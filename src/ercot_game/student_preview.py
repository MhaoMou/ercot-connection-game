"""Fast, conservative student-side plan preview.

The instructor evaluator solves the exact multi-period storage dispatch LP.  A
full storage solve is intentionally not used here: it couples every period and
is too slow for interactive Colab iteration on the 2,000-bus model.  The
preview instead runs the fast independent-period DCOPF on every
``preview_stride``-th game period (every period of the 120-period
representative release by default), with submitted storage removed from
dispatch.  Sampled
totals are scaled to the represented hours.  Storage remains
validated and its capital cost is included in the preview score, but its
operating benefit is deliberately omitted.  The result is a conservative
screening estimate, never the official score.

Team generators respect the daily run-hour budget
(``generator_daily_energy_hours``) when the rules set one: with every period
solved (stride 1, whole days) the preview uses the evaluator's exact daily
budgeted dispatch; with a sampled stride the days are incomplete, so each
generator is conservatively derated to h/24 of its capacity in every sampled
period (never more energy than the budget, less flexibility than the
evaluator).

When the plans exceed the hosting capacity of a checked hour, the preview
applies the evaluator's fair projection (uniform rule with the 50% minimum
allocation) to the same storage-free dispatch instead of failing, and
reports each team's service fraction.  Storage can only raise the official
fraction, so the projected preview stays conservative for a single team.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from collections.abc import Sequence
import sys
import tempfile
from typing import Any

from .batch_evaluation import (
    BatchScoringRules,
    ProjectionDiagnostics,
    TeamScore,
    _fair_continuous_projection,
    _score_team,
    collect_csv_submissions,
    load_scoring_rules,
)
from .csv_submission import load_bus_ids
from .models import TeamPlan

from tools.activsg2000.dcopf import DCOPFInfeasible, DCOPFUnresolved
from tools.activsg2000.plan_adapter import (
    BatchDispatchResult,
    evaluate_plans_with_prepared_dcopf,
)


class PreviewInfeasible(ValueError):
    """Even the zero-load base case of the preview dispatch is infeasible."""


@dataclass(frozen=True)
class StudentPreviewResult:
    """A deliberately non-authoritative full-horizon screening result."""

    exact: bool
    horizon_hours: int
    checked_periods: tuple[int, ...]
    storage_dispatch_policy: str
    dispatch: BatchDispatchResult
    team_scores: tuple[TeamScore, ...]
    preview_stride: int = 1
    sample_spacing_hours: float = 1.0
    generator_dispatch_policy: str = "no_daily_budget"
    service_fraction_by_team: dict[str, float] | None = None
    projection: ProjectionDiagnostics | None = None
    projection_reason: str | None = None


def preview_plans(
    plans: Sequence[TeamPlan],
    *,
    artifact_dir: str | Path,
    horizon: int,
    rules: BatchScoringRules,
    workers: int = 1,
    submission_number: int | None = 1,
    preview_stride: int = 1,
    energy_cost_enabled: bool | None = None,
) -> StudentPreviewResult:
    """Screen plans with independent per-period DCOPF and no storage dispatch.

    This function keeps the official horizon (120 periods of the
    representative release).  It solves every ``preview_stride``-th period
    and drops storage coupling, so students can screen plans without
    waiting for the coupled storage LP.  The returned scores are marked ``student_preview`` by the
    caller-facing serialization and must not be used for ranking.
    """
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    if not plans:
        raise ValueError("at least one plan is required")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    if not isinstance(preview_stride, int) or isinstance(preview_stride, bool) or preview_stride <= 0:
        raise ValueError("preview_stride must be a positive integer")

    ordered_plans = tuple(sorted(plans, key=lambda plan: plan.team_id))
    if len({plan.team_id for plan in ordered_plans}) != len(ordered_plans):
        raise ValueError("team IDs must be unique")
    # A sampled preview is intentionally distinct from the exact instructor
    # evaluator.  Solving every period through the high-level plan adapter is
    # still too expensive on a free Colab runtime.  Sampling every
    # ``preview_stride``-th period keeps the game's period index space and scales
    # the score by the represented hours.
    period_indices = tuple(range(0, horizon, preview_stride))
    sampled_rules = replace(
        rules,
        time_step_hours=rules.time_step_hours * preview_stride,
        period_weight_hours=tuple(weight * preview_stride for weight in rules.period_weight_hours),
    )

    # The exact evaluator remains responsible for storage operation.  Removing
    # storage only from this fast dispatch call prevents the horizon LP from
    # being built while retaining the original plans for capital-cost scoring.
    # The adapter rebuilds storage from the site rows, so clear them there too.
    dispatch_plans = tuple(
        replace(
            plan,
            storages=(),
            sites=tuple(
                replace(site, storage_power_mw=0.0, storage_energy_mwh=0.0)
                for site in plan.sites
            ),
        )
        for plan in ordered_plans
    )
    budget_hours = rules.generator_daily_energy_hours
    day_periods = 24.0 / rules.time_step_hours
    exact_budget = (
        budget_hours is not None
        and preview_stride == 1
        and day_periods.is_integer()
        and len(period_indices) % int(day_periods) == 0
    )
    generator_policy = "no_daily_budget"
    adapter_options: dict[str, Any] = {}
    if budget_hours is not None:
        if exact_budget:
            adapter_options["generator_daily_energy_hours"] = budget_hours
            generator_policy = f"daily_budget_{budget_hours:g}h_exact"
        else:
            derate = min(1.0, budget_hours / 24.0)
            dispatch_plans = tuple(
                replace(
                    plan,
                    generators=tuple(
                        replace(generator, capacity_mw=generator.capacity_mw * derate)
                        for generator in plan.generators
                    ),
                    sites=tuple(
                        replace(site, generator_capacity_mw=site.generator_capacity_mw * derate)
                        for site in plan.sites
                    ),
                )
                for plan in dispatch_plans
            )
            generator_policy = f"daily_budget_{budget_hours:g}h_derated_to_{derate:g}_of_capacity"
    projection: ProjectionDiagnostics | None = None
    projection_reason: str | None = None
    try:
        dispatch = evaluate_plans_with_prepared_dcopf(
            artifact_dir,
            dispatch_plans,
            period_indices=period_indices,
            workers=workers,
            **adapter_options,
        )
    except (DCOPFInfeasible, DCOPFUnresolved) as exc:
        # Some checked hour exceeds hosting capacity.  Apply the evaluator's
        # fair projection to the same storage-free dispatch.
        projection_reason = str(exc)
        projected = _fair_continuous_projection(
            artifact_dir,
            dispatch_plans,
            period_indices,
            period_indices,
            # The adapter's stop-on-infeasible probes require one worker.
            generator_daily_energy_hours=adapter_options.get("generator_daily_energy_hours"),
        )
        if projected is None:
            raise PreviewInfeasible(
                "the preview dispatch is infeasible even with every team at zero load: "
                f"{projection_reason}"
            ) from exc
        dispatch = projected.dispatch
        projection = projected.diagnostics
    service_fraction_by_team = (
        {plan.team_id: 1.0 for plan in ordered_plans}
        if projection is None
        else dict(projection.service_fraction_by_team)
    )
    scores = tuple(
        replace(
            _score_team(
                plan,
                dispatch,
                sampled_rules,
                submission_number=submission_number,
                energy_cost_enabled=energy_cost_enabled,
            ),
            competition_scope=(
                "student_preview" if projection is None else "student_preview_projection"
            ),
        )
        for plan in ordered_plans
    )
    ranked = tuple(
        replace(score, rank=rank)
        for rank, score in enumerate(
            sorted(scores, key=lambda score: (-score.score, score.team_id)),
            start=1,
        )
    )
    return StudentPreviewResult(
        exact=False,
        horizon_hours=horizon,
        checked_periods=period_indices,
        storage_dispatch_policy=(
            f"idle_for_speed;sampled_every_{preview_stride}_periods_"
            f"{preview_stride * rules.time_step_hours:g}h"
        ),
        generator_dispatch_policy=generator_policy,
        dispatch=dispatch,
        team_scores=ranked,
        preview_stride=preview_stride,
        sample_spacing_hours=preview_stride * rules.time_step_hours,
        service_fraction_by_team=service_fraction_by_team,
        projection=projection,
        projection_reason=projection_reason,
    )


def _score_payload(score: TeamScore, fraction: float | None = None) -> dict[str, Any]:
    payload = asdict(score)
    payload["service_fraction"] = 1.0 if fraction is None else fraction
    payload["dropped"] = fraction is not None and fraction <= 0.0
    return payload


def _result_payload(result: StudentPreviewResult) -> dict[str, Any]:
    return {
        "mode": "student_preview",
        "exact": result.exact,
        "horizon_hours": result.horizon_hours,
        "checked_period_count": len(result.checked_periods),
        "storage_dispatch_policy": result.storage_dispatch_policy,
        "generator_dispatch_policy": result.generator_dispatch_policy,
        "warning": (
            f"Preview only: dispatch sampled every {result.preview_stride} game periods "
            f"(every {result.sample_spacing_hours:g} hours); storage is validated and "
            "capital-costed but not dispatched. "
            "Use the instructor evaluator for official storage-aware scores."
        ),
        "team_scores": [
            _score_payload(score, (result.service_fraction_by_team or {}).get(score.team_id))
            for score in result.team_scores
        ],
        "service_fraction_by_team": dict(result.service_fraction_by_team or {}),
        "projection": None if result.projection is None else {
            "applied": True,
            "reason": (
                "the plans exceed the hosting capacity of at least one checked hour; "
                "each team's load is scaled by its service fraction (teams below "
                f"{result.projection.cap_policy.get('minimum_allocation_fraction', 0.5):g} "
                "of their request are dropped), as in the official evaluator"
            ),
            "dispatch_error": result.projection_reason,
            "common_level_mw": result.projection.cap_policy.get("common_level_mw"),
            "dropped_team_ids": sorted(
                team_id
                for team_id, fraction in result.projection.service_fraction_by_team.items()
                if fraction <= 0.0
            ),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fast conservative student-side CSV preview"
    )
    parser.add_argument("--submissions-dir", required=True, type=Path)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="scenario artifact (default: the released representative-day package)",
    )
    parser.add_argument("--rules", type=Path, help="scoring rules (default: the release rules)")
    parser.add_argument("--horizon", type=int, help="period count (default: from the artifact manifest)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--preview-stride",
        type=int,
        help="solve every Nth period (default 1: every period)",
    )
    parser.add_argument("--submission-number", type=int, choices=(1, 2))
    parser.add_argument(
        "--base-load-from",
        type=Path,
        help=(
            "Submission 2: Submission 1 evaluator output directory whose "
            "site_net_withdrawal.csv becomes base load (as in the evaluator)"
        ),
    )
    parser.add_argument("--energy-cost", choices=("on", "off"), help="charge grid purchases at LMP")
    parser.add_argument("--week", type=int, choices=(1, 2, 3), help="release week; sets the energy charge")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _resolve_defaults(args: argparse.Namespace) -> bool | None:
    """Fill release defaults; return the energy-cost switch."""
    from .batch_cli import _energy_cost_setting, _is_representative, _manifest_horizon
    from .release_config import (
        CANONICAL_PREVIEW_STRIDE,
        canonical_release_artifact_dir,
        canonical_release_rules_path,
    )

    if args.artifact_dir is None:
        args.artifact_dir = canonical_release_artifact_dir()
    representative = _is_representative(args.artifact_dir)
    if args.rules is None:
        if not representative:
            raise SystemExit("--rules is required outside the representative release")
        args.rules = canonical_release_rules_path()
    if args.horizon is None:
        args.horizon = _manifest_horizon(args.artifact_dir)
        if args.horizon is None:
            raise SystemExit("--horizon is required for this artifact")
    if args.preview_stride is None:
        args.preview_stride = CANONICAL_PREVIEW_STRIDE
    if args.submission_number is None:
        args.submission_number = 1
    try:
        return _energy_cost_setting(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.submissions_dir.is_dir():
        return _error(f"submissions directory not found: {args.submissions_dir}")
    if args.base_load_from is not None and args.submission_number is None:
        args.submission_number = 2
    energy_cost_enabled = _resolve_defaults(args)
    with tempfile.TemporaryDirectory(prefix="preview_base_load_") as scratch:
        try:
            return _run(args, energy_cost_enabled, Path(scratch))
        except PreviewInfeasible as exc:
            return _error(str(exc))
        except (OSError, ValueError) as exc:
            return _error(str(exc))


def _has_submission_2_base_load(artifact_dir: Path) -> bool:
    """Whether the artifact already carries Submission 1 load (released S2 data)."""
    try:
        manifest = json.loads((Path(artifact_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and "submission_2_base_load" in manifest


def _submission_2_base_load(args: argparse.Namespace, scratch: Path):
    """Return reserved Submission 1 site IDs; repoint the artifact like the evaluator."""
    from .base_load import (
        materialize_base_load_artifact,
        net_withdrawal_by_bus,
        read_site_net_withdrawal,
        site_ids_by_team,
    )
    from .batch_cli import _is_representative

    if args.base_load_from is None:
        if (
            args.submission_number == 2
            and _is_representative(args.artifact_dir)
            and not _has_submission_2_base_load(args.artifact_dir)
        ):
            raise ValueError(
                "a Submission 2 preview needs --base-load-from <Submission 1 output dir> "
                "(the folder with site_net_withdrawal.csv), so that Submission 1 sites "
                "are part of the base load, as in the official evaluator"
            )
        return None
    if args.submission_number != 2:
        raise ValueError("--base-load-from applies to --submission-number 2")
    rows = read_site_net_withdrawal(args.base_load_from)
    derived = scratch / "base_load_artifact"
    materialize_base_load_artifact(
        args.artifact_dir,
        net_withdrawal_by_bus(rows, args.horizon),
        derived,
        provenance={"submission_1_output": str(args.base_load_from), "preview": True},
        validate=False,
    )
    args.artifact_dir = derived
    return site_ids_by_team(rows)


def _run(args: argparse.Namespace, energy_cost_enabled: bool, scratch: Path) -> int:
    reserved_site_ids = _submission_2_base_load(args, scratch)
    bus_ids = load_bus_ids(args.artifact_dir)
    rules = load_scoring_rules(
        args.rules,
        artifact_dir=args.artifact_dir,
        horizon=args.horizon,
    )
    collection = collect_csv_submissions(
        args.submissions_dir,
        bus_ids=bus_ids,
        horizon=args.horizon,
        default_generator_cost_per_mwh=rules.default_generator_cost_per_mwh,
        require_complete_horizon=True,
        max_generator_to_connection_ratio=rules.max_generator_to_connection_ratio,
        reserved_site_ids_by_team=reserved_site_ids,
    )
    for record in collection.rejected:
        print(f"rejected {record.path.name} (team {record.team_id}): {record.failure_reason}")
    accepted = tuple(
        record.submission.plan
        for record in collection.accepted
        if record.submission is not None
    )
    if not accepted:
        print("no valid CSV submissions were found", file=sys.stderr)
        return 1
    result = preview_plans(
        accepted,
        artifact_dir=args.artifact_dir,
        horizon=args.horizon,
        rules=rules,
        workers=args.workers,
        submission_number=args.submission_number,
        preview_stride=args.preview_stride,
        energy_cost_enabled=energy_cost_enabled,
    )
    payload = _result_payload(result)
    payload["energy_cost_enabled"] = energy_cost_enabled
    payload["rejected_submissions"] = [
        {"team_id": record.team_id, "reason": record.failure_reason}
        for record in collection.rejected
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.projection is not None:
        print(
            "NOTE: the plan exceeds the hosting capacity of at least one checked hour; "
            "load was scaled by the evaluator's fair projection. Service fractions: "
            + ", ".join(
                f"{team_id}={fraction:.4g}"
                for team_id, fraction in sorted(result.service_fraction_by_team.items())
            )
        )
    print(f"wrote preview: {args.output.resolve()}")
    print("WARNING: this is a conservative preview, not the official score.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
