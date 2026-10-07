import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ercot_game.round_models import (
    EvaluationRunRecord,
    RoundPolicy,
    RoundRecord,
    RoundState,
    TeamResultRecord,
)
from ercot_game.round_store import RoundStore


@pytest.fixture
def store(tmp_path):
    return RoundStore(tmp_path / "rounds.sqlite3")


def make_round(round_id="round-1"):
    return RoundRecord(
        round_id,
        policy=RoundPolicy(
            scenario_id="scenario",
            scenario_version="1",
            evaluator_version="eval-1",
            deadline_seconds=60,
        ),
    )


def open_round(store, teams=("team-a",)):
    store.create_round(make_round(), teams=teams)
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")


def locked_round(store, teams=("team-a",)):
    open_round(store, teams)
    return store.lock_submission_snapshot("round-1", actor_id="instructor")


def test_create_round_persists_policy_and_team_membership(store):
    store.create_round(make_round(), teams=("team-a", "team-b"))

    loaded = store.get_round("round-1")
    assert loaded is not None
    assert loaded.round_id == "round-1"
    assert loaded.state is RoundState.DRAFT
    assert loaded.policy == make_round().policy
    assert loaded.created_at is not None
    assert store.list_teams("round-1") == ("team-a", "team-b")


def test_transition_round_is_validated_and_audited(store):
    store.create_round(make_round())

    opened = store.transition_round("round-1", RoundState.OPEN, actor_id="instructor", reason="start")

    assert opened.state is RoundState.OPEN
    events = store.export_round_bundle("round-1")["audit_events"]
    assert events[-1]["action"] == "round.transition"
    assert events[-1]["metadata"] == {"from": "draft", "to": "open", "reason": "start"}


def test_invalid_transition_rolls_back_without_audit_event(store):
    store.create_round(make_round())

    with pytest.raises(ValueError):
        store.transition_round("round-1", RoundState.PUBLISHED, actor_id="instructor")

    assert store.get_round("round-1").state is RoundState.DRAFT
    assert store.export_round_bundle("round-1")["audit_events"] == []


def test_drafts_replace_while_team_data_is_isolated(store):
    store.create_round(make_round(), teams=("team-a", "team-b"))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")

    store.upsert_draft("round-1", "team-a", {"load": 1}, revision=1)
    store.upsert_draft("round-1", "team-a", {"load": 2}, revision=2)
    store.upsert_draft("round-1", "team-b", {"load": 9}, revision=1)

    assert store.get_draft("round-1", "team-a")["payload"] == {"load": 2}
    assert store.get_draft("round-1", "team-a")["revision"] == 2
    assert store.get_draft("round-1", "team-b")["payload"] == {"load": 9}


def test_submission_idempotency_and_immutability(store):
    store.create_round(make_round(), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    first = store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "request-1")
    replay = store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "request-1")

    assert replay == first
    assert store.get_team_submission("round-1", "team-a").payload == {"load": 1}
    with pytest.raises(sqlite3.DatabaseError):
        store.connection.execute("UPDATE submissions SET payload_json = '{}' WHERE submission_id = ?", (first.submission_id,))


def test_team_membership_is_immutable_through_direct_sql(store):
    store.create_round(make_round(), teams=("team-a",))

    with pytest.raises(sqlite3.DatabaseError):
        store.connection.execute("UPDATE teams SET display_name = 'changed' WHERE round_id = 'round-1' AND team_id = 'team-a'")
    with pytest.raises(sqlite3.DatabaseError):
        store.connection.execute("DELETE FROM teams WHERE round_id = 'round-1' AND team_id = 'team-a'")


def test_locked_round_rejects_draft_and_submission_writes(store):
    store.create_round(make_round(), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    store.upsert_draft("round-1", "team-a", {"load": 1})
    store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "request-1")
    store.lock_submission_snapshot("round-1", actor_id="instructor")

    with pytest.raises(ValueError):
        store.upsert_draft("round-1", "team-a", {"load": 2})
    with pytest.raises(ValueError):
        store.insert_submission("round-1", "team-a", {"load": 2}, "hash-2", "request-2")


def test_submission_deadline_seconds_is_enforced_by_injected_utc_clock(tmp_path):
    current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    store = RoundStore(tmp_path / "deadline.sqlite3", clock=lambda: current[0])
    store.create_round(make_round(), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    current[0] += timedelta(seconds=61)

    with pytest.raises(ValueError, match="deadline"):
        store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "late")
    assert store.get_team_submission("round-1", "team-a") is None


def test_submission_explicit_deadline_at_is_enforced_by_injected_utc_clock(tmp_path):
    current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    store = RoundStore(tmp_path / "deadline-at.sqlite3", clock=lambda: current[0])
    policy = RoundPolicy("scenario", "1", "eval-1", deadline_at=current[0] + timedelta(seconds=30))
    store.create_round(RoundRecord("round-1", policy=policy), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    current[0] += timedelta(seconds=31)

    with pytest.raises(ValueError, match="deadline"):
        store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "late")


def test_draft_deadline_is_enforced_by_injected_utc_clock(tmp_path):
    current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    store = RoundStore(tmp_path / "draft-deadline.sqlite3", clock=lambda: current[0])
    store.create_round(make_round(), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    current[0] += timedelta(seconds=61)

    with pytest.raises(ValueError, match="round deadline has passed"):
        store.upsert_draft("round-1", "team-a", {"load": 1})
    assert store.get_draft("round-1", "team-a") is None


def test_lock_snapshot_uses_domain_transition_and_audits_state_metadata(store):
    open_round(store, teams=("team-a",))

    snapshot = store.lock_submission_snapshot("round-1", actor_id="instructor")

    assert snapshot == ()
    assert store.get_round("round-1").state is RoundState.LOCKED
    event = store.export_round_bundle("round-1")["audit_events"][-1]
    assert event["action"] == "round.lock"
    assert event["metadata"] == {
        "from": "open",
        "to": "locked",
        "previous_state": "open",
        "new_state": "locked",
        "reason": "submission snapshot locked",
    }


def test_lock_snapshot_invalid_transition_is_atomic_and_has_no_lock_audit(store):
    store.create_round(make_round(), teams=("team-a",))

    with pytest.raises(ValueError, match="cannot transition"):
        store.lock_submission_snapshot("round-1", actor_id="instructor")

    assert store.get_round("round-1").state is RoundState.DRAFT
    assert store.export_round_bundle("round-1")["audit_events"] == []


def test_all_generated_timestamps_use_injected_utc_clock(tmp_path):
    fixed = datetime(2026, 1, 1, 12, 34, 56, 789012, tzinfo=timezone.utc)
    store = RoundStore(tmp_path / "clock.sqlite3", clock=lambda: fixed)
    store.create_round(make_round(), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    store.upsert_draft("round-1", "team-a", {"load": 1})
    submission = store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "key-1")
    store.lock_submission_snapshot("round-1", actor_id="instructor")
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))
    store.record_audit_event("round-1", actor_id="instructor", action="test")

    round_record = store.get_round("round-1")
    draft = store.get_draft("round-1", "team-a")
    run = store.get_evaluation_run("run-1")
    audit_events = store.export_round_bundle("round-1")["audit_events"]
    assert round_record.created_at == fixed
    assert round_record.opened_at == fixed
    assert round_record.locked_at == fixed
    assert draft["updated_at"] == fixed
    assert submission.submitted_at == fixed
    assert run.started_at == fixed
    assert run.completed_at == fixed
    assert all(datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")) == fixed for event in audit_events)
    assert all(datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo == timezone.utc for value in (
        store.export_round_bundle("round-1")["round"]["created_at"],
        store.export_round_bundle("round-1")["round"]["opened_at"],
        store.export_round_bundle("round-1")["round"]["locked_at"],
    ))


def test_evaluation_runs_and_team_results_are_immutable_at_sql_boundary(store):
    locked_round(store)
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))
    store.store_results("run-1", (TeamResultRecord("team-a", 1.0),))

    for statement in (
        "UPDATE evaluation_runs SET status = 'failed' WHERE evaluation_run_id = 'run-1'",
        "DELETE FROM evaluation_runs WHERE evaluation_run_id = 'run-1'",
        "UPDATE team_results SET authoritative_total = 2.0 WHERE evaluation_run_id = 'run-1'",
        "DELETE FROM team_results WHERE evaluation_run_id = 'run-1'",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(statement)

    assert store.get_evaluation_run("run-1") is not None
    assert store.connection.execute("SELECT COUNT(*) FROM team_results WHERE evaluation_run_id = 'run-1'").fetchone()[0] == 1


def test_evaluation_results_and_export_are_deterministic(store, tmp_path):
    locked_round(store, teams=("team-b", "team-a"))
    run = EvaluationRunRecord("run-1", "round-1", "batch-hash", seed=7)
    store.create_evaluation_run(run)
    store.store_results(
        "run-1",
        (
            TeamResultRecord("team-b", 2.0, rank=2, diagnostics={"ok": True}),
            TeamResultRecord("team-a", 3.0, rank=1),
        ),
    )
    first = store.export_round_bundle("round-1")
    reopened = RoundStore(tmp_path / "rounds.sqlite3")
    assert reopened.export_round_bundle("round-1") == first
    assert json.dumps(first, sort_keys=True) == json.dumps(reopened.export_round_bundle("round-1"), sort_keys=True)


@pytest.mark.parametrize("state", [RoundState.DRAFT, RoundState.OPEN])
def test_evaluation_run_requires_locked_snapshot(store, state):
    store.create_round(make_round(), teams=("team-a",))
    if state is RoundState.OPEN:
        store.transition_round("round-1", state, actor_id="instructor")

    with pytest.raises(ValueError, match="locked"):
        store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))


def test_results_require_exact_nonempty_team_coverage_and_roll_back(store):
    locked_round(store, teams=("team-a", "team-b"))
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))
    result_a = TeamResultRecord("team-a", 1.0)
    result_b = TeamResultRecord("team-b", 2.0)

    for results in ((), (result_a,), (result_a, result_a), (result_a, TeamResultRecord("unknown", 3.0))):
        with pytest.raises((ValueError, KeyError), match="team|result|coverage|duplicate|empty"):
            store.store_results("run-1", results)
        assert store.connection.execute("SELECT COUNT(*) FROM team_results").fetchone()[0] == 0

    store.store_results("run-1", (result_a, result_b))


def test_duplicate_idempotency_key_rejects_mismatch_but_exact_request_replays(store):
    open_round(store)
    first = store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "same-key")
    assert store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "same-key") == first
    with pytest.raises(ValueError, match="idempotency"):
        store.insert_submission("round-1", "team-b", {"load": 1}, "hash-1", "same-key")
    with pytest.raises(ValueError, match="idempotency"):
        store.insert_submission("round-1", "team-a", {"load": 2}, "hash-2", "same-key")


def test_lock_snapshot_uses_submission_id_as_tie_breaker(store):
    open_round(store)
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.insert_submission("round-1", "team-a", {"load": 1}, "hash-1", "key-1", submission_id="submission-a", submitted_at=timestamp)
    store.insert_submission("round-1", "team-a", {"load": 2}, "hash-2", "key-2", submission_id="submission-b", submitted_at=timestamp)

    snapshot = store.lock_submission_snapshot("round-1", actor_id="instructor")

    assert [submission.submission_id for submission in snapshot] == ["submission-b"]
    assert snapshot[0].payload == {"load": 2}


def test_draft_revision_is_positive_integer_and_compare_and_swap(store):
    open_round(store)
    with pytest.raises(ValueError, match="revision"):
        store.upsert_draft("round-1", "team-a", {}, revision=0)
    with pytest.raises(ValueError, match="revision"):
        store.upsert_draft("round-1", "team-a", {}, revision=True)
    store.upsert_draft("round-1", "team-a", {"v": 1}, revision=2)
    with pytest.raises(ValueError, match="revision"):
        store.upsert_draft("round-1", "team-a", {"v": 0}, revision=1)
    with pytest.raises(ValueError, match="revision"):
        store.upsert_draft("round-1", "team-a", {"v": 2}, revision=2)


def test_utc_inputs_are_rejected_at_persistence_boundary(store):
    with pytest.raises(ValueError, match="UTC"):
        store.create_round(RoundRecord("bad", policy=RoundPolicy("s", "1", "e"), created_at=datetime.now()))
    with pytest.raises(ValueError, match="UTC"):
        store.create_round(RoundRecord("bad-deadline", policy=RoundPolicy("s", "1", "e", deadline_at=datetime.now())))
    open_round(store)
    with pytest.raises(ValueError, match="UTC"):
        store.insert_submission("round-1", "team-a", {}, "hash", "key", submitted_at=datetime.now())
    store.lock_submission_snapshot("round-1", actor_id="instructor")
    with pytest.raises(ValueError, match="UTC"):
        store.create_evaluation_run(EvaluationRunRecord("bad-run", "round-1", "batch", started_at=datetime.now()))


def test_utc_timestamps_are_timezone_aware(store):
    store.create_round(make_round())
    loaded = store.get_round("round-1")
    assert loaded.created_at is not None
    assert loaded.created_at.tzinfo == timezone.utc
    assert loaded.created_at.utcoffset() == datetime.now(timezone.utc).utcoffset()


def test_schema_foreign_keys_and_unique_membership_are_enforced(store):
    store.create_round(make_round(), teams=("team-a",))

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("INSERT INTO teams VALUES ('round-1', 'team-a', 'duplicate')")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("INSERT INTO drafts VALUES ('missing', 'team-a', '{}', 1, '2026-01-01T00:00:00Z')")


def test_team_results_use_round_scoped_composite_foreign_key(store):
    locked_round(store)
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "INSERT INTO team_results VALUES ('run-1', 'round-1', 'missing', 1.0, NULL, NULL, 'private', NULL)"
        )


def test_team_results_cannot_cross_rounds_for_the_same_team_and_run(store):
    store.create_round(make_round("round-1"), teams=("team-a",))
    store.create_round(make_round("round-2"), teams=("team-a",))
    store.transition_round("round-1", RoundState.OPEN, actor_id="instructor")
    store.transition_round("round-2", RoundState.OPEN, actor_id="instructor")
    store.lock_submission_snapshot("round-1", actor_id="instructor")
    store.lock_submission_snapshot("round-2", actor_id="instructor")
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "INSERT INTO team_results VALUES ('run-1', 'round-2', 'team-a', 1.0, NULL, NULL, 'private', NULL)"
        )


def test_direct_round_delete_is_rejected_and_membership_remains(store):
    store.create_round(make_round(), teams=("team-a",))

    with pytest.raises(sqlite3.IntegrityError, match="deletion"):
        store.connection.execute("DELETE FROM rounds WHERE round_id = 'round-1'")
    assert store.list_teams("round-1") == ("team-a",)


def test_no_team_round_with_dependent_records_cannot_be_deleted(store):
    store.create_round(make_round("empty-round"))
    store.transition_round("empty-round", RoundState.OPEN, actor_id="instructor")
    store.lock_submission_snapshot("empty-round", actor_id="instructor")
    store.create_evaluation_run(EvaluationRunRecord("empty-run", "empty-round", "batch"))
    store.record_audit_event("empty-round", actor_id="instructor", action="test")
    store.connection.execute(
        "INSERT INTO sessions(session_id, actor_id, round_id, team_id, role, expires_at) "
        "VALUES ('session-1', 'actor-1', 'empty-round', NULL, 'instructor', NULL)"
    )

    with pytest.raises(sqlite3.IntegrityError, match="deletion"):
        store.connection.execute("DELETE FROM rounds WHERE round_id = 'empty-round'")

    assert store.get_round("empty-round") is not None
    assert store.get_evaluation_run("empty-run") is not None
    assert store.connection.execute("SELECT COUNT(*) FROM sessions WHERE round_id = 'empty-round'").fetchone()[0] == 1


def test_round_deletion_is_unconditionally_rejected_even_without_dependents(store):
    store.create_round(make_round("undeletable"))

    with pytest.raises(sqlite3.DatabaseError, match="deletion"):
        store.connection.execute("DELETE FROM rounds WHERE round_id = 'undeletable'")
    assert store.get_round("undeletable") is not None


def test_database_rejects_invalid_round_state_and_policy_values(store):
    store.create_round(make_round())

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE rounds SET state = 'not-a-state' WHERE round_id = 'round-1'")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE rounds SET visibility = 'secret' WHERE round_id = 'round-1'")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE rounds SET tie_break_mode = 'not-a-mode' WHERE round_id = 'round-1'")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE rounds SET deadline_seconds = -1 WHERE round_id = 'round-1'")


@pytest.mark.parametrize(
    "result",
    [
        TeamResultRecord("team-a", math.inf),
        TeamResultRecord("team-a", 1.0, rank=0),
        TeamResultRecord("team-a", 1.0, rank=True),
        TeamResultRecord("team-a", 1.0, visibility="secret"),
        TeamResultRecord("team-a", 1.0, diagnostics=[]),
    ],
)
def test_malformed_result_values_are_rejected_before_insert(store, result):
    locked_round(store)
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))

    with pytest.raises(ValueError):
        store.store_results("run-1", (result,))
    assert store.connection.execute("SELECT COUNT(*) FROM team_results").fetchone()[0] == 0


def test_malformed_result_after_valid_result_rolls_back_the_batch(store):
    locked_round(store, teams=("team-a", "team-b"))
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))

    with pytest.raises(ValueError):
        store.store_results(
            "run-1",
            (TeamResultRecord("team-a", 1.0), TeamResultRecord("team-b", math.nan)),
        )
    assert store.connection.execute("SELECT COUNT(*) FROM team_results").fetchone()[0] == 0


def test_result_batch_rolls_back_if_one_team_is_invalid(store):
    locked_round(store)
    store.create_evaluation_run(EvaluationRunRecord("run-1", "round-1", "batch"))

    with pytest.raises(ValueError):
        store.store_results("run-1", (TeamResultRecord("team-a", 1.0), TeamResultRecord("missing", 2.0)))

    assert store.connection.execute("SELECT COUNT(*) FROM team_results").fetchone()[0] == 0
