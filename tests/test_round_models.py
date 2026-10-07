from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from ercot_game.round_models import (
    ActorRole,
    EvaluationRunRecord,
    InvalidTransitionError,
    RoundDomainError,
    RoundPolicy,
    RoundRecord,
    RoundState,
    SessionRecord,
    SubmissionRecord,
    TeamResultRecord,
    rank_results,
    transition_allowed,
    validate_round_policy,
)


def test_round_lifecycle_accepts_only_published_paths_and_failure_paths():
    accepted = {
        (RoundState.DRAFT, RoundState.OPEN),
        (RoundState.OPEN, RoundState.LOCKED),
        (RoundState.LOCKED, RoundState.EVALUATED),
        (RoundState.EVALUATED, RoundState.PUBLISHED),
        (RoundState.EVALUATED, RoundState.FAILED),
        (RoundState.PUBLISHED, RoundState.RETRACTED),
    }

    for current, target in accepted:
        assert transition_allowed(current, target)

    assert not transition_allowed(RoundState.DRAFT, RoundState.LOCKED)
    assert not transition_allowed(RoundState.PUBLISHED, RoundState.OPEN)
    with pytest.raises(InvalidTransitionError) as error:
        RoundRecord("round-1", RoundState.DRAFT).transition(RoundState.PUBLISHED)
    assert error.value.code == "invalid_transition"


def test_round_policy_rejects_missing_versions_negative_deadline_and_bad_visibility():
    valid = RoundPolicy(
        scenario_id="scenario-1",
        scenario_version="2026.09",
        evaluator_version="0.3.0",
        deadline_seconds=3600,
        visibility="private",
    )
    assert validate_round_policy(valid) == valid

    for field, value in (
        ("scenario_id", ""),
        ("scenario_version", ""),
        ("evaluator_version", ""),
        ("deadline_seconds", -1),
        ("visibility", "secret"),
    ):
        with pytest.raises(RoundDomainError):
            validate_round_policy(valid.__class__(**{**valid.__dict__, field: value}))


def test_randomized_tie_breaking_requires_a_seed():
    policy = RoundPolicy(
        scenario_id="scenario-1",
        scenario_version="2026.09",
        evaluator_version="0.3.0",
        tie_break_mode="seeded_random",
    )
    with pytest.raises(RoundDomainError, match="seed"):
        validate_round_policy(policy)


def test_round_domain_records_are_frozen_and_roles_are_strings():
    assert RoundState.OPEN.value == "open"
    assert ActorRole.INSTRUCTOR.value == "instructor"
    assert RoundRecord("round-1", RoundState.OPEN).state is RoundState.OPEN
    SessionRecord("actor-1", "round-1", "team-1", ActorRole.STUDENT)
    SubmissionRecord("submission-1", "round-1", "team-1", "hash", "key")
    EvaluationRunRecord("run-1", "round-1", "batch-hash")
    result = TeamResultRecord("team-1", 10.0)
    with pytest.raises(FrozenInstanceError):
        result.authoritative_total = 11.0


def test_default_ranking_is_descending_and_equal_ranks_ties_independent_of_input_order():
    results = (
        TeamResultRecord("team-b", 10.0),
        TeamResultRecord("team-c", 20.0),
        TeamResultRecord("team-a", 20.0),
    )
    ranked = rank_results(results, "default", None)
    assert [(item.team_id, item.rank) for item in ranked] == [
        ("team-a", 1),
        ("team-c", 1),
        ("team-b", 3),
    ]
    reordered = rank_results(tuple(reversed(results)), "default", None)
    assert [(item.team_id, item.rank) for item in reordered] == [
        ("team-a", 1),
        ("team-c", 1),
        ("team-b", 3),
    ]


def test_seeded_tie_breaking_is_deterministic_and_requires_seed():
    results = (TeamResultRecord("team-a", 10.0), TeamResultRecord("team-b", 10.0))
    first = rank_results(results, "seeded_random", 17)
    second = rank_results(tuple(reversed(results)), "seeded_random", 17)
    assert first == second
    assert [item.rank for item in first] == [1, 2]
    with pytest.raises(RoundDomainError, match="seed"):
        rank_results(results, "seeded_random", None)


@pytest.mark.parametrize("deadline_seconds", ["3600", True, float("nan"), float("inf")])
def test_policy_rejects_non_numeric_or_non_finite_deadline_values(deadline_seconds):
    policy = RoundPolicy(
        scenario_id="scenario-1",
        scenario_version="2026.09",
        evaluator_version="0.3.0",
        deadline_seconds=deadline_seconds,
    )
    with pytest.raises(RoundDomainError):
        validate_round_policy(policy)


@pytest.mark.parametrize("total", ["10.0", True, float("nan"), float("inf")])
def test_ranking_rejects_non_numeric_or_non_finite_authoritative_totals(total):
    with pytest.raises(RoundDomainError):
        rank_results((TeamResultRecord("team-1", total),))


def test_policy_requires_timezone_aware_utc_deadline():
    base = dict(
        scenario_id="scenario-1",
        scenario_version="2026.09",
        evaluator_version="0.3.0",
    )
    for deadline_at in (
        datetime(2026, 9, 29, 12, 0),
        datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None),
    ):
        with pytest.raises(RoundDomainError, match="UTC"):
            validate_round_policy(RoundPolicy(**base, deadline_at=deadline_at))

    assert validate_round_policy(
        RoundPolicy(**base, deadline_at=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc))
    ).deadline_at.tzinfo is timezone.utc


@pytest.mark.parametrize("seed", [True, False, "17", 17.0])
def test_randomized_tie_breaking_requires_an_integer_non_bool_seed(seed):
    policy = RoundPolicy(
        scenario_id="scenario-1",
        scenario_version="2026.09",
        evaluator_version="0.3.0",
        tie_break_mode="seeded_random",
        seed=seed,
    )
    with pytest.raises(RoundDomainError, match="integer"):
        validate_round_policy(policy)
    with pytest.raises(RoundDomainError, match="integer"):
        rank_results((TeamResultRecord("team-1", 1.0),), "seeded_random", seed)


def test_seeded_ranking_rejects_duplicate_team_ids():
    results = (TeamResultRecord("team-1", 10.0), TeamResultRecord("team-1", 10.0))
    with pytest.raises(RoundDomainError, match="duplicate team_id"):
        rank_results(results, "seeded_random", 17)
