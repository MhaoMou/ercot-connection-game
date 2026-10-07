"""Classroom session authentication and round-scoped authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import sqlite3
from typing import Callable
import uuid


class AuthenticationError(ValueError):
    """The supplied credential is not an active session."""


class AuthorizationError(ValueError):
    """A session is not permitted to access the requested scope."""


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    actor_id: str
    round_id: str
    team_id: str | None
    role: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.role not in {"student", "instructor"}:
            raise ValueError("role must be student or instructor")
        for name in ("created_at", "expires_at", "revoked_at"):
            _validate_utc(getattr(self, name), name, allow_none=name != "created_at")


@dataclass(frozen=True)
class IssuedSession:
    token: str
    record: SessionRecord


def _validate_utc(value: datetime | None, name: str, *, allow_none: bool) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    normalized = _validate_utc(value, "timestamp", allow_none=False)
    assert normalized is not None
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_stamp(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise AuthenticationError(f"malformed session {name}") from error
    normalized = _validate_utc(parsed, name, allow_none=False)
    assert normalized is not None
    return normalized


class SessionManager:
    """Issue and enforce sessions stored in a :class:`RoundStore` database.

    With a raw SQLite connection, issue/revoke commit only when the manager
    starts the write transaction. An already-active transaction remains
    caller-owned and is neither committed nor rolled back by this manager.
    """

    _HASH_ITERATIONS = 310_000

    def __init__(self, store_or_connection, *, clock: Callable[[], datetime] | None = None) -> None:
        self.connection: sqlite3.Connection = getattr(store_or_connection, "connection", store_or_connection)
        if not isinstance(self.connection, sqlite3.Connection):
            raise TypeError("store_or_connection must be a RoundStore or sqlite3.Connection")
        self.connection.row_factory = sqlite3.Row
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._migrate_sessions_table()

    def _migrate_sessions_table(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(sessions)")}
        additions = {
            "token_salt": "BLOB",
            "token_hash": "BLOB",
            "token_key": "TEXT",
            "created_at": "TEXT",
            "revoked_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token_key ON sessions(token_key)")

    def _now(self) -> datetime:
        value = self._clock()
        normalized = _validate_utc(value, "clock timestamp", allow_none=False)
        assert normalized is not None
        return normalized

    @staticmethod
    def _required_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value

    def issue(
        self,
        actor_id: str,
        round_id: str,
        *,
        role: str,
        team_id: str | None = None,
        ttl: timedelta | None = None,
        expires_at: datetime | None = None,
    ) -> IssuedSession:
        actor_id = self._required_text(actor_id, "actor_id")
        round_id = self._required_text(round_id, "round_id")
        if role not in {"student", "instructor"}:
            raise ValueError("role must be student or instructor")
        if role == "student":
            team_id = self._required_text(team_id, "team_id")
        elif team_id is not None:
            raise ValueError("instructor sessions cannot be assigned a team")
        if ttl is not None and (not isinstance(ttl, timedelta) or ttl <= timedelta(0)):
            raise ValueError("ttl must be a positive timedelta")
        if expires_at is not None:
            _validate_utc(expires_at, "expires_at", allow_none=False)
        if ttl is not None and expires_at is not None:
            raise ValueError("provide ttl or expires_at, not both")

        if self.connection.execute("SELECT 1 FROM rounds WHERE round_id = ?", (round_id,)).fetchone() is None:
            raise KeyError(round_id)
        if team_id is not None and self.connection.execute(
            "SELECT 1 FROM teams WHERE round_id = ? AND team_id = ?", (round_id, team_id)
        ).fetchone() is None:
            raise KeyError((round_id, team_id))

        created_at = self._now()
        expires_at = expires_at or (created_at + ttl if ttl is not None else None)
        token = secrets.token_urlsafe(32)
        salt = secrets.token_bytes(16)
        token_hash = self._hash(token, salt)
        token_key = self._token_key(token)
        session_id = str(uuid.uuid4())
        transaction_active = self.connection.in_transaction
        try:
            self.connection.execute(
                """INSERT INTO sessions(
                    session_id, actor_id, round_id, team_id, role, expires_at,
                    token_salt, token_hash, token_key, created_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (session_id, actor_id, round_id, team_id, role, _stamp(expires_at) if expires_at else None,
                 salt, token_hash, token_key, _stamp(created_at)),
            )
        except Exception:
            if not transaction_active and self.connection.in_transaction:
                self.connection.rollback()
            raise
        else:
            if not transaction_active and self.connection.in_transaction:
                self.connection.commit()
        return IssuedSession(token, SessionRecord(session_id, actor_id, round_id, team_id, role, created_at, expires_at))

    @classmethod
    def _hash(cls, token: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, cls._HASH_ITERATIONS)

    @staticmethod
    def _token_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _find(self, token: str):
        if not isinstance(token, str) or not token:
            raise AuthenticationError("invalid token")
        row = self.connection.execute("SELECT * FROM sessions WHERE token_key = ?", (self._token_key(token),)).fetchone()
        if row is None:
            raise AuthenticationError("invalid token")
        try:
            salt = self._blob(row["token_salt"], "token salt", expected_length=16)
            stored_hash = self._blob(row["token_hash"], "token hash", expected_length=32)
            candidate = self._hash(token, salt)
        except (TypeError, ValueError) as error:
            raise AuthenticationError("malformed session credential") from error
        if not hmac.compare_digest(candidate, stored_hash):
            raise AuthenticationError("invalid token")
        return row

    @staticmethod
    def _blob(value, name: str, *, expected_length: int) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)) or len(value) != expected_length:
            raise ValueError(f"{name} is malformed")
        return bytes(value)

    def authenticate(
        self, token: str, *, round_id: str | None = None, team_id: str | None = None
    ) -> SessionRecord:
        row = self._find(token)
        record = self._active_record(row)
        if round_id is not None or team_id is not None:
            self.authorize(record, round_id=round_id, team_id=team_id)
        return record

    def revoke(self, token: str) -> SessionRecord:
        row = self._find(token)
        revoked_at = _parse_stamp(row["revoked_at"], "revoked_at")
        if revoked_at is None:
            revoked_at = self._now()
            transaction_active = self.connection.in_transaction
            try:
                self.connection.execute("UPDATE sessions SET revoked_at = ? WHERE session_id = ?", (_stamp(revoked_at), row["session_id"]))
            except Exception:
                if not transaction_active and self.connection.in_transaction:
                    self.connection.rollback()
                raise
            else:
                if not transaction_active and self.connection.in_transaction:
                    self.connection.commit()
        return self._safe_record(row, revoked_at=revoked_at)

    def authorize(
        self,
        session: SessionRecord,
        *,
        round_id: str | None,
        team_id: str | None = None,
        required_role: str | None = None,
        require_instructor: bool = False,
    ) -> SessionRecord:
        if not isinstance(session, SessionRecord):
            raise AuthorizationError("invalid session record")
        if not isinstance(round_id, str) or not round_id:
            raise AuthorizationError("round_id is required")
        if required_role not in {None, "student", "instructor"}:
            raise AuthorizationError("required_role must be student or instructor")
        if require_instructor and required_role not in {None, "instructor"}:
            raise AuthorizationError("require_instructor conflicts with required_role")
        try:
            record = self._active_record_by_id(session.session_id)
        except AuthenticationError:
            raise
        if record.round_id != round_id:
            raise AuthorizationError("session cannot access another round")
        if require_instructor or required_role is not None:
            expected_role = "instructor" if require_instructor else required_role
            assert expected_role is not None
            if record.role != expected_role:
                raise AuthorizationError(f"authorization requires {expected_role} role")
        if team_id is not None and self.connection.execute(
            "SELECT 1 FROM teams WHERE round_id = ? AND team_id = ?", (round_id, team_id)
        ).fetchone() is None:
            raise AuthorizationError("team does not exist in round")
        if record.role == "student" and record.team_id != team_id:
            raise AuthorizationError("student session cannot access another team")
        return record

    def _active_record_by_id(self, session_id: str) -> SessionRecord:
        if not isinstance(session_id, str) or not session_id:
            raise AuthenticationError("invalid session")
        row = self.connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise AuthenticationError("invalid session")
        return self._active_record(row)

    def _active_record(self, row) -> SessionRecord:
        record = self._safe_record(row)
        now = self._now()
        if record.revoked_at is not None:
            raise AuthenticationError("session is revoked")
        if record.expires_at is not None and now >= record.expires_at:
            raise AuthenticationError("session is expired")
        return record

    def _safe_record(self, row, *, revoked_at=None) -> SessionRecord:
        try:
            return self._record(row, revoked_at=revoked_at)
        except (AuthenticationError, TypeError, ValueError, KeyError) as error:
            raise AuthenticationError("malformed persisted session") from error

    @staticmethod
    def _record(row, *, revoked_at=None) -> SessionRecord:
        session_id = SessionManager._persisted_text(row["session_id"], "session_id")
        actor_id = SessionManager._persisted_text(row["actor_id"], "actor_id")
        round_id = SessionManager._persisted_text(row["round_id"], "round_id")
        role = row["role"]
        team_id = row["team_id"]
        if role == "student" and not SessionManager._is_nonempty_text(team_id):
            raise ValueError("student session team is malformed")
        if role == "instructor" and team_id is not None:
            raise ValueError("instructor session team is malformed")
        if role not in {"student", "instructor"}:
            raise ValueError("session role is malformed")
        return SessionRecord(session_id, actor_id, round_id, team_id, role,
                             _parse_stamp(row["created_at"], "created_at"),
                             _parse_stamp(row["expires_at"], "expires_at"),
                             revoked_at if revoked_at is not None else _parse_stamp(row["revoked_at"], "revoked_at"))

    @staticmethod
    def _is_nonempty_text(value) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _persisted_text(value, name: str) -> str:
        if not SessionManager._is_nonempty_text(value):
            raise ValueError(f"{name} is malformed")
        return value
