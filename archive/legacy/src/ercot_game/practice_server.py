"""Local HTTP practice API for the deterministic ERCOT evaluator."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from collections.abc import Iterator, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import cast
from urllib.parse import parse_qs, urlsplit
import uuid
from datetime import datetime, timezone
import hashlib
import hmac
import re
import sqlite3

from .cli import _load_scenario
from .auth import AuthenticationError, AuthorizationError, SessionManager
from .evaluator import (
    EvaluationInputError,
    evaluate_week,
    resolve_evaluation_config,
)
from .io import plan_from_dict
from .models import EvaluationConfig, Scenario
from .practice_serialization import evaluation_response, error_response, scenario_response
from .multiteam import build_audit_bundle, build_batch_input, evaluate_locked_round, replay_audit_bundle
from .evaluation_jobs import create_local_job
from .remote_jobs import RemoteJobDispatcher, RemoteJobStatus
from .round_models import EvaluationRunRecord, RoundDomainError, RoundPolicy, RoundRecord, RoundState, TeamResultRecord, validate_round_policy
from .round_store import RoundStore


MAX_REQUEST_BODY_BYTES = 1024 * 1024
_JSON_PARSE_ERROR = object()
_STATIC_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/results": ("results.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/results.js": ("results.js", "application/javascript; charset=utf-8"),
    "/texas-counties.json": ("texas-counties.json", "application/json; charset=utf-8"),
    "/texas-boundary.json": ("texas-boundary.json", "application/json; charset=utf-8"),
    "/data/ercot-public-network.json": ("data/ercot-public-network.json", "application/json; charset=utf-8"),
    "/data/results/round_metadata.json": ("data/results/round_metadata.json", "application/json; charset=utf-8"),
    "/data/results/public_network.json": ("data/results/public_network.json", "application/json; charset=utf-8"),
    "/data/results/team_report.json": ("data/results/team_report.json", "application/json; charset=utf-8"),
    "/data/results/aggregate_grid_summary.json": ("data/results/aggregate_grid_summary.json", "application/json; charset=utf-8"),
    "/fonts/IBMPlexSans-Regular.woff2": ("fonts/IBMPlexSans-Regular.woff2", "font/woff2"),
    "/fonts/IBMPlexSans-SemiBold.woff2": ("fonts/IBMPlexSans-SemiBold.woff2", "font/woff2"),
    "/fonts/IBMPlexMono-Regular.woff2": ("fonts/IBMPlexMono-Regular.woff2", "font/woff2"),
    "/fonts/SourceSerif4-Regular.ttf": ("fonts/SourceSerif4-Regular.ttf", "font/ttf"),
    "/fonts/SourceSerif4-SemiBold.ttf": ("fonts/SourceSerif4-SemiBold.ttf", "font/ttf"),
}


def _selected_period_from_query(query: str) -> int:
    """Parse the bounded /api/scenario query contract."""
    try:
        parsed = parse_qs(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=1,
        )
    except ValueError as error:
        raise ValueError("scenario query must contain one period=integer parameter") from error

    unknown_keys = sorted(set(parsed) - {"period"})
    if unknown_keys:
        raise ValueError(f"unknown scenario query parameter: {unknown_keys[0]}")
    if not parsed:
        return 0
    values = parsed["period"]
    if len(values) != 1:
        raise ValueError("scenario query must contain one period=integer parameter")
    try:
        return int(values[0])
    except (TypeError, ValueError) as error:
        raise ValueError("scenario period must be an integer") from error


def _default_scenario_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "data/teaching/ercot_connection_scenario_v2.json"
    if candidate.exists():
        return candidate
    return Path.cwd() / "data/teaching/ercot_connection_scenario_v2.json"


def _web_root() -> Path:
    return Path(__file__).resolve().parents[2] / "web"


class PracticeHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying one immutable scenario and resolved config.

    Phase 3 session issuance is a trusted local bootstrap operation and
    requires the configured ``X-Bootstrap-Credential``. Repeating a successful
    evaluation returns its stored run and does not create a second artifact.
    """

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        scenario: Scenario,
        config: EvaluationConfig,
        round_store: RoundStore | None = None,
        bootstrap_credential: str | None = None,
        evaluation_dispatcher: RemoteJobDispatcher | None = None,
    ) -> None:
        super().__init__(server_address, PracticeRequestHandler)
        self.scenario = scenario
        self.config = config
        self.bootstrap_credential = bootstrap_credential
        self.evaluation_dispatcher = evaluation_dispatcher
        self.phase3_lock = threading.RLock()
        if round_store is None:
            self.round_store = RoundStore(sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None))
        else:
            # HTTP handlers run on worker threads. Reopen file-backed stores so
            # sqlite's connection thread affinity cannot turn valid requests
            # into internal errors; the database remains the domain authority.
            database = round_store.connection.execute(
                "PRAGMA database_list"
            ).fetchone()[2]
            if database in {"", ":memory:"}:
                # Keep the injected repository object and its preloaded data.
                # Copy only its connection into a thread-safe in-memory
                # connection because sqlite connection affinity is immutable.
                connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
                round_store.connection.backup(connection)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                round_store.connection = connection
                self.round_store = round_store
            else:
                self.round_store = RoundStore(
                    sqlite3.connect(database, check_same_thread=False, isolation_level=None),
                    clock=round_store._clock,
                )
        self.session_manager = SessionManager(self.round_store)
        self._practice_ready_event: threading.Event | None = None

    def service_actions(self) -> None:
        if self._practice_ready_event is not None:
            self._practice_ready_event.set()
        super().service_actions()


class PracticeRequestHandler(BaseHTTPRequestHandler):
    server: PracticeHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        """Keep the practice server quiet unless an embedding app logs requests."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Route unknown verbs on protected Phase 3 shapes through auth first."""
        if code == HTTPStatus.NOT_IMPLEMENTED:
            if self._phase3_method_guard(urlsplit(self.path).path):
                return
        super().send_error(code, message, explain)

    def _send_json(self, status: HTTPStatus, payload: Mapping[str, object]) -> None:
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: str) -> bool:
        asset = _STATIC_ASSETS.get(path)
        if asset is None:
            return False

        filename, content_type = asset
        web_root = _web_root().resolve()
        asset_path = (web_root / filename).resolve()
        try:
            asset_path.relative_to(web_root)
        except ValueError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return True

        try:
            body = asset_path.read_bytes()
        except OSError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return True

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        include_version: bool = False,
        request_id: str | None = None,
    ) -> None:
        evaluator_version = self.server.scenario.evaluator_version if include_version else None
        self._send_json(
            status,
            error_response(
                code,
                message,
                evaluator_version=evaluator_version,
                request_id=request_id,
            ),
        )

    def _phase3_error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        allowed_methods: tuple[str, ...] = (),
    ) -> None:
        payload = error_response(code, message, request_id=uuid.uuid4().hex)
        if allowed_methods:
            payload["error"]["allowed_methods"] = list(allowed_methods)
        self._send_json(status, payload)

    def _phase3_bearer(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or not header[7:].strip():
            raise AuthenticationError("missing bearer token")
        with self.server.phase3_lock:
            return self.server.session_manager.authenticate(header[7:].strip())

    def _instructor_session(self):
        session = self._phase3_bearer()
        if session.role != "instructor":
            raise AuthorizationError("authorization requires instructor role")
        return session

    def _phase3_method_guard(self, path: str) -> bool:
        """Handle protected route shapes before method-specific fallbacks."""
        patterns = (
            (r"/api/rounds/([^/]+)/submit", ("POST",), "bearer"),
            (r"/api/instructor/rounds/([^/]+)/transition", ("POST",), "bearer"),
            (r"/api/instructor/rounds/([^/]+)/evaluate", ("POST",), "bearer"),
            (r"/api/instructor/rounds/([^/]+)/evaluate/status", ("GET",), "bearer"),
            (r"/api/instructor/rounds/([^/]+)/evaluate/cancel", ("POST",), "bearer"),
            (r"/api/instructor/rounds/([^/]+)/audit", ("GET",), "bearer"),
            (r"/api/instructor/rounds/([^/]+)/audit/replay", ("POST",), "bearer"),
            (r"/api/instructor/rounds", ("POST",), "bearer"),
            (r"/api/rounds/([^/]+)", ("GET",), "bearer"),
            (r"/api/rounds/([^/]+)/draft", ("GET", "PUT"), "bearer"),
            (r"/api/rounds/([^/]+)/(?:submission|leaderboard)", ("GET",), "bearer"),
            (r"/api/session/revoke", ("POST",), "bearer"),
            (r"/api/session", ("POST",), "bootstrap"),
        )
        for pattern, allowed, auth_kind in patterns:
            if re.fullmatch(pattern, path) is None:
                continue
            if self.command in allowed:
                return False
            try:
                if auth_kind == "bearer":
                    self._phase3_bearer()
                else:
                    credential = self.headers.get("X-Bootstrap-Credential", "")
                    configured = self.server.bootstrap_credential
                    if configured is None or not hmac.compare_digest(credential, configured):
                        raise AuthenticationError("trusted bootstrap credential required")
            except AuthenticationError as error:
                self._phase3_auth_error(error)
                return True
            self._phase3_error(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "method_not_allowed",
                "method not allowed",
                allowed_methods=allowed,
            )
            return True
        return False

    def _phase3_body(self) -> object:
        return self._read_json_body(phase3=True)

    def _session(self, round_id: str, *, team_id: str | None = None, instructor: bool = False):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or not header[7:].strip():
            raise AuthenticationError("missing bearer token")
        token = header[7:].strip()
        with self.server.phase3_lock:
            if instructor:
                return self.server.session_manager.authorize(
                    self.server.session_manager.authenticate(token),
                    round_id=round_id, require_instructor=True,
                )
            session = self.server.session_manager.authenticate(token)
            return self.server.session_manager.authorize(
                session, round_id=round_id, team_id=team_id if team_id is not None else session.team_id
            )

    @staticmethod
    def _round_payload(round_record, *, team_id=None):
        policy = round_record.policy
        assert policy is not None
        return {
            "round_id": round_record.round_id,
            "state": round_record.state.value,
            "team_id": team_id,
            "policy": {
                "scenario_id": policy.scenario_id,
                "scenario_version": policy.scenario_version,
                "evaluator_version": policy.evaluator_version,
                "policy_version": policy.policy_version,
                "deadline_seconds": policy.deadline_seconds,
                "deadline_at": policy.deadline_at.isoformat() if policy.deadline_at else None,
                "visibility": policy.visibility,
                "tie_break_mode": policy.tie_break_mode,
                "seed": policy.seed,
            },
        }

    def _phase3_round(self, round_id: str):
        record = self.server.round_store.get_round(round_id)
        if record is None:
            raise KeyError(round_id)
        return record

    @staticmethod
    def _round_request(payload: Mapping[str, object]) -> tuple[str, RoundPolicy | Mapping[str, object] | None, list[tuple[str, str]] | None, str | None]:
        allowed = {"round_id", "policy", "teams", "clone_from"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown field: {unknown[0]}")
        round_id = payload.get("round_id")
        if not isinstance(round_id, str) or not round_id.strip():
            raise ValueError("round_id is required")
        clone_from = payload.get("clone_from")
        if clone_from is not None and (not isinstance(clone_from, str) or not clone_from.strip()):
            raise ValueError("clone_from must be a non-empty string")
        policy_payload = payload.get("policy")
        policy = None
        if policy_payload is not None:
            if not isinstance(policy_payload, Mapping):
                raise ValueError("policy must be an object")
            policy_fields = {
                "scenario_id", "scenario_version", "evaluator_version", "policy_version",
                "deadline_seconds", "deadline_at", "visibility", "tie_break_mode", "seed", "display_timezone",
            }
            unknown_policy = sorted(set(policy_payload) - policy_fields)
            if unknown_policy:
                raise ValueError(f"unknown policy field: {unknown_policy[0]}")
            required = {"scenario_id", "scenario_version", "evaluator_version"}
            if clone_from is None and not required.issubset(policy_payload):
                raise ValueError("policy requires scenario_id, scenario_version, and evaluator_version")
            values = dict(policy_payload)
            if clone_from is None:
                policy = RoundPolicy(
                    scenario_id=values["scenario_id"], scenario_version=values["scenario_version"],
                    evaluator_version=values["evaluator_version"], policy_version=values.get("policy_version", "1"),
                    deadline_seconds=values.get("deadline_seconds"), deadline_at=PracticeRequestHandler._parse_deadline(values.get("deadline_at")),
                    visibility=values.get("visibility", "private"), tie_break_mode=values.get("tie_break_mode", "default"),
                    seed=values.get("seed"), display_timezone=values.get("display_timezone", "UTC"),
                )
            else:
                policy = PracticeRequestHandler._partial_policy(values)
        teams_payload = payload.get("teams")
        teams = None
        if teams_payload is not None:
            if not isinstance(teams_payload, list):
                raise ValueError("teams must be an array")
            parsed: list[tuple[str, str]] = []
            seen: set[str] = set()
            for item in teams_payload:
                if isinstance(item, str):
                    team_id, display_name = item, item
                elif isinstance(item, Mapping):
                    if set(item) - {"team_id", "display_name"}:
                        raise ValueError("unknown team field")
                    team_id = item.get("team_id")
                    display_name = item.get("display_name", team_id)
                else:
                    raise ValueError("team must be a string or object")
                if not isinstance(team_id, str) or not team_id.strip() or not isinstance(display_name, str) or not display_name.strip():
                    raise ValueError("team_id and display_name are required")
                if team_id in seen:
                    raise ValueError("team IDs must be unique")
                seen.add(team_id)
                parsed.append((team_id, display_name))
            teams = parsed
        return round_id, policy, teams, clone_from

    @staticmethod
    def _parse_deadline(value: object) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("deadline_at must be an ISO-8601 UTC timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("deadline_at must be an ISO-8601 UTC timestamp") from error
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("deadline_at must be an ISO-8601 UTC timestamp")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _partial_policy(values: Mapping[str, object]) -> Mapping[str, object]:
        # A clone override is merged with the source policy after loading it.
        values = dict(values)
        if "deadline_at" in values:
            values["deadline_at"] = PracticeRequestHandler._parse_deadline(values["deadline_at"])
        return values

    def _phase3_auth_error(self, error: Exception) -> None:
        if isinstance(error, AuthenticationError):
            self._phase3_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "authentication required")
        else:
            self._phase3_error(HTTPStatus.FORBIDDEN, "forbidden", "access denied")

    def _phase3_get(self, path: str) -> bool:
        with self.server.phase3_lock:
            return self._phase3_get_unlocked(path)

    def _phase3_get_unlocked(self, path: str) -> bool:
        match = re.fullmatch(r"/api/rounds/([^/]+)(?:/(draft|submission|leaderboard))?", path)
        if match:
            round_id, resource = match.groups()
            try:
                session = self._session(round_id)
                record = self._phase3_round(round_id)
                requested_team = parse_qs(urlsplit(self.path).query).get("team_id", [None])[0]
                if requested_team is not None and requested_team != session.team_id:
                    raise AuthorizationError("student session cannot access another team")
                if resource is None:
                    self._send_json(HTTPStatus.OK, self._round_payload(record, team_id=session.team_id))
                elif resource == "draft":
                    if session.team_id is None:
                        raise AuthorizationError("team required")
                    draft = self.server.round_store.get_draft(round_id, session.team_id)
                    if draft is not None and isinstance(draft.get("updated_at"), datetime):
                        draft = dict(draft)
                        draft["updated_at"] = draft["updated_at"].isoformat()
                    self._send_json(HTTPStatus.OK, {"draft": draft})
                elif resource == "submission":
                    if session.team_id is None:
                        raise AuthorizationError("team required")
                    submission = self.server.round_store.get_team_submission(round_id, session.team_id)
                    self._send_json(HTTPStatus.OK, {"submission": self._submission_payload(submission)})
                else:
                    published = record.state is RoundState.PUBLISHED
                    results = []
                    if published:
                        bundle = self.server.round_store.export_round_bundle(round_id)
                        all_results = bundle["team_results"]
                        if session.role == "student" and record.policy.visibility == "private":
                            all_results = [item for item in all_results if item["team_id"] == session.team_id]
                        if record.policy.visibility == "aggregate":
                            results = [{"team_count": len(all_results)}]
                        else:
                            results = [
                                {"team_id": item["team_id"], "rank": item["rank"], "authoritative_total": item["authoritative_total"], "tie_group": item["tie_group"]}
                                for item in all_results
                            ]
                    self._send_json(HTTPStatus.OK, {"published": published, "results": results})
                return True
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
                return True
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "round not found")
                return True
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
                return True
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/evaluate/status", path)
        if match:
            try:
                self._session(match.group(1), instructor=True)
                self._poll_phase3_remote(match.group(1))
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "evaluation job not found")
            except ValueError as error:
                self._phase3_error(HTTPStatus.CONFLICT, "evaluation_job_error", str(error))
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return True
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/audit", path)
        if match:
            try:
                self._session(match.group(1), instructor=True)
                exported = self.server.round_store.export_round_bundle(match.group(1))
                audit_events = exported.get("audit_events", [])
                artifact = next(
                    (event.get("metadata", {}).get("bundle") for event in reversed(audit_events)
                     if isinstance(event, Mapping) and isinstance(event.get("metadata"), Mapping)
                     and isinstance(event["metadata"].get("bundle"), Mapping)),
                    None,
                )
                self._send_json(HTTPStatus.OK, artifact or exported)
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "round not found")
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return True
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/audit/replay", path)
        if match:
            try:
                self._session(match.group(1), instructor=True)
                if self.command != "POST":
                    self._phase3_error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "method not allowed")
                    return True
                payload = self._phase3_body()
                if payload is _JSON_PARSE_ERROR:
                    return True
                if not isinstance(payload, Mapping):
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "audit bundle is required")
                    return True
                replayed = replay_audit_bundle(payload)
                self._send_json(HTTPStatus.OK, {"status": replayed.get("status"), "input_hash": replayed.get("input_hash"), "output_hash": replayed.get("output_hash"), "ranked_results": replayed.get("ranked_results", [])})
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except (KeyError, TypeError, ValueError):
                self._phase3_error(HTTPStatus.UNPROCESSABLE_ENTITY, "validation_failed", "audit bundle could not be replayed")
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return True
        return False

    @staticmethod
    def _submission_payload(submission):
        if submission is None:
            return None
        return {"submission_id": submission.submission_id, "team_id": submission.team_id, "semantic_hash": submission.semantic_hash,
                "idempotency_key": submission.idempotency_key, "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
                "status": submission.status}

    def _read_json_body(self, *, phase3: bool = False) -> object:
        def malformed() -> object:
            if phase3:
                self._phase3_error(HTTPStatus.BAD_REQUEST, "malformed_json", "request body must be valid JSON")
            else:
                self._error(HTTPStatus.BAD_REQUEST, "malformed_json", "request body must be valid JSON")
            return _JSON_PARSE_ERROR

        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            length = 0
        else:
            try:
                length = int(raw_length)
            except ValueError:
                return malformed()
        if length < 0:
            return malformed()
        if length > MAX_REQUEST_BODY_BYTES:
            if phase3:
                self._phase3_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "request body is too large")
            else:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "request body is too large")
            return _JSON_PARSE_ERROR
        try:
            raw_body = self.rfile.read(length)
            return json.loads(raw_body)
        except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError, MemoryError):
            return malformed()

    def do_GET(self) -> None:
        parsed_path = urlsplit(self.path)
        path = parsed_path.path
        try:
            if self._phase3_method_guard(path):
                return
            if self._phase3_get(path):
                return
            if path == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "evaluator_version": self.server.scenario.evaluator_version,
                    },
                )
                return
            if path == "/api/scenario":
                try:
                    selected_period = _selected_period_from_query(parsed_path.query)
                    payload = scenario_response(
                        self.server.scenario, selected_period=selected_period
                    )
                except ValueError as error:
                    self._error(HTTPStatus.BAD_REQUEST, "invalid_period", str(error))
                    return
                self._send_json(HTTPStatus.OK, payload)
                return
            if self._send_static(path):
                return
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
        except Exception:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "internal_error",
                "internal server error",
                request_id=uuid.uuid4().hex,
            )

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if self._phase3_method_guard(path):
            return
        if path == "/api/instructor/rounds":
            try:
                session = self._instructor_session()
                payload = self._phase3_body()
                if payload is _JSON_PARSE_ERROR:
                    return
                if not isinstance(payload, Mapping):
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "request body must be an object")
                    return
                round_id, requested_policy, teams, clone_from = self._round_request(payload)
                with self.server.phase3_lock:
                    session = self._instructor_session()
                    source = self.server.round_store.get_round(clone_from) if clone_from else None
                    if clone_from and source is None:
                        raise KeyError(clone_from)
                    if isinstance(requested_policy, Mapping):
                        if source is None or source.policy is None:
                            raise ValueError("clone source policy is required")
                        values = {
                            "scenario_id": source.policy.scenario_id,
                            "scenario_version": source.policy.scenario_version,
                            "evaluator_version": source.policy.evaluator_version,
                            "policy_version": source.policy.policy_version,
                            "deadline_seconds": source.policy.deadline_seconds,
                            "deadline_at": source.policy.deadline_at,
                            "visibility": source.policy.visibility,
                            "tie_break_mode": source.policy.tie_break_mode,
                            "seed": source.policy.seed,
                            "display_timezone": source.policy.display_timezone,
                        }
                        values.update(requested_policy)
                        requested_policy = RoundPolicy(**values)  # type: ignore[arg-type]
                    elif requested_policy is None and source is not None:
                        requested_policy = source.policy
                    if requested_policy is None:
                        raise ValueError("policy is required")
                    validate_round_policy(requested_policy)
                    record = RoundRecord(round_id, state=RoundState.DRAFT, policy=requested_policy)
                    if clone_from:
                        record = self.server.round_store.clone_round(clone_from, record, teams)
                    else:
                        if teams is None:
                            raise ValueError("teams is required")
                        record = self.server.round_store.create_round(record, teams=teams)
                response = self._round_payload(record)
                response["request_id"] = uuid.uuid4().hex
                response["created_by"] = session.actor_id
                self._send_json(HTTPStatus.CREATED, response)
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "clone source round not found")
            except (TypeError, ValueError, RoundDomainError) as error:
                self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", str(error))
            except sqlite3.IntegrityError:
                self._phase3_error(HTTPStatus.CONFLICT, "round_exists", "round already exists")
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return
        if path == "/api/session":
            try:
                credential = self.headers.get("X-Bootstrap-Credential", "")
                configured = self.server.bootstrap_credential
                if configured is None or not hmac.compare_digest(credential, configured):
                    self._phase3_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "trusted bootstrap credential required")
                    return
                payload = self._phase3_body()
                if payload is _JSON_PARSE_ERROR:
                    return
                if not isinstance(payload, Mapping):
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "request body must be an object")
                    return
                with self.server.phase3_lock:
                    issued = self.server.session_manager.issue(
                        str(payload.get("actor_id", "")), str(payload.get("round_id", "")),
                        role=str(payload.get("role", "")), team_id=payload.get("team_id"),
                    )
                self._send_json(HTTPStatus.CREATED, {"token": issued.token, "session": {
                    "session_id": issued.record.session_id, "actor_id": issued.record.actor_id,
                    "round_id": issued.record.round_id, "team_id": issued.record.team_id,
                    "role": issued.record.role,
                }})
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "round or team not found")
            except (TypeError, ValueError):
                self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "invalid session request")
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return
        if path == "/api/session/revoke":
            try:
                header = self.headers.get("Authorization", "")
                if not header.startswith("Bearer ") or not header[7:].strip():
                    raise AuthenticationError("missing bearer token")
                token = header[7:].strip()
                with self.server.phase3_lock:
                    self.server.session_manager.authenticate(token)
                    self.server.session_manager.revoke(token)
                self._send_json(HTTPStatus.OK, {"revoked": True})
            except AuthenticationError:
                self._phase3_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "authentication required")
            return
        match = re.fullmatch(r"/api/rounds/([^/]+)/submit", path)
        if match:
            round_id = match.group(1)
            try:
                session = self._session(round_id)
                if session.team_id is None:
                    raise AuthorizationError("team required")
                payload = self._phase3_body()
                if payload is _JSON_PARSE_ERROR:
                    return
                if not isinstance(payload, Mapping) or not isinstance(payload.get("plan"), Mapping):
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "request body must contain plan")
                    return
                idempotency_key = self.headers.get("Idempotency-Key") or payload.get("idempotency_key")
                if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "idempotency key is required")
                    return
                plan_payload = dict(payload["plan"])
                if plan_payload.get("team_id", session.team_id) != session.team_id:
                    raise AuthorizationError("plan team does not match authenticated team")
                plan_payload["team_id"] = session.team_id
                with self.server.phase3_lock:
                    session = self._session(round_id)
                    batch = build_batch_input(self.server.scenario, [plan_payload], config=self.server.config)
                    duplicate = self.server.round_store.get_team_submission(round_id, session.team_id)
                    submission = self.server.round_store.insert_submission(
                        round_id, session.team_id, plan_payload, str(batch["canonical_hash"]), idempotency_key
                    )
                status = HTTPStatus.OK if duplicate is not None and duplicate.idempotency_key == idempotency_key else HTTPStatus.CREATED
                self._send_json(status, {"submission": self._submission_payload(submission)})
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except ValueError as error:
                message = str(error)
                code = "deadline_passed" if "deadline" in message else "round_not_open" if "open round" in message else "duplicate_submission"
                self._phase3_error(HTTPStatus.CONFLICT, code, message if code != "duplicate_submission" else "submission already exists")
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return
        match = re.fullmatch(r"/api/rounds/([^/]+)/draft", path)
        if match and self.command == "POST":
            try:
                self._session(match.group(1))
                self._phase3_error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "method not allowed")
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            return
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/transition", path)
        if match:
            try:
                self._session(match.group(1), instructor=True)
                payload = self._phase3_body()
                if payload is _JSON_PARSE_ERROR:
                    return
                if not isinstance(payload, Mapping) or payload.get("state") not in {state.value for state in RoundState}:
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "state is required")
                    return
                with self.server.phase3_lock:
                    session = self._session(match.group(1), instructor=True)
                    record = self.server.round_store.transition_round(match.group(1), RoundState(payload["state"]), actor_id=session.actor_id, reason=payload.get("reason"))
                self._send_json(HTTPStatus.OK, self._round_payload(record))
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "round not found")
            except ValueError as error:
                self._phase3_error(HTTPStatus.CONFLICT, "invalid_transition", str(error))
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/evaluate/cancel", path)
        if match:
            try:
                session = self._session(match.group(1), instructor=True)
                dispatcher = self.server.evaluation_dispatcher
                if dispatcher is None:
                    self._phase3_error(HTTPStatus.CONFLICT, "dispatcher_not_configured", "remote evaluation is not configured")
                    return
                with self.server.phase3_lock:
                    job = dispatcher.find_for_round(match.group(1))
                    if job is None:
                        raise KeyError(match.group(1))
                    job = dispatcher.cancel(job.job_id)
                    state = self._phase3_round(match.group(1)).state.value
                self._send_json(HTTPStatus.OK, {"state": state, "evaluation_job_id": job.job_id, "status": job.status.value, "actor_id": session.actor_id})
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except KeyError:
                self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "evaluation job not found")
            except ValueError as error:
                self._phase3_error(HTTPStatus.CONFLICT, "evaluation_job_error", str(error))
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/evaluate", path)
        if match:
            try:
                self._session(match.group(1), instructor=True)
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
                return
            payload = self._phase3_body()
            if payload is _JSON_PARSE_ERROR:
                return
            if not isinstance(payload, Mapping):
                self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "request body must be an object")
                return
            self._evaluate_phase3(match.group(1))
            return
        match = re.fullmatch(r"/api/instructor/rounds/([^/]+)/audit/replay", path)
        if match:
            try:
                session = self._session(match.group(1), instructor=True)
                payload = self._phase3_body()
                if payload is _JSON_PARSE_ERROR:
                    return
                if not isinstance(payload, Mapping):
                    self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "audit bundle is required")
                    return
                replayed = replay_audit_bundle(payload)
                self._send_json(HTTPStatus.OK, {"status": replayed.get("status"), "input_hash": replayed.get("input_hash"), "output_hash": replayed.get("output_hash"), "ranked_results": replayed.get("ranked_results", []), "actor_id": session.actor_id})
            except (AuthenticationError, AuthorizationError) as error:
                self._phase3_auth_error(error)
            except (KeyError, TypeError, ValueError):
                self._phase3_error(HTTPStatus.UNPROCESSABLE_ENTITY, "validation_failed", "audit bundle could not be replayed")
            except Exception:
                self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")
            return
        if urlsplit(self.path).path != "/api/evaluate" and path != "/api/evaluate":
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return

        try:
            payload = self._read_json_body()
            if payload is _JSON_PARSE_ERROR:
                return
            if not isinstance(payload, Mapping) or "plan" not in payload:
                self._error(HTTPStatus.BAD_REQUEST, "missing_plan", "request body must contain plan")
                return
            plan_payload = payload["plan"]
            if not isinstance(plan_payload, Mapping):
                self._error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_plan",
                    "plan payload is malformed: plan must be an object",
                )
                return
            try:
                plan = plan_from_dict(cast(Mapping[str, object], plan_payload))
            except (KeyError, TypeError, ValueError) as error:
                self._error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_plan",
                    f"plan payload is malformed: {error}",
                )
                return
            try:
                result = evaluate_week(self.server.scenario, self.server.config, (plan,))
            except EvaluationInputError as error:
                self._error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "evaluation_input",
                    "; ".join(error.errors),
                    include_version=True,
                )
                return
            self._send_json(HTTPStatus.OK, evaluation_response(result))
        except Exception:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "internal_error",
                "internal server error",
                request_id=uuid.uuid4().hex,
            )

    def _evaluate_phase3(self, round_id: str) -> None:
        if self.server.evaluation_dispatcher is not None:
            return self._queue_phase3_remote(round_id)
        with self.server.phase3_lock:
            return self._evaluate_phase3_unlocked(round_id)

    def _queue_phase3_remote(self, round_id: str) -> None:
        dispatcher = self.server.evaluation_dispatcher
        assert dispatcher is not None
        try:
            with self.server.phase3_lock:
                session = self._session(round_id, instructor=True)
                existing = dispatcher.find_for_round(round_id)
                if existing is not None:
                    self._send_json(HTTPStatus.ACCEPTED, {
                        "state": self._phase3_round(round_id).state.value,
                        "evaluation_job_id": existing.job_id,
                        "remote_job_id": existing.remote_job_id,
                        "status": existing.status.value,
                        "input_hash": existing.batch_input_hash,
                        "idempotent": True,
                    })
                    return
                snapshot = self.server.round_store.lock_submission_snapshot(round_id, actor_id=session.actor_id)
                record = self.server.round_store.get_round(round_id)
                assert record is not None and record.policy is not None
                package_root = dispatcher.state_path.parent / "packages"
                package = create_local_job(
                    package_root,
                    self.server.scenario,
                    [{"team_id": item.team_id, "payload": item.payload} for item in snapshot],
                    round_id=round_id,
                    job_id=f"{round_id}-{uuid.uuid4().hex}",
                    config=self.server.config,
                    policy_version=record.policy.policy_version,
                    seed=record.policy.seed,
                    tie_break_mode=record.policy.tie_break_mode,
                )
                job = dispatcher.submit(package.path)
                self.server.round_store.create_evaluation_run(EvaluationRunRecord(
                    job.job_id, round_id, job.batch_input_hash, record.policy.seed, "queued",
                ))
            self._send_json(HTTPStatus.ACCEPTED, {
                "state": "locked",
                "evaluation_job_id": job.job_id,
                "remote_job_id": job.remote_job_id,
                "status": job.status.value,
                "input_hash": job.batch_input_hash,
            })
        except (AuthenticationError, AuthorizationError) as error:
            self._phase3_auth_error(error)
        except KeyError:
            self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "round not found")
        except ValueError as error:
            self._phase3_error(HTTPStatus.CONFLICT, "evaluation_job_error", str(error))
        except Exception:
            self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")

    def _poll_phase3_remote(self, round_id: str) -> None:
        dispatcher = self.server.evaluation_dispatcher
        if dispatcher is None:
            self._phase3_error(HTTPStatus.CONFLICT, "dispatcher_not_configured", "remote evaluation is not configured")
            return
        with self.server.phase3_lock:
            job = dispatcher.find_for_round(round_id)
            if job is None:
                raise KeyError(round_id)
            job = dispatcher.poll(job.job_id)
            record = self._phase3_round(round_id)
            completed_run_id = f"{job.job_id}-artifact" if job.status is RemoteJobStatus.COMPLETE else None
            if job.status is RemoteJobStatus.COMPLETE and record.state is RoundState.LOCKED:
                assert job.artifact_path is not None
                artifact = json.loads(job.artifact_path.read_text(encoding="utf-8"))
                evaluation = artifact["evaluation"]
                completed = self.server.round_store.create_evaluation_run(EvaluationRunRecord(
                    completed_run_id, round_id, job.batch_input_hash, evaluation.get("batch_input", {}).get("seed"), "complete",
                ))
                ranked = evaluation.get("ranked_results", ())
                self.server.round_store.store_results(completed.evaluation_run_id, [
                    TeamResultRecord(
                        str(item["team_id"]), float(item["official_revenue"]), int(item["rank"]),
                        str(item["tie_group"]), record.policy.visibility, completed.evaluation_run_id,
                        dict(item),
                    )
                    for item in ranked if isinstance(item, Mapping)
                ])
                self.server.round_store.record_audit_event(
                    round_id,
                    actor_id="remote-evaluation-worker",
                    action="evaluation.artifact",
                    target_id=completed.evaluation_run_id,
                    metadata={"bundle": artifact["audit_bundle"], "remote_job_id": job.remote_job_id},
                )
                record = self.server.round_store.transition_round(round_id, RoundState.EVALUATED, actor_id="remote-evaluation-worker")
            elif job.status is RemoteJobStatus.TERMINAL_FAILED and record.state is RoundState.LOCKED:
                self.server.round_store.transition_round(round_id, RoundState.EVALUATED, actor_id="remote-evaluation-worker", reason="remote evaluation failed")
                record = self.server.round_store.transition_round(round_id, RoundState.FAILED, actor_id="remote-evaluation-worker", reason=job.error)
            status_code = HTTPStatus.OK if job.status in {RemoteJobStatus.COMPLETE, RemoteJobStatus.CANCELLED} else HTTPStatus.UNPROCESSABLE_ENTITY if job.status is RemoteJobStatus.TERMINAL_FAILED else HTTPStatus.ACCEPTED
            self._send_json(status_code, {
                "state": record.state.value,
                "evaluation_job_id": job.job_id,
                "remote_job_id": job.remote_job_id,
                "status": job.status.value,
                "input_hash": job.batch_input_hash,
                "output_hash": job.output_hash,
                "evaluation_run_id": completed_run_id,
                "error": job.error,
            })

    def _evaluate_phase3_unlocked(self, round_id: str) -> None:
        try:
            session = self._session(round_id, instructor=True)
            existing = self.server.round_store.get_round(round_id)
            if existing is None:
                raise KeyError(round_id)
            if existing.state in {RoundState.EVALUATED, RoundState.PUBLISHED}:
                bundle = self.server.round_store.export_round_bundle(round_id)
                runs = bundle.get("evaluation_runs", [])
                if runs:
                    run = runs[-1]
                    self._send_json(HTTPStatus.OK, {
                        "state": existing.state.value,
                        "evaluation_run_id": run["evaluation_run_id"],
                        "input_hash": run["batch_input_hash"],
                        "idempotent": True,
                    })
                    return
            session = self._session(round_id, instructor=True)
            snapshot = self.server.round_store.lock_submission_snapshot(round_id, actor_id=session.actor_id)
            record = self.server.round_store.get_round(round_id)
            assert record is not None and record.policy is not None
            evaluation = evaluate_locked_round(
                self.server.scenario, [{"team_id": item.team_id, "payload": item.payload} for item in snapshot],
                config=self.server.config, policy_version=record.policy.policy_version,
                seed=record.policy.seed, tie_break_mode=record.policy.tie_break_mode,
            )
            run_id = uuid.uuid4().hex
            run = self.server.round_store.create_evaluation_run(EvaluationRunRecord(
                run_id, round_id, str(evaluation.get("input_hash", "")), record.policy.seed,
                "complete" if evaluation.get("status") == "complete" else "failed", error=evaluation.get("error"),
            ))
            if evaluation.get("status") != "complete":
                self.server.round_store.transition_round(round_id, RoundState.EVALUATED, actor_id=session.actor_id, reason="evaluation attempted")
                self.server.round_store.transition_round(round_id, RoundState.FAILED, actor_id=session.actor_id, reason="evaluation failed")
                self._phase3_error(HTTPStatus.UNPROCESSABLE_ENTITY, "evaluation_failed", "evaluation failed")
                return
            ranked = evaluation.get("ranked_results", ())
            self.server.round_store.store_results(run.evaluation_run_id, [
                TeamResultRecord(str(item["team_id"]), float(item["official_revenue"]), int(item["rank"]), str(item["tie_group"]), record.policy.visibility, run_id, dict(item))
                for item in ranked if isinstance(item, Mapping)
            ])
            self.server.round_store.record_audit_event(
                round_id, actor_id=session.actor_id, action="evaluation.artifact",
                target_id=run_id, metadata={"bundle": build_audit_bundle(evaluation)},
            )
            record = self.server.round_store.transition_round(round_id, RoundState.EVALUATED, actor_id=session.actor_id)
            self._send_json(HTTPStatus.OK, {"state": record.state.value, "evaluation_run_id": run_id, "input_hash": evaluation.get("input_hash")})
        except (AuthenticationError, AuthorizationError) as error:
            self._phase3_auth_error(error)
        except ValueError as error:
            self._phase3_error(HTTPStatus.CONFLICT, "invalid_transition", str(error))
        except Exception:
            self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        if self._phase3_method_guard(path):
            return
        match = re.fullmatch(r"/api/rounds/([^/]+)/draft", path)
        if not match:
            self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        try:
            round_id = match.group(1)
            session = self._session(round_id)
            if session.team_id is None:
                raise AuthorizationError("team required")
            payload = self._phase3_body()
            if payload is _JSON_PARSE_ERROR:
                return
            if not isinstance(payload, Mapping) or not isinstance(payload.get("plan"), Mapping):
                self._phase3_error(HTTPStatus.BAD_REQUEST, "validation_failed", "request body must contain plan")
                return
            if payload["plan"].get("team_id", session.team_id) != session.team_id:
                raise AuthorizationError("plan team does not match authenticated team")
            with self.server.phase3_lock:
                session = self._session(round_id)
                draft = self.server.round_store.upsert_draft(
                    round_id, session.team_id, dict(payload["plan"]), revision=payload.get("revision")
                )
            draft["updated_at"] = draft["updated_at"].isoformat()
            self._send_json(HTTPStatus.OK, {"draft": draft})
        except (AuthenticationError, AuthorizationError) as error:
            self._phase3_auth_error(error)
        except ValueError as error:
            message = str(error)
            code = "deadline_passed" if message == "round deadline has passed" else "round_not_open" if "open" in message else "validation_failed"
            self._phase3_error(HTTPStatus.CONFLICT, code, message)
        except KeyError:
            self._phase3_error(HTTPStatus.NOT_FOUND, "not_found", "round not found")
        except Exception:
            self._phase3_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")

    def _phase3_unsupported_method(self) -> None:
        path = urlsplit(self.path).path
        if self._phase3_method_guard(path):
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")

    def do_DELETE(self) -> None:
        self._phase3_unsupported_method()

    def do_PATCH(self) -> None:
        self._phase3_unsupported_method()

    def do_OPTIONS(self) -> None:
        self._phase3_unsupported_method()

    def do_HEAD(self) -> None:
        self._phase3_unsupported_method()


def create_server(
    *,
    scenario_path: Path | str | None = None,
    host: str = "localhost",
    port: int = 8000,
    round_store: RoundStore | None = None,
    bootstrap_credential: str | None = None,
    evaluation_dispatcher: RemoteJobDispatcher | None = None,
) -> PracticeHTTPServer:
    """Load inputs once and return a ready-to-serve practice server."""
    scenario = _load_scenario(Path(scenario_path) if scenario_path is not None else _default_scenario_path())
    config = resolve_evaluation_config(scenario)
    return PracticeHTTPServer((host, port), scenario, config, round_store, bootstrap_credential, evaluation_dispatcher)


@contextmanager
def server_context(
    *,
    scenario_path: Path | str | None = None,
    host: str = "localhost",
    port: int = 0,
) -> Iterator[PracticeHTTPServer]:
    """Run a practice server in a background thread and clean it up reliably."""
    server = create_server(scenario_path=scenario_path, host=host, port=port)
    ready = threading.Event()
    worker_errors: list[BaseException] = []
    server._practice_ready_event = ready

    def serve() -> None:
        try:
            server.serve_forever(poll_interval=0.01)
        except BaseException as error:
            worker_errors.append(error)
        finally:
            ready.set()

    thread = threading.Thread(target=serve, daemon=True)
    server._practice_server_thread = thread
    thread.start()
    if not ready.wait(timeout=2):
        server.server_close()
        thread.join()
        raise RuntimeError("practice server did not become ready")
    if worker_errors:
        server.server_close()
        thread.join()
        raise RuntimeError("practice server failed during startup") from worker_errors[0]
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        assert not thread.is_alive()
        if worker_errors:
            raise RuntimeError("practice server failed in background") from worker_errors[0]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local ERCOT practice HTTP server")
    parser.add_argument("--scenario", type=Path, default=_default_scenario_path())
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    server = create_server(scenario_path=args.scenario, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
