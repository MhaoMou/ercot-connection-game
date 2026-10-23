"""Transactional coordination of the classroom game's weekly submissions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .batch_evaluation import (
    BatchEvaluation,
    BatchScoringRules,
    TeamScore,
    _collect_evaluation_inputs,
    evaluate_csv_batch,
)
from .base_load import (
    materialize_base_load_artifact,
    net_withdrawal_by_bus,
    site_net_withdrawal_rows,
)
from .calendars import weekly_match_for
from .csv_submission import load_bus_ids
from .game_state import RELEASED_ROUND_SEQUENCE, GameState
from .game_state_store import GameStateStore
from .models import TeamPlan


class RoundCoordinatorError(RuntimeError):
    """Raised when a round cannot be prepared or committed."""


PlanLoader = Callable[..., Sequence[TeamPlan]]
Evaluator = Callable[..., BatchEvaluation]


def _default_plan_loader(
    submissions: Sequence[str | Path] | str | Path,
    *,
    artifact_dir: str | Path,
    horizon: int,
    rules: BatchScoringRules,
) -> tuple[TeamPlan, ...]:
    """Reuse the evaluator's strict CSV collection path for state updates."""
    try:
        bus_ids = load_bus_ids(artifact_dir)
        collection = _collect_evaluation_inputs(
            submissions,
            bus_ids=bus_ids,
            horizon=horizon,
            default_generator_cost_per_mwh=rules.default_generator_cost_per_mwh,
            require_complete_horizon=True,
            max_generator_to_connection_ratio=getattr(rules, "max_generator_to_connection_ratio", 1.0),
        )
    except (OSError, ValueError) as exc:
        raise RoundCoordinatorError(f"could not validate round submissions: {exc}") from exc
    # Keep only accepted plans.  The batch evaluator deliberately isolates
    # malformed submissions so valid teams can still be evaluated; rejected
    # records must not enter the persistent asset ledger.
    return tuple(
        record.submission.plan
        for record in collection.accepted
        if record.submission is not None
    )


def _state_for_round(state: GameState, round_key: str) -> GameState:
    """Apply the weekly reset before plans are materialized or evaluated."""
    match = weekly_match_for(round_key)
    if state.current_week_id == match.week_id:
        return state
    return replace(
        state,
        asset_ledger=state.asset_ledger.reset(),
        carried_base_load_mw_by_bus={},
    )


def _load_state(state_path: str | Path) -> GameState:
    store = GameStateStore(state_path)
    try:
        return store.load() if Path(state_path).exists() else GameState.new()
    except FileNotFoundError:
        return GameState.new()


def evaluate_round(
    *,
    state_path: str | Path,
    round_key: str,
    submissions: Sequence[str | Path] | str | Path,
    artifact_dir: str | Path,
    horizon: int,
    rules: BatchScoringRules,
    plan_loader: PlanLoader | None = None,
    evaluator: Evaluator = evaluate_csv_batch,
    evaluator_kwargs: Mapping[str, Any] | None = None,
    base_load_artifact_dir: str | Path | None = None,
) -> "RoundEvaluationResult":
    """Evaluate one round and commit its state only after success.

    The existing evaluator remains responsible for dispatch and scoring.
    This wrapper owns only the transactional sequence: load prior state,
    validate/register current plans, evaluate, then save the advanced state.
    Any exception before the final save leaves the previous file untouched.

    The week sets the energy charge, and Submission 2 is evaluated on a
    derived artifact (written to ``base_load_artifact_dir``, by default next
    to the state file) whose base load includes the hourly net withdrawal of
    every Submission 1 site.
    """
    store = GameStateStore(state_path)
    try:
        match = weekly_match_for(round_key)
    except ValueError as exc:
        raise RoundCoordinatorError(str(exc)) from exc
    loaded_state = _load_state(state_path)
    expected_round = loaded_state.next_round_key
    if expected_round != round_key:
        if (
            match.round_keys[1] == round_key
            and loaded_state.current_round_key != match.round_keys[0]
        ):
            raise RoundCoordinatorError(
                f"submission 1 for {match.week_id} must be successfully committed "
                f"before submission 2 ({match.round_keys[0]})"
            )
        raise RoundCoordinatorError(
            f"round transition expected {expected_round}, received {round_key}"
        )

    ledger_reset = (
        loaded_state.current_round_key is not None
        and loaded_state.current_week_id != match.week_id
    )
    preserves_prior_submission = (
        loaded_state.current_week_id == match.week_id
        and match.round_keys[1] == round_key
    )
    prior_state = _state_for_round(loaded_state, round_key)
    return _evaluate_submission(
        store=store,
        state_path=state_path,
        round_key=round_key,
        match=match,
        prior_state=prior_state,
        submissions=submissions,
        artifact_dir=artifact_dir,
        horizon=horizon,
        rules=rules,
        plan_loader=plan_loader,
        evaluator=evaluator,
        evaluator_kwargs=evaluator_kwargs,
        base_load_artifact_dir=base_load_artifact_dir,
        ledger_reset=ledger_reset,
        preserves_prior_submission=preserves_prior_submission,
    )


_OWNED_EVALUATOR_KWARGS = (
    "submission_number",
    "energy_cost_enabled",
    "reserved_site_ids_by_team",
)


def _evaluate_submission(
    *,
    store: GameStateStore,
    state_path: str | Path,
    round_key: str,
    match: Any,
    prior_state: GameState,
    submissions: Sequence[str | Path] | str | Path,
    artifact_dir: str | Path,
    horizon: int,
    rules: BatchScoringRules,
    plan_loader: PlanLoader | None,
    evaluator: Evaluator,
    evaluator_kwargs: Mapping[str, Any] | None,
    base_load_artifact_dir: str | Path | None,
    ledger_reset: bool,
    preserves_prior_submission: bool,
) -> "RoundEvaluationResult":
    """Evaluate one submission of the classroom schedule.

    Submission 1 sites are fixed base load in Submission 2: they are not
    re-dispatched or re-scored, and a Submission 2 file may list only new
    site IDs (a file reusing one of its team's Submission 1 IDs is rejected).
    """
    submission_number = match.round_keys.index(round_key) + 1
    loader = plan_loader or _default_plan_loader
    plans = tuple(
        loader(
            submissions,
            artifact_dir=artifact_dir,
            horizon=horizon,
            rules=rules,
        )
    )
    reserved: dict[str, frozenset[str]] = {}
    evaluation_artifact = Path(artifact_dir)
    if submission_number == 2:
        reserved = {
            team_id: frozenset(team_state.sites)
            for team_id, team_state in prior_state.asset_ledger.teams.items()
        }
        plans = tuple(
            plan
            for plan in plans
            if not {site.site_id for site in plan.sites} & reserved.get(plan.team_id, frozenset())
        )
        carried = prior_state.carried_base_load_mw_by_bus
        if carried:
            evaluation_artifact = (
                Path(base_load_artifact_dir)
                if base_load_artifact_dir is not None
                else Path(state_path).parent / "base_load" / round_key
            )
            try:
                materialize_base_load_artifact(
                    artifact_dir,
                    carried,
                    evaluation_artifact,
                    provenance={"round_key": round_key},
                )
            except (OSError, ValueError) as exc:
                raise RoundCoordinatorError(
                    f"could not build the Submission 2 base load: {exc}"
                ) from exc

    kwargs = dict(evaluator_kwargs or {})
    if any(name in kwargs for name in _OWNED_EVALUATOR_KWARGS):
        raise RoundCoordinatorError("evaluate_round owns the submission and energy kwargs")
    kwargs.update(
        submission_number=submission_number,
        energy_cost_enabled=match.energy_cost_enabled,
        reserved_site_ids_by_team=reserved,
    )
    advanced_state = prior_state.advance(round_key, plans)
    evaluation = evaluator(
        submissions,
        artifact_dir=evaluation_artifact,
        horizon=horizon,
        rules=rules,
        **kwargs,
    )
    if not _has_period_collection(evaluation):
        raise RoundCoordinatorError(
            "evaluation did not return a usable dispatch result; state was not committed"
        )
    _validate_projection_team_isolation(evaluation, {plan.team_id: plan for plan in plans})
    if submission_number == 1:
        withdrawal = net_withdrawal_by_bus(site_net_withdrawal_rows(evaluation), horizon)
        advanced_state = replace(advanced_state, carried_base_load_mw_by_bus=withdrawal)
    store.save(advanced_state)
    return RoundEvaluationResult(
        round_key=round_key,
        evaluation=evaluation,
        prior_state=prior_state,
        state=advanced_state,
        ledger_reset=ledger_reset,
        preserves_prior_submission=preserves_prior_submission,
        artifact_dir=evaluation_artifact,
    )


@dataclass(frozen=True)
class ClassroomRoundInput:
    """Inputs for one submission in the released classroom schedule."""

    round_key: str
    submissions: Sequence[str | Path] | str | Path
    artifact_dir: str | Path
    horizon: int
    rules: BatchScoringRules


@dataclass(frozen=True)
class WeeklyRanking:
    """Per-submission results and the weekly ranking for one weekly match.

    ``submission_results`` holds the ranked results of each evaluated
    submission of the week, in submission order.  For the feedback-only
    Week 1 these are practice feedback and ``rankings`` is empty.  For the
    scored Weeks 2 and 3, both Submission 1 and Submission 2 count, and
    ``rankings`` ranks each team's weekly total (Submission 1 + Submission 2).
    """

    week_id: str
    feedback_only: bool
    rankings: tuple[TeamScore, ...] = ()
    submission_results: tuple[tuple[TeamScore, ...], ...] = ()


@dataclass(frozen=True)
class ClassroomEvaluationResult:
    """Public result for a sequential classroom evaluation."""

    submissions: tuple["RoundEvaluationResult", ...]
    weekly_rankings: tuple[WeeklyRanking, ...]
    final_rankings: tuple[TeamScore, ...]
    state: GameState

    def to_public_dict(self) -> dict[str, Any]:
        """Return aggregate metadata safe to publish to classroom consumers."""
        return {
            "submissions": [submission.to_public_dict() for submission in self.submissions],
            "weekly_rankings": {
                ranking.week_id: {
                    "feedback_only": ranking.feedback_only,
                    "submission_results": [
                        _score_counts(scores) for scores in ranking.submission_results
                    ],
                    "rankings": _score_counts(ranking.rankings),
                }
                for ranking in self.weekly_rankings
            },
            "final_rankings": _score_counts(self.final_rankings),
            "state_metadata": {
                "current_round_key": self.state.current_round_key,
                "next_round_key": self.state.next_round_key,
                "completed_rounds": list(self.state.completed_rounds),
            },
        }


def evaluate_classroom(
    *,
    state_path: str | Path,
    rounds: Sequence[ClassroomRoundInput],
    plan_loader: PlanLoader | None = None,
    evaluator: Evaluator = evaluate_csv_batch,
    evaluator_kwargs: Mapping[str, Any] | None = None,
) -> ClassroomEvaluationResult:
    """Evaluate a contiguous classroom schedule prefix transactionally.

    A caller may supply all six rounds or a prefix when resuming an interrupted
    classroom run.  Each round is committed through :func:`evaluate_round`,
    so a failed round cannot advance the state or expose a partial ranking.
    Persisted completed rounds are skipped and are not reconstructed in the
    returned result; a complete persisted state returns an empty result.
    """
    round_inputs = tuple(rounds)
    if not round_inputs or len(round_inputs) > len(RELEASED_ROUND_SEQUENCE):
        raise RoundCoordinatorError("classroom rounds must contain a non-empty released schedule prefix")
    expected_rounds = RELEASED_ROUND_SEQUENCE[: len(round_inputs)]
    actual_rounds = tuple(item.round_key for item in round_inputs)
    if actual_rounds != expected_rounds:
        raise RoundCoordinatorError(
            "classroom rounds must be a contiguous prefix of the released six-round schedule"
        )

    loaded_state = _load_state(state_path)

    pending_inputs = round_inputs[len(loaded_state.completed_rounds):]
    if not pending_inputs:
        return ClassroomEvaluationResult(
            submissions=(),
            weekly_rankings=(),
            final_rankings=(),
            state=loaded_state,
        )

    results: list[RoundEvaluationResult] = []
    for item in pending_inputs:
        results.append(
            evaluate_round(
                state_path=state_path,
                round_key=item.round_key,
                submissions=item.submissions,
                artifact_dir=item.artifact_dir,
                horizon=item.horizon,
                rules=item.rules,
                plan_loader=plan_loader,
                evaluator=evaluator,
                evaluator_kwargs=evaluator_kwargs,
            )
        )

    # Final ranking = sum of the four scored submissions: Week 2 S1 + Week 2
    # S2 + Week 3 S1 + Week 3 S2.  Week 1 is practice feedback only.
    weekly_rankings: list[WeeklyRanking] = []
    final_scores: list[TeamScore] = []
    for week_id, week_results in _group_week_results(results):
        feedback_only = week_results[0].feedback_only
        submission_results = tuple(
            _rank_scores(tuple(getattr(result.evaluation, "team_scores", ())))
            for result in week_results
        )
        if feedback_only:
            rankings: tuple[TeamScore, ...] = ()
        else:
            scored_scores = [
                score for scores in submission_results for score in scores
            ]
            rankings = _rank_scores(_sum_scores_by_team(scored_scores))
            final_scores.extend(scored_scores)
        weekly_rankings.append(
            WeeklyRanking(
                week_id=week_id,
                feedback_only=feedback_only,
                rankings=rankings,
                submission_results=submission_results,
            )
        )

    final_rankings = _rank_scores(_sum_scores_by_team(final_scores))
    return ClassroomEvaluationResult(
        submissions=tuple(results),
        weekly_rankings=tuple(weekly_rankings),
        final_rankings=final_rankings,
        state=results[-1].state,
    )


def _sum_scores_by_team(scores: Sequence[TeamScore]) -> tuple[TeamScore, ...]:
    """Sum scored submissions per team.

    Invalid or infeasible submissions contribute the rules' infeasible score
    (0 under the released rules).  The aggregate is valid/feasible when at
    least one summed submission was, so one failed submission lowers a team's
    total without moving the team into a separate ranking tier.
    """
    aggregate_by_team: dict[str, TeamScore] = {}
    for score in scores:
        previous = aggregate_by_team.get(score.team_id)
        if previous is None:
            aggregate_by_team[score.team_id] = replace(score, submission_key=None)
            continue
        feasible = previous.feasible or score.feasible
        aggregate_by_team[score.team_id] = replace(
            previous,
            valid=previous.valid or score.valid,
            feasible=feasible,
            failure_reason=None if feasible else previous.failure_reason,
            score=previous.score + score.score,
            served_load_mwh=previous.served_load_mwh + score.served_load_mwh,
            it_value=previous.it_value + score.it_value,
            energy_cost=previous.energy_cost + score.energy_cost,
            generator_operating_cost=(
                previous.generator_operating_cost + score.generator_operating_cost
            ),
            generator_capital_cost=(
                previous.generator_capital_cost + score.generator_capital_cost
            ),
            site_cost=previous.site_cost + score.site_cost,
            storage_capital_cost=(
                previous.storage_capital_cost + score.storage_capital_cost
            ),
        )
    return tuple(aggregate_by_team.values())


def _group_week_results(
    results: Sequence["RoundEvaluationResult"],
) -> tuple[tuple[str, tuple["RoundEvaluationResult", ...]], ...]:
    grouped: dict[str, list[RoundEvaluationResult]] = {}
    for result in results:
        grouped.setdefault(result.week_id, []).append(result)
    return tuple((week_id, tuple(grouped[week_id])) for week_id in grouped)


def _rank_scores(scores: Sequence[TeamScore]) -> tuple[TeamScore, ...]:
    ordered = sorted(
        scores,
        key=lambda item: (
            0 if item.valid and item.feasible else 1 if item.valid else 2,
            -item.score,
            item.team_id,
        ),
    )
    return tuple(replace(score, rank=index) for index, score in enumerate(ordered, start=1))


def _public_score_dict(score: Any) -> dict[str, Any]:
    payload = asdict(score)
    payload.pop("submission_key", None)
    return payload


def _score_counts(scores: Sequence[TeamScore]) -> dict[str, int]:
    return {
        "team_count": len(scores),
        "valid_team_count": sum(score.valid for score in scores),
        "feasible_team_count": sum(score.valid and score.feasible for score in scores),
    }


def _validate_projection_team_isolation(
    evaluation: Any,
    materialized_plans: Mapping[str, TeamPlan],
) -> None:
    """Reject projection diagnostics that leak rejected or unknown teams."""
    diagnostics = getattr(evaluation, "projection_diagnostics", None)
    if diagnostics is None:
        return
    valid_team_ids = set(materialized_plans)
    for field_name in (
        "service_fraction_by_team",
        "projected_capacity_mw_by_team",
        "capped_request_capacity_mw_by_team",
        "requested_load_mwh_by_team",
        "projected_load_mwh_by_team",
    ):
        values = getattr(diagnostics, field_name, None)
        if not isinstance(values, Mapping):
            raise RoundCoordinatorError(
                f"projection diagnostics field {field_name} must be a mapping; state was not committed"
            )
        unknown_team_ids = sorted(set(values) - valid_team_ids)
        if unknown_team_ids:
            raise RoundCoordinatorError(
                "projection diagnostics contain rejected or unknown team(s): "
                + ", ".join(unknown_team_ids)
                + "; state was not committed"
            )


def _has_period_collection(evaluation: Any) -> bool:
    """Accept real and lightweight dispatch objects with a period collection."""
    dispatch = getattr(evaluation, "dispatch", None)
    if dispatch is None:
        return False
    try:
        periods = dispatch.periods
    except AttributeError:
        return False
    if periods is None or isinstance(periods, (str, bytes)):
        return False
    try:
        period_count = len(periods)
    except (TypeError, ValueError):
        return False
    return period_count > 0


class RoundEvaluationResult:
    """Result of a committed round, including before/after game state."""

    def __init__(
        self,
        *,
        round_key: str,
        evaluation: BatchEvaluation,
        prior_state: GameState,
        state: GameState,
        ledger_reset: bool = False,
        preserves_prior_submission: bool = False,
        artifact_dir: str | Path | None = None,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.round_key = round_key
        self.evaluation = evaluation
        self.prior_state = prior_state
        self.state = state
        self.ledger_reset = ledger_reset
        self.preserves_prior_submission = preserves_prior_submission

    @property
    def week_id(self) -> str:
        return weekly_match_for(self.round_key).week_id

    @property
    def submission_number(self) -> int:
        match = weekly_match_for(self.round_key)
        return match.round_keys.index(self.round_key) + 1

    @property
    def feedback_only(self) -> bool:
        return weekly_match_for(self.round_key).feedback_only

    @property
    def scored(self) -> bool:
        """Both submissions of Weeks 2 and 3 count; Week 1 is feedback only."""
        return not self.feedback_only

    @property
    def predecessor_round_key(self) -> str | None:
        return (
            weekly_match_for(self.round_key).round_keys[0]
            if self.submission_number == 2
            else None
        )

    @property
    def team_results(self) -> tuple[TeamScore, ...]:
        return tuple(getattr(self.evaluation, "team_scores", ()))

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize round metadata without exposing team-specific classroom data."""
        return {
            "round_key": self.round_key,
            "week_id": self.week_id,
            "submission_number": self.submission_number,
            "feedback_only": self.feedback_only,
            "scored": self.scored,
            "ledger_reset": self.ledger_reset,
            "preserves_prior_submission": self.preserves_prior_submission,
            "predecessor_round_key": self.predecessor_round_key,
            "team_results": _score_counts(self.team_results),
        }
