"""Compatibility re-export for the first-class batch evaluator."""

from ercot_game.batch_evaluation import (
    BatchCollection,
    BatchEvaluation,
    BatchScoringRules,
    FailureIsolationEvent,
    SubmissionRecord,
    TeamScore,
    _infeasible_score,
    _score_team,
    collect_csv_submissions,
    evaluate_csv_batch,
    load_scoring_rules,
    write_batch_outputs as _write_batch_outputs,
)
from .dcopf import DCOPFInfeasible
from .plan_adapter import BatchDispatchResult, evaluate_plans_with_prepared_dcopf

__all__ = [
    "BatchDispatchResult",
    "BatchCollection",
    "BatchEvaluation",
    "BatchScoringRules",
    "DCOPFInfeasible",
    "FailureIsolationEvent",
    "SubmissionRecord",
    "TeamScore",
    "collect_csv_submissions",
    "evaluate_csv_batch",
    "evaluate_plans_with_prepared_dcopf",
    "load_scoring_rules",
    "write_batch_outputs",
]


def write_batch_outputs(evaluation, output_dir):
    """Preserve the legacy writer call while the first-class API gains metadata."""
    dispatches = [
        record.dispatch
        for record in getattr(evaluation, "dispatch_records", ())
        if getattr(record, "dispatch", None) is not None
    ]
    if evaluation.dispatch is not None:
        dispatches.append(evaluation.dispatch)
    period_indices = tuple(
        sorted({
            period.period_index
            for dispatch in dispatches
            for period in dispatch.periods
        })
    )
    if not period_indices:
        period_indices = (0,)
    return _write_batch_outputs(
        evaluation,
        output_dir,
        scenario_version="unspecified",
        evaluator_version="unspecified",
        period_indices=period_indices,
        source_period_indices=getattr(evaluation, "source_period_indices", None),
    )
