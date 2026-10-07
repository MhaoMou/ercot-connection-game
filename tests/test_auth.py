from datetime import datetime, timedelta, timezone
import secrets
import sqlite3

import pytest
import ercot_game.auth as auth_module

from ercot_game.auth import (
    AuthorizationError,
    AuthenticationError,
    SessionManager,
    SessionRecord,
)
from ercot_game.round_models import RoundPolicy, RoundRecord, RoundState
from ercot_game.round_store import RoundStore


UTC = timezone.utc


def make_round(round_id, teams=("team-a", "team-b")):
    return RoundRecord(round_id, policy=RoundPolicy("scenario", "1", "eval-1"))


@pytest.fixture
def store(tmp_path):
    store = RoundStore(tmp_path / "rounds.sqlite3")
    store.create_round(make_round("round-1"), teams=("team-a", "team-b"))
    store.create_round(make_round("round-2"), teams=("team-a",))
    return store


def test_issued_token_is_only_returned_in_plaintext_and_database_stores_hash(store):
    manager = SessionManager(store)

    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")

    assert issued.token
    row = store.connection.execute("SELECT * FROM sessions WHERE session_id = ?", (issued.record.session_id,)).fetchone()
    assert row["token_hash"] != issued.token
    assert row["token_salt"]
    assert row["token_hash"]
    assert issued.record.created_at.tzinfo is UTC
    assert issued.record.revoked_at is None


def test_wrong_token_is_rejected(store):
    manager = SessionManager(store)
    manager.issue("student-1", "round-1", role="student", team_id="team-a")

    with pytest.raises(AuthenticationError):
        manager.authenticate("wrong-token")


def test_expired_session_is_rejected(store):
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    manager = SessionManager(store, clock=lambda: current[0])
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a", ttl=timedelta(seconds=10))
    current[0] += timedelta(seconds=10)

    with pytest.raises(AuthenticationError, match="expired"):
        manager.authenticate(issued.token)


def test_revoked_session_is_rejected(store):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")

    manager.revoke(issued.token)

    with pytest.raises(AuthenticationError, match="revoked"):
        manager.authenticate(issued.token)


def test_student_can_access_only_assigned_team_and_round(store):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
    session = manager.authenticate(issued.token)

    assert manager.authorize(session, round_id="round-1", team_id="team-a") == session
    with pytest.raises(AuthorizationError):
        manager.authorize(session, round_id="round-1", team_id="team-b")
    with pytest.raises(AuthorizationError):
        manager.authorize(session, round_id="round-2", team_id="team-a")


def test_student_is_rejected_by_instructor_only_authorization_gate(store):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
    session = manager.authenticate(issued.token)

    with pytest.raises(AuthorizationError, match="instructor"):
        manager.authorize(session, round_id="round-1", required_role="instructor")
    with pytest.raises(AuthorizationError, match="instructor"):
        manager.authorize(session, round_id="round-1", require_instructor=True)


def test_authorize_does_not_trust_a_forged_session_record(store):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
    session = manager.authenticate(issued.token)
    forged = SessionRecord(session.session_id, "attacker", "round-1", "team-b", "student", session.created_at)

    with pytest.raises(AuthorizationError):
        manager.authorize(forged, round_id="round-1", team_id="team-b")


def test_authorize_rechecks_revocation_after_authentication(store):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
    session = manager.authenticate(issued.token)
    manager.revoke(issued.token)

    with pytest.raises(AuthenticationError, match="revoked"):
        manager.authorize(session, round_id="round-1", team_id="team-a")


def test_manager_accepts_raw_sqlite_connection(tmp_path):
    connection = sqlite3.connect(":memory:")
    store = RoundStore(connection)
    store.create_round(make_round("round-1"), teams=("team-a",))
    connection.row_factory = None
    manager = SessionManager(connection)

    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")

    assert manager.authenticate(issued.token).actor_id == "student-1"


def test_authentication_rejects_malformed_persisted_rows_as_authentication_failure(store):
    manager = SessionManager(store)
    malformed = []
    for field, value in (("role", "admin"), ("team_id", None), ("token_salt", b"bad"), ("token_hash", b"bad")):
        issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
        if field == "team_id":
            value = None
        store.connection.execute(f"UPDATE sessions SET {field} = ? WHERE session_id = ?", (value, issued.record.session_id))
        malformed.append(issued.token)

    for token in malformed:
        with pytest.raises(AuthenticationError):
            manager.authenticate(token)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", ""),
        ("actor_id", ""),
        ("round_id", ""),
        ("team_id", ""),
        ("role", "instructor"),
    ],
)
def test_reconstruction_rejects_malformed_identity_and_assignments(store, field, value):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
    if field in {"round_id", "team_id"}:
        store.connection.execute("PRAGMA foreign_keys = OFF")
    store.connection.execute(f"UPDATE sessions SET {field} = ? WHERE session_id = ?", (value, issued.record.session_id))
    if field in {"round_id", "team_id"}:
        store.connection.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(AuthenticationError):
        manager.authenticate(issued.token)


def test_persisted_salt_and_hash_require_exact_lengths(store):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")

    for field, value in (("token_salt", b"x" * 15), ("token_hash", b"x" * 31)):
        store.connection.execute(f"UPDATE sessions SET {field} = ? WHERE session_id = ?", (value, issued.record.session_id))
        with pytest.raises(AuthenticationError):
            manager.authenticate(issued.token)
        valid = secrets.token_bytes(16) if field == "token_salt" else manager._hash(issued.token, secrets.token_bytes(16))
        if field == "token_hash":
            row = store.connection.execute("SELECT token_salt FROM sessions WHERE session_id = ?", (issued.record.session_id,)).fetchone()
            valid = manager._hash(issued.token, bytes(row["token_salt"]))
        store.connection.execute(f"UPDATE sessions SET {field} = ? WHERE session_id = ?", (valid, issued.record.session_id))


def test_raw_connection_issue_persists_across_reopen(tmp_path):
    database = tmp_path / "sessions.sqlite3"
    first_connection = sqlite3.connect(database)
    first_store = RoundStore(first_connection)
    first_store.create_round(make_round("round-1"), teams=("team-a",))
    first_manager = SessionManager(first_connection)
    issued = first_manager.issue("student-1", "round-1", role="student", team_id="team-a")
    first_connection.close()

    reopened_connection = sqlite3.connect(database)
    reopened_store = RoundStore(reopened_connection)
    assert SessionManager(reopened_connection).authenticate(issued.token).actor_id == "student-1"
    reopened_connection.close()


def test_raw_connection_revoke_is_visible_across_connections(tmp_path):
    database = tmp_path / "revocation.sqlite3"
    first_connection = sqlite3.connect(database)
    first_store = RoundStore(first_connection)
    first_store.create_round(make_round("round-1"), teams=("team-a",))
    issued = SessionManager(first_connection).issue("student-1", "round-1", role="student", team_id="team-a")
    first_connection.close()

    second_connection = sqlite3.connect(database)
    second_manager = SessionManager(second_connection)
    second_manager.revoke(issued.token)
    second_connection.close()

    third_connection = sqlite3.connect(database)
    with pytest.raises(AuthenticationError, match="revoked"):
        SessionManager(third_connection).authenticate(issued.token)
    third_connection.close()


def test_lookup_key_limits_pbkdf2_to_the_single_indexed_candidate(store, monkeypatch):
    manager = SessionManager(store)
    issued = [manager.issue(f"student-{i}", "round-1", role="student", team_id="team-a") for i in range(3)]
    calls = 0
    original_hash = manager._hash

    def counting_hash(token, salt):
        nonlocal calls
        calls += 1
        return original_hash(token, salt)

    monkeypatch.setattr(manager, "_hash", counting_hash)
    assert manager.authenticate(issued[1].token).actor_id == "student-1"
    assert calls == 1
    indexes = store.connection.execute("PRAGMA index_list(sessions)").fetchall()
    assert any("token_key" in row["name"] for row in indexes)


def test_instructor_can_manage_any_team_in_their_round(store):
    manager = SessionManager(store)
    issued = manager.issue("instructor-1", "round-1", role="instructor")
    session = manager.authenticate(issued.token)

    assert manager.authorize(session, round_id="round-1", team_id="team-a") == session
    assert manager.authorize(session, round_id="round-1", team_id="team-b") == session
    with pytest.raises(AuthorizationError):
        manager.authorize(session, round_id="round-2", team_id="team-a")


def test_instructor_authorization_rejects_nonexistent_team(store):
    manager = SessionManager(store)
    issued = manager.issue("instructor-1", "round-1", role="instructor")
    session = manager.authenticate(issued.token)

    with pytest.raises(AuthorizationError, match="team"):
        manager.authorize(session, round_id="round-1", team_id="missing-team", require_instructor=True)


def test_authentication_uses_constant_time_digest_comparison(store, monkeypatch):
    manager = SessionManager(store)
    issued = manager.issue("student-1", "round-1", role="student", team_id="team-a")
    calls = []
    original_compare = auth_module.hmac.compare_digest

    def recording_compare(left, right):
        calls.append((left, right))
        return original_compare(left, right)

    monkeypatch.setattr(auth_module.hmac, "compare_digest", recording_compare)
    manager.authenticate(issued.token)

    assert len(calls) == 1


def test_malformed_inputs_are_rejected_without_writing_a_session(store):
    manager = SessionManager(store)

    cases = (
        dict(actor_id="", round_id="round-1", role="student", team_id="team-a"),
        dict(actor_id="student", round_id="missing", role="student", team_id="team-a"),
        dict(actor_id="student", round_id="round-1", role="student"),
        dict(actor_id="student", round_id="round-1", role="admin", team_id="team-a"),
        dict(actor_id="student", round_id="round-1", role="student", team_id="missing"),
    )
    for case in cases:
        with pytest.raises((ValueError, KeyError)):
            manager.issue(**case)

    assert store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_session_record_rejects_naive_or_non_utc_timestamps():
    with pytest.raises(ValueError, match="UTC"):
        SessionRecord("s", "actor", "round", None, "student", datetime.now())
