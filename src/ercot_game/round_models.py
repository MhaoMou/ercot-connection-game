"""Immutable domain types and deterministic policies for classroom rounds."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import math
from numbers import Real
from typing import Any, Sequence


class RoundState(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    LOCKED = "locked"
    EVALUATED = "evaluated"
    PUBLISHED = "published"
    FAILED = "failed"
    RETRACTED = "retracted"


class ActorRole(StrEnum):
    STUDENT = "student"
    INSTRUCTOR = "instructor"
    SYSTEM = "system"


class RoundDomainError(ValueError):
    """Base error for invalid round-domain operations."""

    def __init__(self, message: str, *, code: str = "validation_failed") -> None:
        super().__init__(message)
        self.code = code


class InvalidTransitionError(RoundDomainError):
    """Raised when a round lifecycle transition is not permitted."""

    def __init__(self, current: RoundState, target: RoundState) -> None:
        super().__init__(
            f"cannot transition round from {current.value} to {target.value}",
            code="invalid_transition",
        )
        self.current = current
        self.target = target


@dataclass(frozen=True)
class RoundPolicy:
    scenario_id: str
    scenario_version: str
    evaluator_version: str
    policy_version: str = "1"
    deadline_seconds: float | None = None
    deadline_at: datetime | None = None
    visibility: str = "private"
    tie_break_mode: str = "default"
    seed: int | None = None
    display_timezone: str = "UTC"


@dataclass(frozen=True)
class RoundRecord:
    round_id: str
    state: RoundState = RoundState.DRAFT
    policy: RoundPolicy | None = None
    created_at: datetime | None = None
    opened_at: datetime | None = None
    locked_at: datetime | None = None
    published_at: datetime | None = None

    def transition(self, target: RoundState) -> "RoundRecord":
        current = _coerce_state(self.state)
        target = _coerce_state(target)
        if not transition_allowed(current, target):
            raise InvalidTransitionError(current, target)
        return replace(self, state=target)


@dataclass(frozen=True)
class SessionRecord:
    actor_id: str
    round_id: str
    team_id: str | None
    role: ActorRole
    expires_at: datetime | None = None


@dataclass(frozen=True)
class SubmissionRecord:
    submission_id: str
    round_id: str
    team_id: str
    semantic_hash: str
    idempotency_key: str
    payload: Any = None
    submitted_at: datetime | None = None
    status: str = "accepted"


@dataclass(frozen=True)
class EvaluationRunRecord:
    evaluation_run_id: str
    round_id: str
    batch_input_hash: str
    seed: int | None = None
    status: str = "complete"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True)
class TeamResultRecord:
    team_id: str
    authoritative_total: float
    rank: int | None = None
    tie_group: str | None = None
    visibility: str = "private"
    evaluation_run_id: str | None = None
    diagnostics: Any = None


_ALLOWED_TRANSITIONS = frozenset(
    {
        (RoundState.DRAFT, RoundState.OPEN),
        (RoundState.OPEN, RoundState.LOCKED),
        (RoundState.LOCKED, RoundState.EVALUATED),
        (RoundState.EVALUATED, RoundState.PUBLISHED),
        (RoundState.EVALUATED, RoundState.FAILED),
        (RoundState.PUBLISHED, RoundState.RETRACTED),
    }
)
_ALLOWED_VISIBILITY = frozenset({"private", "aggregate", "public"})
_RANDOMIZED_TIE_MODES = frozenset({"seeded_random", "randomized"})
_DEFAULT_TIE_MODES = frozenset({"default", "authoritative_total"})


def _coerce_state(value: RoundState | str) -> RoundState:
    try:
        return value if isinstance(value, RoundState) else RoundState(value)
    except ValueError as error:
        raise RoundDomainError(f"unsupported round state: {value!r}") from error


def transition_allowed(current: RoundState | str, target: RoundState | str) -> bool:
    """Return whether a lifecycle transition is allowed."""
    try:
        pair = (_coerce_state(current), _coerce_state(target))
    except RoundDomainError:
        return False
    return pair in _ALLOWED_TRANSITIONS


def validate_round_policy(policy: RoundPolicy) -> RoundPolicy:
    """Validate and return a round policy unchanged."""
    for field_name in ("scenario_id", "scenario_version", "evaluator_version", "policy_version"):
        if not isinstance(getattr(policy, field_name), str) or not getattr(policy, field_name).strip():
            raise RoundDomainError(f"{field_name} is required")
    if policy.deadline_seconds is not None:
        if (
            not isinstance(policy.deadline_seconds, Real)
            or isinstance(policy.deadline_seconds, bool)
            or not math.isfinite(policy.deadline_seconds)
            or policy.deadline_seconds < 0
        ):
            raise RoundDomainError("deadline_seconds must be finite and non-negative")
    if policy.deadline_at is not None:
        if not isinstance(policy.deadline_at, datetime):
            raise RoundDomainError("deadline_at must be a datetime")
        if (
            policy.deadline_at.tzinfo is None
            or policy.deadline_at.utcoffset() != timedelta(0)
        ):
            raise RoundDomainError("deadline_at must be a timezone-aware UTC datetime")
    if policy.visibility not in _ALLOWED_VISIBILITY:
        raise RoundDomainError(f"unsupported visibility: {policy.visibility!r}")
    if policy.tie_break_mode not in _DEFAULT_TIE_MODES | _RANDOMIZED_TIE_MODES:
        raise RoundDomainError(f"unsupported tie_break_mode: {policy.tie_break_mode!r}")
    if policy.tie_break_mode in _RANDOMIZED_TIE_MODES:
        if policy.seed is None:
            raise RoundDomainError("seed is required for randomized tie-breaking")
        if isinstance(policy.seed, bool) or not isinstance(policy.seed, int):
            raise RoundDomainError("seed must be an integer for randomized tie-breaking")
    return policy


def _seeded_key(seed: int, team_id: str) -> str:
    return hashlib.sha256(f"{seed}:{team_id}".encode("utf-8")).hexdigest()


def rank_results(
    results: Sequence[TeamResultRecord],
    tie_break_mode: str = "default",
    seed: int | None = None,
) -> tuple[TeamResultRecord, ...]:
    """Rank results by descending authoritative total.

    Default ranking uses competition ranks, so equal totals share a rank. A
    seeded mode orders only equal-total groups using a stable hash of the seed
    and team ID, making the result independent of input/presentation order.
    """
    if tie_break_mode not in _DEFAULT_TIE_MODES | _RANDOMIZED_TIE_MODES:
        raise RoundDomainError(f"unsupported tie_break_mode: {tie_break_mode!r}")
    if tie_break_mode in _RANDOMIZED_TIE_MODES:
        if seed is None:
            raise RoundDomainError("seed is required for randomized tie-breaking")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise RoundDomainError("seed must be an integer for randomized tie-breaking")
        team_ids = [result.team_id for result in results]
        if len(team_ids) != len(set(team_ids)):
            raise RoundDomainError("duplicate team_id is not allowed in seeded ranking")
    for result in results:
        if (
            isinstance(result.authoritative_total, bool)
            or not isinstance(result.authoritative_total, Real)
            or not math.isfinite(result.authoritative_total)
        ):
            raise RoundDomainError("authoritative_total must be finite")

    ordered = sorted(results, key=lambda item: (-item.authoritative_total, item.team_id))
    if tie_break_mode in _RANDOMIZED_TIE_MODES:
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and ordered[end].authoritative_total == ordered[start].authoritative_total:
                end += 1
            ordered[start:end] = sorted(
                ordered[start:end], key=lambda item: _seeded_key(seed, item.team_id)  # type: ignore[arg-type]
            )
            start = end

    ranked: list[TeamResultRecord] = []
    previous_total: float | None = None
    previous_rank = 0
    for position, result in enumerate(ordered, start=1):
        is_tied = previous_total == result.authoritative_total
        rank = position if tie_break_mode in _RANDOMIZED_TIE_MODES or not is_tied else previous_rank
        ranked.append(replace(result, rank=rank, tie_group=str(rank) if rank else None))
        previous_total = result.authoritative_total
        previous_rank = rank
    return tuple(ranked)
