"""SQLite persistence for the Phase 3 classroom round lifecycle.

The store deliberately exposes domain records at its boundaries and keeps JSON
serialization and SQL details private. It assumes callers have already
performed authentication and authorization; team IDs are therefore explicit
arguments and are never inferred from a session. Team memberships are
immutable. Direct round deletion is intentionally restricted by foreign keys;
this store provides no implicit whole-round cleanup operation, so deleting a
round cannot silently delete memberships or their dependent records.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
from numbers import Real
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Iterator
import uuid

from .round_models import (
    EvaluationRunRecord,
    RoundPolicy,
    RoundRecord,
    RoundState,
    SubmissionRecord,
    TeamResultRecord,
    validate_round_policy,
)


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS rounds (
    round_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    scenario_version TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    deadline_seconds REAL,
    deadline_at TEXT,
    visibility TEXT NOT NULL,
    tie_break_mode TEXT NOT NULL,
    seed INTEGER,
    display_timezone TEXT NOT NULL,
    created_at TEXT NOT NULL,
    opened_at TEXT,
    locked_at TEXT,
    published_at TEXT,
    CHECK (state IN ('draft', 'open', 'locked', 'evaluated', 'published', 'failed', 'retracted')),
    CHECK (length(trim(scenario_id)) > 0),
    CHECK (length(trim(scenario_version)) > 0),
    CHECK (length(trim(evaluator_version)) > 0),
    CHECK (length(trim(policy_version)) > 0),
    CHECK (deadline_seconds IS NULL OR deadline_seconds >= 0),
    CHECK (visibility IN ('private', 'aggregate', 'public')),
    CHECK (tie_break_mode IN ('default', 'authoritative_total', 'seeded_random', 'randomized')),
    CHECK (seed IS NULL OR typeof(seed) = 'integer'),
    CHECK (tie_break_mode NOT IN ('seeded_random', 'randomized') OR seed IS NOT NULL)
);
CREATE TRIGGER IF NOT EXISTS rounds_immutable_delete
BEFORE DELETE ON rounds BEGIN SELECT RAISE(ABORT, 'round deletion is not supported'); END;
CREATE TABLE IF NOT EXISTS teams (
    round_id TEXT NOT NULL REFERENCES rounds(round_id),
    team_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    PRIMARY KEY (round_id, team_id),
    UNIQUE (round_id, team_id)
);
CREATE TRIGGER IF NOT EXISTS teams_immutable_update
BEFORE UPDATE ON teams BEGIN SELECT RAISE(ABORT, 'team memberships are immutable'); END;
CREATE TRIGGER IF NOT EXISTS teams_immutable_delete
BEFORE DELETE ON teams BEGIN SELECT RAISE(ABORT, 'team memberships are immutable'); END;
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    round_id TEXT NOT NULL REFERENCES rounds(round_id),
    team_id TEXT,
    role TEXT NOT NULL,
    expires_at TEXT,
    FOREIGN KEY (round_id, team_id) REFERENCES teams(round_id, team_id)
);
CREATE TABLE IF NOT EXISTS drafts (
    round_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (typeof(revision) = 'integer' AND revision > 0),
    PRIMARY KEY (round_id, team_id),
    FOREIGN KEY (round_id, team_id) REFERENCES teams(round_id, team_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE (round_id, idempotency_key),
    FOREIGN KEY (round_id, team_id) REFERENCES teams(round_id, team_id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS submissions_immutable_update
BEFORE UPDATE ON submissions BEGIN SELECT RAISE(ABORT, 'submissions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS submissions_immutable_delete
BEFORE DELETE ON submissions BEGIN SELECT RAISE(ABORT, 'submissions are immutable'); END;
CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_run_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES rounds(round_id),
    batch_input_hash TEXT NOT NULL,
    seed INTEGER,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error TEXT,
    UNIQUE (evaluation_run_id, round_id)
);
CREATE TRIGGER IF NOT EXISTS evaluation_runs_immutable_update
BEFORE UPDATE ON evaluation_runs BEGIN SELECT RAISE(ABORT, 'evaluation runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS evaluation_runs_immutable_delete
BEFORE DELETE ON evaluation_runs BEGIN SELECT RAISE(ABORT, 'evaluation runs are immutable'); END;
CREATE TABLE IF NOT EXISTS team_results (
    evaluation_run_id TEXT NOT NULL,
    round_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    authoritative_total REAL NOT NULL,
    rank INTEGER,
    tie_group TEXT,
    visibility TEXT NOT NULL,
    diagnostics_json TEXT,
    PRIMARY KEY (evaluation_run_id, team_id),
    FOREIGN KEY (evaluation_run_id, round_id) REFERENCES evaluation_runs(evaluation_run_id, round_id),
    FOREIGN KEY (round_id, team_id) REFERENCES teams(round_id, team_id)
);
CREATE TRIGGER IF NOT EXISTS team_results_immutable_update
BEFORE UPDATE ON team_results BEGIN SELECT RAISE(ABORT, 'team results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS team_results_immutable_delete
BEFORE DELETE ON team_results BEGIN SELECT RAISE(ABORT, 'team results are immutable'); END;
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id TEXT NOT NULL REFERENCES rounds(round_id),
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_id TEXT,
    occurred_at TEXT NOT NULL,
    request_id TEXT,
    metadata_json TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamps must be timezone-aware UTC datetimes")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_stamp(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _unjson(value: str | None) -> Any:
    return None if value is None else json.loads(value)


class RoundStore:
    """Transactional SQLite repository for rounds and their audit artifacts.

    Round deletion is intentionally unsupported. A database trigger rejects
    every direct delete, and foreign keys also prevent dependent-record cleanup
    from becoming an implicit cascade. A future authorized purge workflow must
    be explicit and separately audited.
    """

    def __init__(self, database: str | Path | sqlite3.Connection = ":memory:", *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _now
        if isinstance(database, sqlite3.Connection):
            self.connection = database
            self.connection.isolation_level = None
        else:
            self.connection = sqlite3.connect(str(database), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(_SCHEMA)

    def _clock_now(self) -> datetime:
        value = self._clock()
        _stamp(value)
        return value.astimezone(timezone.utc)

    def _timestamp(self, value: datetime | None = None) -> str:
        return _stamp(self._clock_now() if value is None else value)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def create_round(self, record: RoundRecord, teams: Iterable[str] = ()) -> RoundRecord:
        """Create a round and optional team memberships atomically."""
        policy = record.policy
        if policy is None:
            raise ValueError("round policy is required")
        validate_round_policy(policy)
        created = record.created_at or self._clock_now()
        with self._write() as db:
            db.execute(
                """INSERT INTO rounds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.round_id, record.state.value, policy.scenario_id, policy.scenario_version,
                    policy.evaluator_version, policy.policy_version, policy.deadline_seconds,
                    _stamp(policy.deadline_at) if policy.deadline_at else None, policy.visibility,
                    policy.tie_break_mode, policy.seed, policy.display_timezone, _stamp(created),
                    _stamp(record.opened_at) if record.opened_at else None,
                    _stamp(record.locked_at) if record.locked_at else None,
                    _stamp(record.published_at) if record.published_at else None,
                ),
            )
            for team in teams:
                team_id, display_name = (team, team) if isinstance(team, str) else team
                db.execute("INSERT INTO teams VALUES (?, ?, ?)", (record.round_id, team_id, display_name))
        return self.get_round(record.round_id)  # type: ignore[return-value]

    def clone_round(
        self,
        source_round_id: str,
        record: RoundRecord,
        teams: Iterable[str | tuple[str, str]] | None = None,
    ) -> RoundRecord:
        """Create a draft round from an existing round's policy and teams.

        Only configuration is copied. Mutable drafts, submissions, evaluation
        artifacts, and audit history remain exclusive to the source round.
        """
        source = self.get_round(source_round_id)
        if source is None:
            raise KeyError(source_round_id)
        policy = record.policy or source.policy
        if policy is None:
            raise ValueError("round policy is required")
        if teams is None:
            rows = self.connection.execute(
                "SELECT team_id, display_name FROM teams WHERE round_id = ? ORDER BY team_id",
                (source_round_id,),
            ).fetchall()
            teams = tuple((row["team_id"], row["display_name"]) for row in rows)
        return self.create_round(
            RoundRecord(record.round_id, state=RoundState.DRAFT, policy=policy),
            teams=teams,
        )

    def get_round(self, round_id: str) -> RoundRecord | None:
        row = self.connection.execute("SELECT * FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
        if row is None:
            return None
        policy = RoundPolicy(
            row["scenario_id"], row["scenario_version"], row["evaluator_version"], row["policy_version"],
            row["deadline_seconds"], _parse_stamp(row["deadline_at"]), row["visibility"],
            row["tie_break_mode"], row["seed"], row["display_timezone"],
        )
        return RoundRecord(row["round_id"], RoundState(row["state"]), policy, _parse_stamp(row["created_at"]),
                           _parse_stamp(row["opened_at"]), _parse_stamp(row["locked_at"]), _parse_stamp(row["published_at"]))

    def list_teams(self, round_id: str) -> tuple[str, ...]:
        rows = self.connection.execute("SELECT team_id FROM teams WHERE round_id = ? ORDER BY team_id", (round_id,)).fetchall()
        return tuple(row["team_id"] for row in rows)

    def transition_round(self, round_id: str, target: RoundState, *, actor_id: str, reason: str | None = None) -> RoundRecord:
        """Validate, persist, and audit one lifecycle transition."""
        with self._write() as db:
            current = self.get_round(round_id)
            if current is None:
                raise KeyError(round_id)
            transitioned = current.transition(target)
            now = self._timestamp()
            column = {RoundState.OPEN: "opened_at", RoundState.LOCKED: "locked_at", RoundState.PUBLISHED: "published_at"}.get(target)
            if column:
                db.execute(f"UPDATE rounds SET state = ?, {column} = ? WHERE round_id = ?", (target.value, now, round_id))
            else:
                db.execute("UPDATE rounds SET state = ? WHERE round_id = ?", (target.value, round_id))
            self._record_audit(db, round_id, actor_id, "round.transition", round_id,
                               {"from": current.state.value, "to": target.value, "reason": reason})
        return self.get_round(round_id)  # type: ignore[return-value]

    def _assert_team_writable(self, round_id: str, team_id: str) -> RoundRecord:
        round_record = self.get_round(round_id)
        if round_record is None:
            raise KeyError(round_id)
        if round_record.state is not RoundState.OPEN:
            raise ValueError("team writes require an open round")
        if self.connection.execute("SELECT 1 FROM teams WHERE round_id = ? AND team_id = ?", (round_id, team_id)).fetchone() is None:
            raise KeyError((round_id, team_id))
        return round_record

    @staticmethod
    def _round_deadline(round_record: RoundRecord) -> datetime | None:
        policy = round_record.policy
        assert policy is not None
        deadlines = []
        if policy.deadline_at is not None:
            deadlines.append(policy.deadline_at.astimezone(timezone.utc))
        if policy.deadline_seconds is not None and round_record.created_at is not None:
            deadlines.append(round_record.created_at + timedelta(seconds=policy.deadline_seconds))
        return min(deadlines) if deadlines else None

    def upsert_draft(self, round_id: str, team_id: str, payload: Any, *, revision: int | None = None) -> dict[str, Any]:
        """Replace the latest draft; only authenticated service layers should call this."""
        with self._write() as db:
            round_record = self._assert_team_writable(round_id, team_id)
            deadline = self._round_deadline(round_record)
            if deadline is not None and self._clock_now() >= deadline:
                raise ValueError("round deadline has passed")
            old = db.execute("SELECT revision FROM drafts WHERE round_id = ? AND team_id = ?", (round_id, team_id)).fetchone()
            if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0):
                raise ValueError("revision must be a positive integer")
            if old is not None and revision is not None and revision <= old["revision"]:
                raise ValueError("revision must advance the existing revision")
            next_revision = revision if revision is not None else (old["revision"] + 1 if old else 1)
            db.execute("INSERT INTO drafts VALUES (?, ?, ?, ?, ?) ON CONFLICT(round_id, team_id) DO UPDATE SET payload_json=excluded.payload_json, revision=excluded.revision, updated_at=excluded.updated_at",
                       (round_id, team_id, _json(payload), next_revision, self._timestamp()))
        return self.get_draft(round_id, team_id)  # type: ignore[return-value]

    def get_draft(self, round_id: str, team_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT payload_json, revision, updated_at FROM drafts WHERE round_id = ? AND team_id = ?", (round_id, team_id)).fetchone()
        if row is None:
            return None
        return {"payload": _unjson(row["payload_json"]), "revision": row["revision"], "updated_at": _parse_stamp(row["updated_at"])}

    def insert_submission(self, round_id: str, team_id: str, payload: Any, semantic_hash: str, idempotency_key: str,
                          *, submission_id: str | None = None, submitted_at: datetime | None = None) -> SubmissionRecord:
        """Append an immutable submission, replaying the original row for duplicate keys."""
        with self._write() as db:
            existing = db.execute("SELECT * FROM submissions WHERE round_id = ? AND idempotency_key = ?", (round_id, idempotency_key)).fetchone()
            if existing is not None:
                if existing["team_id"] != team_id or existing["semantic_hash"] != semantic_hash or existing["payload_json"] != _json(payload):
                    raise ValueError("idempotency key cannot be reused for a different request")
                return self._submission(existing)
            round_record = self._assert_team_writable(round_id, team_id)
            deadline = self._round_deadline(round_record)
            if deadline is not None and self._clock_now() >= deadline:
                raise ValueError("round deadline has passed")
            db.execute("INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (submission_id or str(uuid.uuid4()), round_id, team_id, semantic_hash, idempotency_key, _json(payload), self._timestamp(submitted_at), "accepted"))
            row = db.execute("SELECT * FROM submissions WHERE rowid = last_insert_rowid()").fetchone()
        return self._submission(row)

    def _submission(self, row: sqlite3.Row) -> SubmissionRecord:
        return SubmissionRecord(row["submission_id"], row["round_id"], row["team_id"], row["semantic_hash"], row["idempotency_key"],
                                _unjson(row["payload_json"]), _parse_stamp(row["submitted_at"]), row["status"])

    def get_team_submission(self, round_id: str, team_id: str) -> SubmissionRecord | None:
        row = self.connection.execute("SELECT * FROM submissions WHERE round_id = ? AND team_id = ? ORDER BY submitted_at DESC, submission_id DESC LIMIT 1", (round_id, team_id)).fetchone()
        return None if row is None else self._submission(row)

    def lock_submission_snapshot(self, round_id: str, *, actor_id: str) -> tuple[SubmissionRecord, ...]:
        """Close an open round and return its latest submission for each team in stable order."""
        with self._write() as db:
            current = self.get_round(round_id)
            if current is None:
                raise KeyError(round_id)
            transitioned = current.transition(RoundState.LOCKED)
            reason = "submission snapshot locked"
            db.execute("UPDATE rounds SET state = ?, locked_at = ? WHERE round_id = ?", (transitioned.state.value, self._timestamp(), round_id))
            self._record_audit(
                db,
                round_id,
                actor_id,
                "round.lock",
                round_id,
                {
                    "from": current.state.value,
                    "to": transitioned.state.value,
                    "previous_state": current.state.value,
                    "new_state": transitioned.state.value,
                    "reason": reason,
                },
            )
            rows = db.execute("""
                SELECT * FROM (
                    SELECT s.*, ROW_NUMBER() OVER (
                        PARTITION BY team_id ORDER BY submitted_at DESC, submission_id DESC
                    ) AS row_number
                    FROM submissions AS s WHERE round_id = ?
                ) WHERE row_number = 1 ORDER BY team_id
            """, (round_id,)).fetchall()
        return tuple(self._submission(row) for row in rows)

    def create_evaluation_run(self, record: EvaluationRunRecord) -> EvaluationRunRecord:
        with self._write() as db:
            round_record = self.get_round(record.round_id)
            if round_record is None:
                raise KeyError(record.round_id)
            if round_record.state not in (RoundState.LOCKED, RoundState.EVALUATED) or round_record.locked_at is None:
                raise ValueError("evaluation requires a locked round")
            started_at = record.started_at or self._clock_now()
            completed_at = record.completed_at
            if completed_at is None and record.status == "complete":
                completed_at = self._clock_now()
            db.execute("INSERT INTO evaluation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (record.evaluation_run_id, record.round_id, record.batch_input_hash, record.seed, record.status,
                        self._timestamp(started_at), self._timestamp(completed_at) if completed_at else None, record.error))
        return self.get_evaluation_run(record.evaluation_run_id)  # type: ignore[return-value]

    def get_evaluation_run(self, run_id: str) -> EvaluationRunRecord | None:
        row = self.connection.execute("SELECT * FROM evaluation_runs WHERE evaluation_run_id = ?", (run_id,)).fetchone()
        return None if row is None else EvaluationRunRecord(row["evaluation_run_id"], row["round_id"], row["batch_input_hash"], row["seed"], row["status"], _parse_stamp(row["started_at"]), _parse_stamp(row["completed_at"]), row["error"])

    def store_results(self, evaluation_run_id: str, results: Iterable[TeamResultRecord]) -> None:
        """Persist a complete result set atomically; duplicate result rows are rejected."""
        result_rows = tuple(results)
        for result in result_rows:
            if (isinstance(result.authoritative_total, bool)
                    or not isinstance(result.authoritative_total, Real)
                    or not math.isfinite(result.authoritative_total)):
                raise ValueError("authoritative_total must be finite")
            if result.rank is not None and (isinstance(result.rank, bool) or not isinstance(result.rank, int) or result.rank <= 0):
                raise ValueError("rank must be a positive integer")
            if result.visibility not in {"private", "aggregate", "public"}:
                raise ValueError("visibility is invalid")
            if result.diagnostics is not None and not isinstance(result.diagnostics, dict):
                raise ValueError("diagnostics must be a JSON object")
            try:
                if result.diagnostics is not None:
                    _json(result.diagnostics)
            except (TypeError, ValueError) as error:
                raise ValueError("diagnostics must be JSON-serializable") from error
        with self._write() as db:
            run = self.get_evaluation_run(evaluation_run_id)
            if run is None:
                raise KeyError(evaluation_run_id)
            round_record = self.get_round(run.round_id)
            if round_record is None or round_record.state not in (RoundState.LOCKED, RoundState.EVALUATED):
                raise ValueError("results require a locked round")
            expected_teams = set(self.list_teams(run.round_id))
            actual_teams = [result.team_id for result in result_rows]
            if not actual_teams:
                raise ValueError("result set cannot be empty")
            if len(actual_teams) != len(set(actual_teams)):
                raise ValueError("result set contains duplicate teams")
            if set(actual_teams) != expected_teams:
                raise ValueError("result set must have exact team coverage")
            for result in result_rows:
                db.execute("INSERT INTO team_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (evaluation_run_id, run.round_id, result.team_id, result.authoritative_total, result.rank, result.tie_group,
                            result.visibility, _json(result.diagnostics) if result.diagnostics is not None else None))

    def record_audit_event(self, round_id: str, *, actor_id: str, action: str, target_id: str | None = None,
                           metadata: dict[str, Any] | None = None, request_id: str | None = None) -> int:
        with self._write() as db:
            return self._record_audit(db, round_id, actor_id, action, target_id, metadata or {}, request_id)

    def _record_audit(self, db: sqlite3.Connection, round_id: str, actor_id: str, action: str, target_id: str | None,
                      metadata: dict[str, Any], request_id: str | None = None) -> int:
        cursor = db.execute("INSERT INTO audit_events(round_id, actor_id, action, target_id, occurred_at, request_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (round_id, actor_id, action, target_id, self._timestamp(), request_id, _json(metadata)))
        return int(cursor.lastrowid)

    def export_round_bundle(self, round_id: str) -> dict[str, Any]:
        """Return a deterministic, self-contained JSON-compatible audit bundle."""
        round_record = self.get_round(round_id)
        if round_record is None:
            raise KeyError(round_id)
        policy = round_record.policy
        assert policy is not None
        bundle: dict[str, Any] = {"round": {"round_id": round_record.round_id, "state": round_record.state.value,
            "policy": {"scenario_id": policy.scenario_id, "scenario_version": policy.scenario_version, "evaluator_version": policy.evaluator_version, "policy_version": policy.policy_version, "deadline_seconds": policy.deadline_seconds, "deadline_at": _stamp(policy.deadline_at) if policy.deadline_at else None, "visibility": policy.visibility, "tie_break_mode": policy.tie_break_mode, "seed": policy.seed, "display_timezone": policy.display_timezone},
            "created_at": _stamp(round_record.created_at), "opened_at": _stamp(round_record.opened_at) if round_record.opened_at else None, "locked_at": _stamp(round_record.locked_at) if round_record.locked_at else None, "published_at": _stamp(round_record.published_at) if round_record.published_at else None},
            "teams": [{"team_id": row["team_id"], "display_name": row["display_name"]} for row in self.connection.execute("SELECT team_id, display_name FROM teams WHERE round_id = ? ORDER BY team_id", (round_id,))],
            "drafts": [{"team_id": row["team_id"], "payload": _unjson(row["payload_json"]), "revision": row["revision"], "updated_at": row["updated_at"]} for row in self.connection.execute("SELECT team_id, payload_json, revision, updated_at FROM drafts WHERE round_id = ? ORDER BY team_id", (round_id,))],
            "submissions": [{"submission_id": row["submission_id"], "team_id": row["team_id"], "semantic_hash": row["semantic_hash"], "idempotency_key": row["idempotency_key"], "payload": _unjson(row["payload_json"]), "submitted_at": row["submitted_at"], "status": row["status"]} for row in self.connection.execute("SELECT * FROM submissions WHERE round_id = ? ORDER BY team_id, submitted_at, submission_id", (round_id,))],
            "evaluation_runs": [dict(row) for row in self.connection.execute("SELECT * FROM evaluation_runs WHERE round_id = ? ORDER BY evaluation_run_id", (round_id,))],
            "team_results": [{**dict(row), "diagnostics": _unjson(row["diagnostics_json"])} for row in self.connection.execute("SELECT tr.* FROM team_results tr JOIN evaluation_runs er ON er.evaluation_run_id = tr.evaluation_run_id WHERE er.round_id = ? ORDER BY tr.evaluation_run_id, tr.team_id", (round_id,))],
            "audit_events": [{**dict(row), "metadata": _unjson(row["metadata_json"])} for row in self.connection.execute("SELECT * FROM audit_events WHERE round_id = ? ORDER BY event_id", (round_id,))]}
        for row in bundle["evaluation_runs"]:
            row.pop("round_id", None)
        return bundle
