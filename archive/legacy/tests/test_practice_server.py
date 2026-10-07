import copy
import http.client
import json
from pathlib import Path
import re
import socket
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from ercot_game import practice_server
from ercot_game.auth import SessionManager
from ercot_game.round_models import RoundPolicy, RoundRecord, RoundState
from ercot_game.round_store import RoundStore
from ercot_game.practice_serialization import scenario_response


FIXTURE = Path(__file__).parents[1] / "data/fixtures/ercot_small.json"


VALID_PLAN = {
    "team_id": "team-alpha",
    "bus_id": "bus-central",
    "path_corridors": ["corridor-west-central"],
    "capacity_mw": 10.0,
    "profile": [1.0] * 6,
    "generator": None,
    "intervention_budget_k": 0,
    "curtailment_depth_mu": 0.0,
    "flexibility_fee_per_mwh": 0.0,
}


CANONICAL_PLAN = {
    "team_id": "team-canonical",
    "connections": [
        {
            "connection_id": "site-z",
            "bus_id": "bus-panhandle-01",
            "path_corridors": [],
            "capacity_mw": 5.0,
            "profile": [0.5] * 6,
        },
        {
            "connection_id": "site-a",
            "bus_id": "bus-coast-01",
            "path_corridors": [],
            "capacity_mw": 5.0,
            "profile": [0.5] * 6,
        },
    ],
    "generators": [
        {
            "generator_id": "gen-z",
            "connection_id": "site-z",
            "capacity_mw": 1.0,
            "marginal_cost_per_mwh": 20.0,
        },
        {
            "generator_id": "gen-a",
            "connection_id": "site-a",
            "capacity_mw": 1.0,
            "marginal_cost_per_mwh": 10.0,
        },
    ],
    "intervention_budget_k": 0,
    "curtailment_depth_mu": 0.0,
    "flexibility_fee_per_mwh": 0.0,
}


@pytest.fixture
def running_server():
    server = practice_server.create_server(scenario_path=FIXTURE, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, method, path, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    headers = {}
    encoded = None
    if body is not None:
        encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response, raw, json.loads(raw)


def raw_request(server, method, path):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    connection.request(method, path)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response, raw


@pytest.fixture
def phase3_server(tmp_path):
    store = RoundStore(tmp_path / "classroom.sqlite")
    store.create_round(
        RoundRecord(
            "round-1",
            policy=RoundPolicy(
                "ercot-small-week-01", "1", "0.3.0", deadline_seconds=3600
            ),
        ),
        teams=("team-alpha", "team-beta"),
    )
    store.transition_round("round-1", RoundState.OPEN, actor_id="teacher")
    server = practice_server.create_server(
        scenario_path=FIXTURE, port=0, round_store=store, bootstrap_credential="test-bootstrap"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def phase3_request(server, method, path, body=None, token=None, idempotency_key=None, include_bootstrap=True):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if include_bootstrap and getattr(server, "bootstrap_credential", None):
        headers["X-Bootstrap-Credential"] = server.bootstrap_credential
    encoded = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response, raw, json.loads(raw)


def issue_phase3_session(server, actor_id, role, team_id=None):
    response, _, payload = phase3_request(
        server, "POST", "/api/session", {
            "actor_id": actor_id,
            "round_id": "round-1",
            "role": role,
            **({"team_id": team_id} if team_id else {}),
        }
    )
    assert response.status == 201
    return payload["token"]


def test_instructor_can_create_and_clone_rounds_without_mutating_source(phase3_server):
    server, store = phase3_server
    instructor = issue_phase3_session(server, "teacher", "instructor")
    policy = {
        "scenario_id": "ercot-small-week-01",
        "scenario_version": "1",
        "evaluator_version": "0.3.0",
        "policy_version": "week-2",
        "deadline_seconds": 120,
        "deadline_at": None,
        "visibility": "aggregate",
        "tie_break_mode": "default",
        "seed": None,
        "display_timezone": "UTC",
    }
    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds",
        {"round_id": "round-2", "policy": policy, "teams": ["team-alpha", {"team_id": "team-beta", "display_name": "Beta"}]},
        token=instructor,
    )
    assert response.status == 201
    assert payload["round_id"] == "round-2"
    assert payload["state"] == "draft"
    assert payload["request_id"]
    assert store.list_teams("round-2") == ("team-alpha", "team-beta")

    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds",
        {"round_id": "round-3", "clone_from": "round-2", "policy": {"policy_version": "week-3"}, "teams": ["team-gamma"]},
        token=instructor,
    )
    assert response.status == 201
    assert payload["round_id"] == "round-3"
    assert payload["policy"]["policy_version"] == "week-3"
    assert store.list_teams("round-3") == ("team-gamma",)
    assert store.get_round("round-2").policy.policy_version == "week-2"
    assert store.list_teams("round-2") == ("team-alpha", "team-beta")


def test_round_creation_is_instructor_only_and_validates_structured_input(phase3_server):
    server, _ = phase3_server
    student = issue_phase3_session(server, "alice", "student", "team-alpha")
    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds", {}, token=student
    )
    assert response.status == 403
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["request_id"]

    instructor = issue_phase3_session(server, "teacher", "instructor")
    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds",
        {"round_id": "bad", "policy": {"scenario_id": "only"}, "teams": []},
        token=instructor,
    )
    assert response.status == 400
    assert payload["error"]["code"] == "validation_failed"
    assert payload["error"]["request_id"]

    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds",
        {"round_id": "clone-missing", "clone_from": "does-not-exist"},
        token=instructor,
    )
    assert response.status == 404
    assert payload["error"]["code"] == "not_found"
    assert payload["error"]["request_id"]


def test_late_draft_has_same_deadline_error_as_late_submission(phase3_server):
    server, store = phase3_server
    instructor = issue_phase3_session(server, "teacher", "instructor")
    student = issue_phase3_session(server, "alice", "student", "team-alpha")
    store.connection.execute("UPDATE rounds SET deadline_at = ? WHERE round_id = ?", ("2026-01-01T00:00:00Z", "round-1"))
    response, _, payload = phase3_request(
        server, "PUT", "/api/rounds/round-1/draft", {"plan": VALID_PLAN}, token=student
    )
    assert response.status == 409
    assert payload["error"]["code"] == "deadline_passed"
    assert payload["error"]["request_id"]


def test_file_store_server_preserves_injected_clock_for_draft_and_submission_deadlines(tmp_path):
    current = [datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)]
    store = RoundStore(tmp_path / "clocked.sqlite", clock=lambda: current[0])
    store.create_round(
        RoundRecord(
            "round-1",
            policy=RoundPolicy("ercot-small-week-01", "1", "0.3.0", deadline_at=current[0] + timedelta(seconds=30)),
        ),
        teams=("team-alpha",),
    )
    store.transition_round("round-1", RoundState.OPEN, actor_id="teacher")
    server = practice_server.create_server(
        scenario_path=FIXTURE, port=0, round_store=store, bootstrap_credential="test-bootstrap"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        student = issue_phase3_session(server, "alice", "student", "team-alpha")
        current[0] += timedelta(seconds=31)
        draft_response, _, draft_payload = phase3_request(
            server, "PUT", "/api/rounds/round-1/draft", {"plan": VALID_PLAN}, token=student
        )
        assert draft_response.status == 409
        assert draft_payload["error"]["code"] == "deadline_passed"
        submit_response, _, submit_payload = phase3_request(
            server, "POST", "/api/rounds/round-1/submit", {"plan": VALID_PLAN}, token=student, idempotency_key="late"
        )
        assert submit_response.status == 409
        assert submit_payload["error"]["code"] == "deadline_passed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_health_returns_version_and_json_headers(running_server):
    response, raw, payload = request(running_server, "GET", "/api/health")

    assert response.status == 200
    assert payload == {"status": "ok", "evaluator_version": "0.3.0"}
    assert response.getheader("Content-Type") == "application/json"
    assert int(response.getheader("Content-Length")) == len(raw)


def test_scenario_returns_six_periods_and_map_metadata(running_server):
    response, _, payload = request(running_server, "GET", "/api/scenario")

    assert response.status == 200
    assert payload["time_horizon"] == 6
    assert payload["map"]["bus_coordinates"]
    assert payload["map"]["corridor_paths"]


@pytest.mark.parametrize(
    ("route", "relative_path", "content_type", "body"),
    [
        ("/results", "results.html", "text/html; charset=utf-8", b'<main data-results-mode="readonly"></main>'),
        ("/results.js", "results.js", "application/javascript; charset=utf-8", b"console.log('results');"),
        (
            "/data/results/round_metadata.json",
            "data/results/round_metadata.json",
            "application/json; charset=utf-8",
            b'{"round_id":"round-01"}',
        ),
        (
            "/data/results/public_network.json",
            "data/results/public_network.json",
            "application/json; charset=utf-8",
            b'{"buses":[]}',
        ),
        (
            "/data/results/team_report.json",
            "data/results/team_report.json",
            "application/json; charset=utf-8",
            b'{"team_id":"team-alpha"}',
        ),
        (
            "/data/results/aggregate_grid_summary.json",
            "data/results/aggregate_grid_summary.json",
            "application/json; charset=utf-8",
            b'{"regions":[]}',
        ),
    ],
)
def test_results_assets_are_public_and_served_with_expected_content_types(
    running_server, monkeypatch, tmp_path, route, relative_path, content_type, body
):
    asset_path = tmp_path / relative_path
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(body)
    monkeypatch.setattr(practice_server, "_web_root", lambda: tmp_path)

    response, raw = raw_request(running_server, "GET", route)

    assert response.status == 200
    assert response.getheader("Content-Type") == content_type
    assert raw == body


def test_results_route_serves_the_real_results_shell(running_server):
    response, raw = raw_request(running_server, "GET", "/results")

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert b'data-results-mode="readonly"' in raw
    assert b'id="results-view"' in raw
    assert b'id="workspace"' not in raw
    assert b'ERCOT Connection Planning' not in raw


def test_unknown_results_asset_returns_json_404(running_server, monkeypatch, tmp_path):
    monkeypatch.setattr(practice_server, "_web_root", lambda: tmp_path)

    response, raw = raw_request(running_server, "GET", "/data/results/not-published.json")

    assert response.status == 404
    assert response.getheader("Content-Type") == "application/json"
    payload = json.loads(raw)
    assert payload["error"]["code"] == "not_found"


def test_scenario_supports_selected_period_query_and_canonical_map_metadata(running_server):
    response, _, payload = request(running_server, "GET", "/api/scenario?period=2")

    assert response.status == 200
    assert len(payload["buses"]) == 32
    assert len(payload["corridors"]) == 48
    assert payload["selected_period"]["index"] == 2
    assert payload["selected_period"]["buses"][0]["headroom_mw"] == 21
    assert payload["zones"] == payload["presentation"]["zone_labels"]
    assert payload["tutorial_hints"] == payload["presentation"]["tutorial_hints"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/scenario?peroid=1",
        "/api/scenario?period=1&period=2",
        "/api/scenario?period=not-an-integer",
        "/api/scenario?period=",
        "/api/scenario?period=6",
        "/api/scenario?period=1&unknown=value",
        "/api/scenario?period",
    ],
)
def test_scenario_rejects_strict_query_contract_with_structured_400(running_server, path):
    response, _, payload = request(running_server, "GET", path)

    assert response.status == 400
    assert payload["error"]["code"] == "invalid_period"
    assert payload["error"]["message"]
    assert "Traceback" not in json.dumps(payload)


def test_evaluate_returns_deterministic_serialized_result(running_server):
    first = request(running_server, "POST", "/api/evaluate", {"plan": VALID_PLAN})
    second = request(running_server, "POST", "/api/evaluate", {"plan": VALID_PLAN})

    assert first[0].status == second[0].status == 200
    assert first[2] == second[2]
    assert first[2]["evaluator_version"] == "0.3.0"
    assert first[2]["team_results"][0]["team_id"] == "team-alpha"


def test_evaluate_accepts_canonical_multi_site_plan_and_returns_canonical_fields(running_server):
    first = request(running_server, "POST", "/api/evaluate", {"plan": CANONICAL_PLAN})
    second = request(running_server, "POST", "/api/evaluate", {"plan": CANONICAL_PLAN})

    assert first[0].status == second[0].status == 200
    assert first[2] == second[2]
    assert [site["connection_id"] for site in first[2]["connection_results"]] == [
        "site-a",
        "site-z",
    ]
    assert [item["generator_id"] for item in first[2]["generator_dispatch"]] == [
        "gen-a",
        "gen-z",
    ]
    assert first[2]["team_totals"][0]["team_id"] == "team-canonical"
    team = first[2]["team_results"][0]
    assert [item["connection_id"] for item in team["site_diagnostics"]] == [
        "site-a",
        "site-z",
    ]


def test_evaluate_legacy_and_canonical_single_site_plans_share_semantic_input_hash(running_server):
    legacy = request(running_server, "POST", "/api/evaluate", {"plan": VALID_PLAN})
    canonical = {
        "team_id": VALID_PLAN["team_id"],
        "connections": [
            {
                "connection_id": "connection-legacy",
                "bus_id": VALID_PLAN["bus_id"],
                "path_corridors": VALID_PLAN["path_corridors"],
                "capacity_mw": VALID_PLAN["capacity_mw"],
                "profile": VALID_PLAN["profile"],
            }
        ],
        "generators": [],
        "intervention_budget_k": VALID_PLAN["intervention_budget_k"],
        "curtailment_depth_mu": VALID_PLAN["curtailment_depth_mu"],
        "flexibility_fee_per_mwh": VALID_PLAN["flexibility_fee_per_mwh"],
    }
    canonical_response = request(
        running_server, "POST", "/api/evaluate", {"plan": canonical}
    )

    assert legacy[0].status == canonical_response[0].status == 200
    assert legacy[2]["input_hash"] == canonical_response[2]["input_hash"]


def test_malformed_canonical_reference_is_a_safe_invalid_plan(running_server):
    malformed = copy.deepcopy(CANONICAL_PLAN)
    malformed["generators"][0]["connection_id"] = "missing-site"

    response, _, payload = request(running_server, "POST", "/api/evaluate", {"plan": malformed})

    assert response.status == 422
    assert payload["error"]["code"] == "invalid_plan"
    assert "missing-site" in payload["error"]["message"]
    assert "Traceback" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("field_path", "expected_fragment"),
    (
        (("connections", 0, "connection_id"), "connection_id must not be empty"),
        (("generators", 0, "generator_id"), "generator_id must not be empty"),
    ),
)
@pytest.mark.parametrize("blank_id", ("", "   "))
def test_blank_canonical_ids_are_structured_evaluation_errors(
    running_server, field_path, expected_fragment, blank_id
):
    malformed = copy.deepcopy(CANONICAL_PLAN)
    target = malformed
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = blank_id
    if field_path[0] == "connections":
        malformed["generators"][0]["connection_id"] = blank_id

    response, _, payload = request(running_server, "POST", "/api/evaluate", {"plan": malformed})

    assert response.status == 422
    assert payload["error"]["code"] == "evaluation_input"
    assert expected_fragment in payload["error"]["message"]
    assert payload["error"]["evaluator_version"] == "0.3.0"
    assert "Traceback" not in json.dumps(payload)


def test_malformed_json_and_missing_plan_are_structured_400s(running_server):
    malformed = request(running_server, "POST", "/api/evaluate", b"{")
    missing = request(running_server, "POST", "/api/evaluate", {})

    assert malformed[0].status == 400
    assert malformed[2] == {
        "error": {"code": "malformed_json", "message": "request body must be valid JSON"}
    }
    assert missing[0].status == 400
    assert missing[2] == {
        "error": {"code": "missing_plan", "message": "request body must contain plan"}
    }


def test_deeply_nested_json_below_size_limit_is_a_structured_malformed_json_400(running_server):
    nested_json = b"[" * 20000 + b"]" * 20000

    assert len(nested_json) < practice_server.MAX_REQUEST_BODY_BYTES
    response, _, payload = request(running_server, "POST", "/api/evaluate", nested_json)

    assert response.status == 400
    assert payload == {
        "error": {"code": "malformed_json", "message": "request body must be valid JSON"}
    }
    assert "Traceback" not in json.dumps(payload)


@pytest.mark.parametrize("body", [b"null", b"[]", b'"text"', b"1", b"true"])
def test_non_object_json_is_a_structured_400(running_server, body):
    response, _, payload = request(running_server, "POST", "/api/evaluate", body)

    assert response.status == 400
    assert payload == {
        "error": {"code": "missing_plan", "message": "request body must contain plan"}
    }


def test_invalid_plan_has_deterministic_422_message(running_server):
    body = {"plan": {"team_id": "team-alpha"}}

    first = request(running_server, "POST", "/api/evaluate", body)
    second = request(running_server, "POST", "/api/evaluate", body)

    assert first[0].status == second[0].status == 422
    assert first[2] == second[2]
    assert first[2]["error"]["code"] == "invalid_plan"
    assert "payload is malformed" in first[2]["error"]["message"]


def test_evaluation_input_error_includes_version(running_server):
    invalid = copy.deepcopy(VALID_PLAN)
    invalid["bus_id"] = "does-not-exist"

    response, _, payload = request(running_server, "POST", "/api/evaluate", {"plan": invalid})

    assert response.status == 422
    assert payload["error"]["code"] == "evaluation_input"
    assert payload["error"]["evaluator_version"] == "0.3.0"
    assert "team-alpha" in payload["error"]["message"]


def test_unexpected_exception_is_request_safe(monkeypatch, running_server):
    def explode(*args, **kwargs):
        raise RuntimeError("secret traceback detail")

    monkeypatch.setattr(practice_server, "evaluate_week", explode)
    response, _, payload = request(running_server, "POST", "/api/evaluate", {"plan": VALID_PLAN})

    assert response.status == 500
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == "internal server error"
    assert re.fullmatch(r"[0-9a-f]{32}", payload["error"]["request_id"])
    serialized = json.dumps(payload)
    assert "secret traceback detail" not in serialized
    assert "Traceback" not in serialized


def test_unknown_route_returns_404(running_server):
    response, _, payload = request(running_server, "GET", "/unknown")

    assert response.status == 404
    assert payload == {"error": {"code": "not_found", "message": "route not found"}}


def test_request_body_size_limit_returns_413(running_server):
    connection = socket.create_connection(("127.0.0.1", running_server.server_address[1]))
    connection.sendall(
        (
            "POST /api/evaluate HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {practice_server.MAX_REQUEST_BODY_BYTES + 1}\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
    )
    chunks = []
    while chunk := connection.recv(4096):
        chunks.append(chunk)
    raw_response = b"".join(chunks)
    connection.close()
    header, raw_body = raw_response.split(b"\r\n\r\n", 1)
    response_status = int(header.splitlines()[0].split()[1])
    payload = json.loads(raw_body)

    assert response_status == 413
    assert payload == {
        "error": {"code": "request_too_large", "message": "request body is too large"}
    }


def test_requests_do_not_mutate_loaded_scenario(running_server):
    before = scenario_response(running_server.scenario)

    request(running_server, "GET", "/api/scenario")
    request(running_server, "POST", "/api/evaluate", {"plan": VALID_PLAN})

    assert scenario_response(running_server.scenario) == before


def test_phase3_session_round_and_team_isolation(phase3_server):
    server, _ = phase3_server
    alpha = issue_phase3_session(server, "alice", "student", "team-alpha")
    beta = issue_phase3_session(server, "bob", "student", "team-beta")

    response, _, payload = phase3_request(server, "GET", "/api/rounds/round-1", token=alpha)
    assert response.status == 200
    assert payload["state"] == "open"
    assert payload["team_id"] == "team-alpha"

    response, _, payload = phase3_request(
        server, "PUT", "/api/rounds/round-1/draft", {"plan": VALID_PLAN}, token=alpha
    )
    assert response.status == 200
    assert payload["draft"]["payload"]["team_id"] == "team-alpha"

    response, _, payload = phase3_request(
        server, "GET", "/api/rounds/round-1/draft", token=beta
    )
    assert response.status == 200
    assert payload["draft"] is None

    response, _, payload = phase3_request(
        server, "GET", "/api/rounds/round-1/draft?team_id=team-alpha", token=beta
    )
    assert response.status == 403
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["request_id"]


def test_phase3_submission_is_idempotent_and_requires_bearer(phase3_server):
    server, _ = phase3_server
    token = issue_phase3_session(server, "alice", "student", "team-alpha")

    response, _, payload = phase3_request(
        server, "POST", "/api/rounds/round-1/submit", {"plan": VALID_PLAN}, token=token,
        idempotency_key="attempt-1",
    )
    assert response.status == 201
    first_id = payload["submission"]["submission_id"]
    response, _, payload = phase3_request(
        server, "POST", "/api/rounds/round-1/submit", {"plan": VALID_PLAN}, token=token,
        idempotency_key="attempt-1",
    )
    assert response.status == 200
    assert payload["submission"]["submission_id"] == first_id

    response, _, payload = phase3_request(server, "GET", "/api/rounds/round-1/submission")
    assert response.status == 401
    assert payload["error"]["code"] == "unauthorized"
    assert "token" not in json.dumps(payload).lower()


def test_phase3_instructor_evaluate_publish_leaderboard_and_audit(phase3_server):
    server, _ = phase3_server
    instructor = issue_phase3_session(server, "teacher", "instructor")
    student = issue_phase3_session(server, "alice", "student", "team-alpha")
    beta = issue_phase3_session(server, "bob", "student", "team-beta")
    phase3_request(
        server, "POST", "/api/rounds/round-1/submit", {"plan": VALID_PLAN}, token=student,
        idempotency_key="attempt-1",
    )
    beta_plan = dict(VALID_PLAN)
    beta_plan["team_id"] = "team-beta"
    phase3_request(
        server, "POST", "/api/rounds/round-1/submit", {"plan": beta_plan}, token=beta,
        idempotency_key="attempt-beta-1",
    )

    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds/round-1/evaluate", {}, token=instructor
    )
    assert response.status == 200, payload
    assert payload["state"] == "evaluated"
    response, _, payload = phase3_request(
        server, "GET", "/api/rounds/round-1/leaderboard", token=student
    )
    assert response.status == 200
    assert payload["published"] is False
    assert payload["results"] == []

    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds/round-1/transition",
        {"state": "published"}, token=instructor,
    )
    assert response.status == 200
    response, _, payload = phase3_request(
        server, "GET", "/api/rounds/round-1/leaderboard", token=student
    )
    assert response.status == 200
    assert payload["published"] is True
    assert payload["results"]

    response, _, payload = phase3_request(
        server, "GET", "/api/instructor/rounds/round-1/audit", token=instructor
    )
    assert response.status == 200
    assert payload["format_version"] == "phase3-audit-v1"
    response, _, replay = phase3_request(
        server, "POST", "/api/instructor/rounds/round-1/audit/replay", payload, token=instructor
    )
    assert response.status == 200
    assert replay["status"] == "complete"


def test_phase3_student_cannot_mutate_round_and_errors_are_structured(phase3_server):
    server, _ = phase3_server
    student = issue_phase3_session(server, "alice", "student", "team-alpha")
    response, _, payload = phase3_request(
        server, "POST", "/api/instructor/rounds/round-1/transition",
        {"state": "locked"}, token=student,
    )
    assert response.status == 403
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["request_id"]
    assert "Traceback" not in json.dumps(payload)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/session", b"{"),
        ("PUT", "/api/rounds/round-1/draft", b"{"),
        ("POST", "/api/rounds/round-1/submit", b"{"),
        ("POST", "/api/instructor/rounds/round-1/transition", b"{"),
        ("POST", "/api/instructor/rounds/round-1/evaluate", b"{"),
        ("POST", "/api/instructor/rounds/round-1/audit/replay", b"{"),
    ],
)
def test_phase3_malformed_json_returns_one_structured_response(phase3_server, method, path, body):
    server, _ = phase3_server
    token = None
    if "/instructor/" in path:
        token = issue_phase3_session(server, "teacher", "instructor")
    elif "/rounds/" in path:
        token = issue_phase3_session(server, "alice", "student", "team-alpha")
    response, raw, payload = phase3_request(server, method, path, body, token=token)
    assert response.status == 400
    assert payload["error"]["code"] == "malformed_json"
    assert payload["error"]["request_id"]
    assert raw.count(b"malformed_json") == 1


def test_phase3_rejects_team_id_spoofing_in_draft_and_submission(phase3_server):
    server, _ = phase3_server
    token = issue_phase3_session(server, "alice", "student", "team-alpha")
    spoofed = dict(VALID_PLAN)
    spoofed["team_id"] = "team-beta"
    for method, path in (("PUT", "/api/rounds/round-1/draft"), ("POST", "/api/rounds/round-1/submit")):
        response, _, payload = phase3_request(server, method, path, {"plan": spoofed}, token=token, idempotency_key="spoof-1")
        assert response.status == 403
        assert payload["error"]["code"] == "forbidden"


def test_phase3_bootstrap_requires_trusted_credential_and_revocation_is_strict(phase3_server):
    server, _ = phase3_server
    response, _, payload = phase3_request(server, "POST", "/api/session", {"actor_id": "teacher", "round_id": "round-1", "role": "instructor"}, include_bootstrap=False)
    assert response.status == 401
    assert payload["error"]["code"] == "unauthorized"
    token = issue_phase3_session(server, "alice", "student", "team-alpha")
    response, _, _ = phase3_request(server, "POST", "/api/session/revoke", token="bad-token")
    assert response.status == 401
    response, _, _ = phase3_request(server, "POST", "/api/session/revoke", token=token)
    assert response.status == 200
    response, _, _ = phase3_request(server, "POST", "/api/session/revoke", token=token)
    assert response.status == 401


def test_phase3_draft_post_is_structured_method_error_and_audit_replay_is_post_only(phase3_server):
    server, _ = phase3_server
    token = issue_phase3_session(server, "alice", "student", "team-alpha")
    response, _, payload = phase3_request(server, "POST", "/api/rounds/round-1/draft", {"plan": VALID_PLAN}, token=token)
    assert response.status == 405
    assert payload["error"]["code"] == "method_not_allowed"
    instructor = issue_phase3_session(server, "teacher", "instructor")
    response, _, payload = phase3_request(server, "GET", "/api/instructor/rounds/round-1/audit/replay", token=instructor)
    assert response.status == 405
    assert payload["error"]["code"] == "method_not_allowed"


def test_phase3_evaluation_retry_returns_same_stored_run_and_actor_is_audited(phase3_server):
    server, store = phase3_server
    instructor = issue_phase3_session(server, "teacher", "instructor")
    for team_id, actor_id, key in (("team-alpha", "alice", "a"), ("team-beta", "bob", "b")):
        token = issue_phase3_session(server, actor_id, "student", team_id)
        plan = dict(VALID_PLAN)
        plan["team_id"] = team_id
        phase3_request(server, "POST", "/api/rounds/round-1/submit", {"plan": plan}, token=token, idempotency_key=key)
    first = phase3_request(server, "POST", "/api/instructor/rounds/round-1/evaluate", {}, token=instructor)
    second = phase3_request(server, "POST", "/api/instructor/rounds/round-1/evaluate", {}, token=instructor)
    assert first[0].status == second[0].status == 200
    assert first[2]["evaluation_run_id"] == second[2]["evaluation_run_id"]
    assert any(event["actor_id"] == "teacher" for event in store.export_round_bundle("round-1")["audit_events"])


def test_phase3_private_leaderboard_only_exposes_requesting_team(phase3_server):
    server, _ = phase3_server
    instructor = issue_phase3_session(server, "teacher", "instructor")
    for team_id, actor_id, key in (("team-alpha", "alice", "a"), ("team-beta", "bob", "b")):
        token = issue_phase3_session(server, actor_id, "student", team_id)
        plan = dict(VALID_PLAN)
        plan["team_id"] = team_id
        phase3_request(server, "POST", "/api/rounds/round-1/submit", {"plan": plan}, token=token, idempotency_key=key)
    phase3_request(server, "POST", "/api/instructor/rounds/round-1/evaluate", {}, token=instructor)
    phase3_request(server, "POST", "/api/instructor/rounds/round-1/transition", {"state": "published"}, token=instructor)
    alpha = issue_phase3_session(server, "alice2", "student", "team-alpha")
    response, _, payload = phase3_request(server, "GET", "/api/rounds/round-1/leaderboard", token=alpha)
    assert response.status == 200
    assert [item["team_id"] for item in payload["results"]] == ["team-alpha"]


def test_phase3_concurrent_team_submissions_are_serialized(phase3_server):
    server, _ = phase3_server
    requests = []
    for team_id, actor_id, key in (("team-alpha", "alice", "a"), ("team-beta", "bob", "b")):
        token = issue_phase3_session(server, actor_id, "student", team_id)
        plan = dict(VALID_PLAN)
        plan["team_id"] = team_id
        requests.append((token, plan, key))

    def submit(item):
        token, plan, key = item
        return phase3_request(server, "POST", "/api/rounds/round-1/submit", {"plan": plan}, token=token, idempotency_key=key)[0].status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit, requests))
    assert sorted(statuses) == [201, 201]


def test_phase3_preserves_preloaded_in_memory_store(tmp_path):
    store = RoundStore()
    store.create_round(
        RoundRecord("memory-round", policy=RoundPolicy("ercot-small-week-01", "1", "0.3.0")),
        teams=("team-alpha",),
    )
    server = practice_server.create_server(
        scenario_path=FIXTURE, port=0, round_store=store, bootstrap_credential="test-bootstrap"
    )
    assert server.round_store is store
    assert server.round_store.get_round("memory-round") is not None
    server.server_close()


@pytest.mark.parametrize("path", ("/api/instructor/rounds/round-1/transition", "/api/instructor/rounds/round-1/evaluate"))
def test_phase3_unauthenticated_malformed_mutation_is_unauthorized(phase3_server, path):
    server, _ = phase3_server
    response, _, payload = phase3_request(server, "POST", path, b"{", include_bootstrap=False)
    assert response.status == 401
    assert payload["error"]["code"] == "unauthorized"
    assert payload["error"]["request_id"]


def test_phase3_mutation_reauthenticates_inside_lock(phase3_server, monkeypatch):
    server, _ = phase3_server
    token = issue_phase3_session(server, "alice", "student", "team-alpha")
    calls = []
    original = server.session_manager.authenticate

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(server.session_manager, "authenticate", counted)
    response, _, _ = phase3_request(server, "PUT", "/api/rounds/round-1/draft", {"plan": VALID_PLAN}, token=token)
    assert response.status == 200
    assert len(calls) >= 2


def test_phase3_unauthenticated_round_lookup_does_not_reveal_existence(phase3_server):
    server, _ = phase3_server
    responses = [
        phase3_request(server, "GET", "/api/rounds/round-1"),
        phase3_request(server, "GET", "/api/rounds/does-not-exist"),
    ]
    assert [response.status for response, _, _ in responses] == [401, 401]
    assert all(payload["error"]["code"] == "unauthorized" for _, _, payload in responses)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/instructor/rounds/round-1/audit/replay"),
        ("POST", "/api/rounds/round-1/draft"),
    ],
)
def test_phase3_unauthenticated_method_mismatch_is_unauthorized(phase3_server, method, path):
    server, _ = phase3_server
    response, _, payload = phase3_request(server, method, path, b"{", include_bootstrap=False)
    assert response.status == 401
    assert payload["error"]["code"] == "unauthorized"


def test_phase3_bootstrap_authenticates_before_parsing_body(phase3_server):
    server, _ = phase3_server
    response, _, payload = phase3_request(
        server, "POST", "/api/session", b"{", include_bootstrap=False
    )
    assert response.status == 401
    assert payload["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "method,path,token_kind,allowed",
    [
        ("GET", "/api/rounds/round-1/submit", "student", ["POST"]),
        ("PUT", "/api/instructor/rounds/round-1/evaluate", "instructor", ["POST"]),
        ("POST", "/api/instructor/rounds/round-1/audit", "instructor", ["GET"]),
    ],
)
def test_phase3_authenticated_route_mismatch_returns_structured_405(phase3_server, method, path, token_kind, allowed):
    server, _ = phase3_server
    token = issue_phase3_session(
        server,
        "teacher" if token_kind == "instructor" else "alice",
        token_kind,
        None if token_kind == "instructor" else "team-alpha",
    )
    response, _, payload = phase3_request(server, method, path, token=token)
    assert response.status == 405
    assert payload["error"]["code"] == "method_not_allowed"
    assert payload["error"]["allowed_methods"] == allowed
    assert payload["error"]["request_id"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/rounds/round-1/submit"),
        ("DELETE", "/api/rounds/round-1/submit"),
        ("PUT", "/api/instructor/rounds/round-1/evaluate"),
        ("POST", "/api/instructor/rounds/round-1/audit"),
        ("GET", "/api/session/revoke"),
        ("GET", "/api/session"),
    ],
)
def test_phase3_unauthenticated_route_mismatch_returns_401(phase3_server, method, path):
    server, _ = phase3_server
    response, _, payload = phase3_request(server, method, path, include_bootstrap=False)
    assert response.status == 401
    assert payload["error"]["code"] == "unauthorized"
    assert payload["error"]["request_id"]


@pytest.mark.parametrize("method", ("TRACE", "CONNECT", "BREW"))
def test_phase3_unknown_verbs_are_auth_first_on_protected_routes(phase3_server, method):
    server, _ = phase3_server
    unauthenticated = phase3_request(server, method, "/api/rounds/round-1/submit", include_bootstrap=False)
    assert unauthenticated[0].status == 401
    assert unauthenticated[2]["error"]["code"] == "unauthorized"
    token = issue_phase3_session(server, "alice", "student", "team-alpha")
    authenticated = phase3_request(server, method, "/api/rounds/round-1/submit", token=token)
    assert authenticated[0].status == 405
    assert authenticated[2]["error"]["code"] == "method_not_allowed"
    assert authenticated[2]["error"]["allowed_methods"] == ["POST"]
    assert authenticated[2]["error"]["request_id"]


def test_factory_supports_context_manager_and_ephemeral_port(monkeypatch):
    background_errors = []
    monkeypatch.setattr(threading, "excepthook", background_errors.append)
    threads = []
    for _ in range(25):
        with practice_server.server_context(scenario_path=FIXTURE, port=0) as server:
            assert server.server_address[1] != 0
            assert server.scenario.scenario_id == "ercot-small-week-01"
            thread = server._practice_server_thread
            threads.append(thread)

        assert not thread.is_alive()

    assert all(not thread.is_alive() for thread in threads)
    assert not background_errors


def test_context_does_not_yield_before_serve_forever_starts(monkeypatch):
    allow_serve = threading.Event()
    serve_called = threading.Event()
    context_entered = threading.Event()
    context_errors = []
    original_serve_forever = practice_server.PracticeHTTPServer.serve_forever

    def delayed_serve_forever(server, *args, **kwargs):
        serve_called.set()
        assert allow_serve.wait(timeout=2)
        return original_serve_forever(server, *args, **kwargs)

    monkeypatch.setattr(
        practice_server.PracticeHTTPServer,
        "serve_forever",
        delayed_serve_forever,
    )

    def enter_context():
        try:
            with practice_server.server_context(scenario_path=FIXTURE, port=0):
                context_entered.set()
        except BaseException as error:
            context_errors.append(error)

    context_thread = threading.Thread(target=enter_context, daemon=True)
    context_thread.start()
    try:
        assert serve_called.wait(timeout=2)
        assert not context_entered.wait(timeout=0.1)
    finally:
        allow_serve.set()

    context_thread.join(timeout=2)
    assert not context_thread.is_alive()
    assert not context_errors


def test_concurrent_health_and_evaluate_requests_are_safe(running_server):
    requests = [
        ("GET", "/api/health", None),
        ("POST", "/api/evaluate", {"plan": VALID_PLAN}),
    ] * 2

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda item: request(running_server, *item), requests)
        )

    assert [response.status for response, _, _ in responses].count(200) == len(requests)
