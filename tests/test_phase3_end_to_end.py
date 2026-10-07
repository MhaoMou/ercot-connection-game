from __future__ import annotations

import copy
import hashlib
import http.client
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ercot_game import practice_server
from ercot_game.multiteam import evaluate_locked_round, replay_audit_bundle
from ercot_game.round_models import RoundPolicy, RoundRecord, RoundState, TeamResultRecord, rank_results
from ercot_game.round_store import RoundStore
from ercot_game.io import scenario_from_dict


PROJECT_ROOT = Path(__file__).parents[1]
SCENARIO = PROJECT_ROOT / "data/fixtures/phase3_round.json"


def _request(server, method, path, body=None, token=None, *, bootstrap=True, bootstrap_credential="teacher-bootstrap", key=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if bootstrap:
        headers["X-Bootstrap-Credential"] = bootstrap_credential
    if key:
        headers["Idempotency-Key"] = key
    encoded = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, json.loads(raw)


def _issue(server, actor_id, role, team_id=None, round_id="week-1"):
    payload = {"actor_id": actor_id, "round_id": round_id, "role": role}
    if team_id is not None:
        payload["team_id"] = team_id
    status, result = _request(server, "POST", "/api/session", payload)
    assert status == 201, result
    return result["token"]


def _open(server, round_id="week-1", actor_id="teacher"):
    instructor = _issue(server, actor_id, "instructor", round_id=round_id)
    status, result = _request(
        server, "POST", f"/api/instructor/rounds/{round_id}/transition",
        {"state": "open"}, instructor, bootstrap=False,
    )
    assert status == 200, result
    return instructor


def _plan(team_id, *, invalid=False):
    plan = {
        "team_id": team_id,
        "connections": [{
            "connection_id": f"connection-{team_id}",
            "bus_id": "bus-shared",
            "path_corridors": ["corridor-shared"],
            "capacity_mw": 12.0,
            "profile": [1.0, 1.0],
        }],
        "generators": [],
        "intervention_budget_k": 0,
        "curtailment_depth_mu": 0.0,
        "flexibility_fee_per_mwh": 0.0,
    }
    if invalid:
        plan["connections"][0]["bus_id"] = "does-not-exist"
    return plan


@pytest.fixture
def classroom_server(tmp_path):
    clock_now = [datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)]
    store = RoundStore(tmp_path / "classroom.sqlite", clock=lambda: clock_now[0])
    store.create_round(
        RoundRecord(
            "week-1",
            policy=RoundPolicy(
                "phase3-minimal-round", "1", "0.3.0",
                visibility="private", policy_version="phase3-canonical-v1", seed=17,
            ),
            created_at=clock_now[0],
        ),
        teams=("team-alpha", "team-bravo", "team-invalid"),
    )
    scenario_path = tmp_path / "phase3-scenario.json"
    scenario_path.write_text(json.dumps(json.loads(SCENARIO.read_text(encoding="utf-8"))["scenario"]), encoding="utf-8")
    server = practice_server.create_server(
        scenario_path=scenario_path, port=0, round_store=store,
        bootstrap_credential="teacher-bootstrap",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, store, clock_now
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_instructor_opens_round_registers_teams_and_issues_scoped_sessions(classroom_server):
    server, store, _ = classroom_server
    assert store.get_round("week-1").state is RoundState.DRAFT
    assert store.list_teams("week-1") == ("team-alpha", "team-bravo", "team-invalid")
    instructor = _open(server)
    alpha = _issue(server, "alice", "student", "team-alpha")
    assert instructor and alpha
    status, round_view = _request(server, "GET", "/api/rounds/week-1", token=alpha, bootstrap=False)
    assert status == 200
    assert round_view["team_id"] == "team-alpha"
    assert round_view["state"] == "open"
    status, invalid_transition = _request(
        server, "POST", "/api/instructor/rounds/week-1/transition",
        {"state": "open"}, instructor, bootstrap=False,
    )
    assert status == 409
    assert invalid_transition["error"]["code"] == "invalid_transition"


def test_students_save_drafts_submit_immutable_plans_and_retries_are_idempotent(classroom_server):
    server, store, _ = classroom_server
    _open(server)
    alpha = _issue(server, "alice", "student", "team-alpha")
    plan = _plan("team-alpha")
    status, draft = _request(server, "PUT", "/api/rounds/week-1/draft", {"plan": plan, "revision": 1}, alpha, bootstrap=False)
    assert status == 200 and draft["draft"]["payload"] == plan
    status, submitted = _request(server, "POST", "/api/rounds/week-1/submit", {"plan": plan}, alpha, bootstrap=False, key="alpha-submit")
    assert status == 201, (submitted, store.get_round("week-1"), store._clock_now())
    retry_status, retry = _request(server, "POST", "/api/rounds/week-1/submit", {"plan": plan}, alpha, bootstrap=False, key="alpha-submit")
    assert retry_status == 200 and retry == submitted
    conflict_status, conflict = _request(
        server, "POST", "/api/rounds/week-1/submit",
        {"plan": {**plan, "capacity_mw": 11.0}}, alpha,
        bootstrap=False, key="alpha-submit",
    )
    assert conflict_status == 409
    assert conflict["error"]["code"] == "duplicate_submission"
    bravo = _issue(server, "bob", "student", "team-bravo")
    cross_team_status, cross_team = _request(
        server, "POST", "/api/rounds/week-1/submit", {"plan": _plan("team-bravo")},
        bravo, bootstrap=False, key="alpha-submit",
    )
    assert cross_team_status == 409
    assert cross_team["error"]["code"] == "duplicate_submission"
    with pytest.raises(sqlite3.DatabaseError):
        store.connection.execute("UPDATE submissions SET payload_json = '{}' WHERE team_id = 'team-alpha'")
    assert store.get_team_submission("week-1", "team-alpha").payload == plan


def test_deadline_and_lock_reject_writes_and_invalid_plan_gets_official_zero(classroom_server):
    server, store, _ = classroom_server
    _open(server)
    invalid = _issue(server, "ivan", "student", "team-invalid")
    status, submitted = _request(server, "POST", "/api/rounds/week-1/submit", {"plan": _plan("team-invalid", invalid=True)}, invalid, bootstrap=False, key="invalid")
    assert status == 201, submitted
    deadline_at = classroom_server[2][0] - timedelta(seconds=1)
    store.create_round(
        RoundRecord(
            "deadline-round",
            policy=RoundPolicy("scenario", "1", "0.3.0", deadline_at=deadline_at),
            created_at=deadline_at - timedelta(minutes=5),
        ),
        teams=("team-invalid",),
    )
    _open(server, "deadline-round", "deadline-teacher")
    late_student = _issue(server, "late-student", "student", "team-invalid", "deadline-round")
    late_status, late_payload = _request(
        server, "POST", "/api/rounds/deadline-round/submit",
        {"plan": _plan("team-invalid", invalid=True)}, late_student,
        bootstrap=False, key="late-submit",
    )
    assert late_status == 409
    assert late_payload["error"]["code"] == "deadline_passed"
    assert store.get_round("deadline-round").state is RoundState.OPEN
    instructor = _issue(server, "teacher-2", "instructor")
    lock_status, lock_result = _request(
        server, "POST", "/api/instructor/rounds/week-1/transition",
        {"state": "locked"}, instructor, bootstrap=False,
    )
    assert lock_status == 200, lock_result
    post_lock_draft_status, post_lock_draft = _request(
        server, "PUT", "/api/rounds/week-1/draft",
        {"plan": _plan("team-invalid", invalid=True)}, invalid, bootstrap=False,
    )
    assert post_lock_draft_status == 409
    assert post_lock_draft["error"]["code"] == "round_not_open"
    post_lock_submit_status, post_lock_submit = _request(
        server, "POST", "/api/rounds/week-1/submit",
        {"plan": _plan("team-invalid", invalid=True)}, invalid,
        bootstrap=False, key="after-lock",
    )
    assert post_lock_submit_status == 409
    assert post_lock_submit["error"]["code"] == "round_not_open"
    assert store.get_round("week-1").state is RoundState.LOCKED
    result = evaluate_locked_round(scenario_from_dict(json.loads(SCENARIO.read_text())["scenario"]), [{"team_id": "team-invalid", "payload": _plan("team-invalid", invalid=True)}])
    assert result["ranked_results"][0]["official_revenue"] == 0.0
    assert result["ranked_results"][0]["validation"]["valid"] is False


def test_shared_resource_allocation_and_ranking_are_canonical_under_submission_reordering():
    data = json.loads(SCENARIO.read_text(encoding="utf-8"))
    scenario = scenario_from_dict(data["scenario"])
    forward = evaluate_locked_round(scenario, data["submissions"], policy_version=data["policy_version"], seed=data["seed"])
    reverse = evaluate_locked_round(scenario, list(reversed(data["submissions"])), policy_version=data["policy_version"], seed=data["seed"])
    assert forward == reverse
    assert forward["input_hash"] == reverse["input_hash"]
    assert forward["ranked_results"] == reverse["ranked_results"]
    assert [(item["team_id"], item["rank"]) for item in forward["ranked_results"]] == [(item["team_id"], item["rank"]) for item in reverse["ranked_results"]]
    for first, second in zip(forward["ranked_results"], reverse["ranked_results"]):
        assert first["team_id"] == second["team_id"]
        assert first["rank"] == second["rank"]
        assert first["official_revenue"] == second["official_revenue"]
        assert first["evaluator_result"] == second["evaluator_result"] if not first["validation"]["valid"] else True
        if first["validation"]["valid"]:
            assert first["evaluator_result"]["allocation"] == second["evaluator_result"]["allocation"]
            assert first["evaluator_result"]["score_breakdown"] == second["evaluator_result"]["score_breakdown"]
            assert first["evaluator_result"]["diagnostics"] == second["evaluator_result"]["diagnostics"]
    valid = [item for item in forward["ranked_results"] if item["validation"]["valid"]]
    assert sum(item["evaluator_result"]["allocation"]["allocated_capacity_mw"] for item in valid) <= 35.0
    by_team = {item["team_id"]: item for item in forward["ranked_results"]}
    assert by_team["team-bravo"]["evaluator_result"]["allocation"] == {
        "allocated_capacity_mw": 9.0,
        "binding_resources": ["bus:bus-shared"],
        "resource_ratio_by_time": [pytest.approx(5 / 6), 0.75],
    }
    assert by_team["team-bravo"]["official_revenue"] == pytest.approx(
        by_team["team-bravo"]["evaluator_result"]["score_breakdown"]["total"]
    )
    assert by_team["team-invalid"]["official_revenue"] == 0.0
    assert [(item["team_id"], item["rank"]) for item in forward["ranked_results"]] == [
        ("team-bravo", 1), ("team-alpha", 2), ("team-invalid", 3)
    ]
    tied = rank_results((TeamResultRecord("team-z", 10.0), TeamResultRecord("team-a", 10.0)), "default", None)
    assert [(item.team_id, item.rank) for item in tied] == [("team-a", 1), ("team-z", 1)]


def test_instructor_evaluates_publishes_retracts_and_private_visibility_filters_results(classroom_server):
    server, store, _ = classroom_server
    instructor = _open(server)
    alpha = _issue(server, "alice", "student", "team-alpha")
    bravo = _issue(server, "bob", "student", "team-bravo")
    invalid = _issue(server, "ivan", "student", "team-invalid")
    for token, team, key, is_invalid in ((alpha, "team-alpha", "a", False), (bravo, "team-bravo", "b", False), (invalid, "team-invalid", "i", True)):
        response = _request(server, "POST", "/api/rounds/week-1/submit", {"plan": _plan(team, invalid=is_invalid)}, token, bootstrap=False, key=key)
        assert response[0] == 201, response[1]
    evaluation = _request(server, "POST", "/api/instructor/rounds/week-1/evaluate", {}, instructor, bootstrap=False)
    assert evaluation[0] == 200, evaluation[1]
    assert _request(server, "POST", "/api/instructor/rounds/week-1/transition", {"state": "published"}, instructor, bootstrap=False)[0] == 200
    student_status, student_board = _request(server, "GET", "/api/rounds/week-1/leaderboard", token=alpha, bootstrap=False)
    instructor_status, instructor_board = _request(server, "GET", "/api/rounds/week-1/leaderboard", token=instructor, bootstrap=False)
    assert student_status == instructor_status == 200
    assert [row["team_id"] for row in student_board["results"]] == ["team-alpha"]
    assert all(set(row) == {"team_id", "rank", "authoritative_total", "tie_group"} for row in student_board["results"])
    assert all("plan" not in row and "diagnostics" not in row for row in student_board["results"])
    assert "team-bravo" not in json.dumps(student_board)
    assert {row["team_id"] for row in instructor_board["results"]} == {"team-alpha", "team-bravo", "team-invalid"}
    assert next(row for row in instructor_board["results"] if row["team_id"] == "team-invalid")["authoritative_total"] == 0.0
    assert _request(server, "POST", "/api/instructor/rounds/week-1/transition", {"state": "retracted"}, instructor, bootstrap=False)[0] == 200
    assert _request(server, "GET", "/api/rounds/week-1/leaderboard", token=alpha, bootstrap=False)[1]["published"] is False
    assert store.get_round("week-1").state is RoundState.RETRACTED


def test_public_and_aggregate_visibility_filter_only_the_supported_leaderboard_fields(classroom_server):
    server, store, _ = classroom_server
    for round_id, visibility in (("public-week", "public"), ("aggregate-week", "aggregate")):
        store.create_round(
            RoundRecord(
                round_id,
                policy=RoundPolicy("phase3-minimal-round", "1", "0.3.0", visibility=visibility, policy_version=round_id),
            ),
            teams=("team-alpha", "team-bravo"),
        )
        instructor = _open(server, round_id, f"{round_id}-teacher")
        students = [
            (_issue(server, f"{round_id}-alice", "student", "team-alpha", round_id), "team-alpha", "a"),
            (_issue(server, f"{round_id}-bob", "student", "team-bravo", round_id), "team-bravo", "b"),
        ]
        for token, team, key in students:
            status, response = _request(
                server, "POST", f"/api/rounds/{round_id}/submit", {"plan": _plan(team)},
                token, bootstrap=False, key=f"{round_id}-{key}",
            )
            assert status == 201, response
            assert response["submission"]["team_id"] == team
        assert _request(server, "POST", f"/api/instructor/rounds/{round_id}/evaluate", {}, instructor, bootstrap=False)[0] == 200
        assert _request(server, "POST", f"/api/instructor/rounds/{round_id}/transition", {"state": "published"}, instructor, bootstrap=False)[0] == 200
        status, board = _request(server, "GET", f"/api/rounds/{round_id}/leaderboard", token=students[0][0], bootstrap=False)
        assert status == 200 and board["published"] is True
        if visibility == "public":
            assert {row["team_id"] for row in board["results"]} == {"team-alpha", "team-bravo"}
            assert all(set(row) == {"team_id", "rank", "authoritative_total", "tie_group"} for row in board["results"])
        else:
            assert board["results"] == [{"team_count": 2}]


def test_audit_export_replay_and_tamper_detection_are_available_to_instructor(classroom_server):
    server, _, _ = classroom_server
    instructor = _open(server)
    alpha = _issue(server, "alice", "student", "team-alpha")
    bravo = _issue(server, "bob", "student", "team-bravo")
    invalid = _issue(server, "ivan", "student", "team-invalid")
    submission_responses = []
    for token, team, key, is_invalid in ((alpha, "team-alpha", "a", False), (bravo, "team-bravo", "b", False), (invalid, "team-invalid", "i", True)):
        response = _request(server, "POST", "/api/rounds/week-1/submit", {"plan": _plan(team, invalid=is_invalid)}, token, bootstrap=False, key=key)
        assert response[0] == 201, response[1]
        assert response[1]["submission"]["team_id"] == team
        assert response[1]["submission"]["idempotency_key"] == key
        submission_responses.append(response[1]["submission"])
    first_evaluation_status, first_evaluation = _request(server, "POST", "/api/instructor/rounds/week-1/evaluate", {}, instructor, bootstrap=False)
    assert first_evaluation_status == 200
    event_count = len(server.round_store.export_round_bundle("week-1")["audit_events"])
    retry_status, retry_evaluation = _request(server, "POST", "/api/instructor/rounds/week-1/evaluate", {}, instructor, bootstrap=False)
    assert retry_status == 200
    assert retry_evaluation["idempotent"] is True
    assert retry_evaluation["evaluation_run_id"] == first_evaluation["evaluation_run_id"]
    assert retry_evaluation["input_hash"] == first_evaluation["input_hash"]
    assert len(server.round_store.export_round_bundle("week-1")["audit_events"]) == event_count
    status, bundle = _request(server, "GET", "/api/instructor/rounds/week-1/audit", token=instructor, bootstrap=False)
    assert status == 200 and bundle["metadata"]["evaluator_version"] == "0.3.0"
    assert {item["team_id"] for item in bundle["batch_input"]["submissions"]} == {"team-alpha", "team-bravo", "team-invalid"}
    assert next(item for item in bundle["results"] if item["team_id"] == "team-invalid")["official_revenue"] == 0.0
    replay_status, replay = _request(server, "POST", "/api/instructor/rounds/week-1/audit/replay", bundle, instructor, bootstrap=False)
    assert replay_status == 200 and replay["output_hash"] == bundle["metadata"]["output_hash"]
    tampered = copy.deepcopy(bundle)
    tampered["batch_input"]["seed"] = 999
    assert _request(server, "POST", "/api/instructor/rounds/week-1/audit/replay", tampered, instructor, bootstrap=False)[0] == 422
    tamper_cases = []
    scenario_tampered = copy.deepcopy(bundle)
    scenario_tampered["scenario"]["scenario_id"] = "tampered"
    tamper_cases.append(scenario_tampered)
    policy_tampered = copy.deepcopy(bundle)
    policy_tampered["metadata"]["policy_version"] = "tampered"
    tamper_cases.append(policy_tampered)
    submission_tampered = copy.deepcopy(bundle)
    submission_tampered["batch_input"]["submissions"][0]["team_id"] = "tampered"
    tamper_cases.append(submission_tampered)
    results_tampered = copy.deepcopy(bundle)
    results_tampered["results"][0]["official_revenue"] += 1.0
    tamper_cases.append(results_tampered)
    output_hash_tampered = copy.deepcopy(bundle)
    output_hash_tampered["metadata"]["output_hash"] = "0" * 64
    tamper_cases.append(output_hash_tampered)
    assert replay["ranked_results"] == bundle["results"]
    for tampered_bundle in tamper_cases:
        tamper_status, tamper_response = _request(
            server, "POST", "/api/instructor/rounds/week-1/audit/replay",
            tampered_bundle, instructor, bootstrap=False,
        )
        assert tamper_status == 422
        assert tamper_response["error"]["code"] == "validation_failed"
        with pytest.raises(ValueError):
            replay_audit_bundle(tampered_bundle)


@pytest.mark.parametrize("path", ["/api/rounds/week-2", "/api/rounds/week-1?team_id=team-bravo"])
def test_unauthorized_cross_team_and_cross_round_access_returns_structured_errors(classroom_server, path):
    server, _, _ = classroom_server
    _open(server)
    alpha = _issue(server, "alice", "student", "team-alpha")
    status, payload = _request(server, "GET", path, token=alpha, bootstrap=False)
    assert status == 403
    assert payload["error"]["code"] == "forbidden"
    assert "Traceback" not in json.dumps(payload)


def test_bootstrap_and_bearer_failures_are_exact_structured_401s(classroom_server):
    server, _, _ = classroom_server
    status, payload = _request(
        server, "POST", "/api/session",
        {"actor_id": "teacher", "round_id": "week-1", "role": "instructor"},
        bootstrap=False,
    )
    assert status == 401 and payload["error"]["code"] == "unauthorized"
    status, payload = _request(
        server, "POST", "/api/session",
        {"actor_id": "teacher", "round_id": "week-1", "role": "instructor"},
        bootstrap_credential="wrong-bootstrap",
    )
    assert status == 401 and payload["error"]["code"] == "unauthorized"
    status, payload = _request(server, "GET", "/api/rounds/week-1", bootstrap=False)
    assert status == 401 and payload["error"]["code"] == "unauthorized"
    _open(server)
    student = _issue(server, "alice", "student", "team-alpha")
    for method, path, body in (
        ("POST", "/api/instructor/rounds/week-1/transition", {"state": "locked"}),
        ("POST", "/api/instructor/rounds/week-1/evaluate", {}),
        ("GET", "/api/instructor/rounds/week-1/audit", None),
    ):
        status, role_error = _request(server, method, path, body, student, bootstrap=False)
        assert status == 403
        assert role_error["error"]["code"] == "forbidden"


def test_weekly_operation_uses_http_rounds_and_survives_service_restart(tmp_path):
    data = json.loads(SCENARIO.read_text(encoding="utf-8"))
    scenario = scenario_from_dict(data["scenario"])
    database_path = tmp_path / "month.sqlite"
    # Keep normal weekly writes ahead of their deadlines even when the HTTP
    # server reopens this file-backed store with its default wall clock.
    fixture_now = [datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)]
    store = RoundStore(database_path, clock=lambda: fixture_now[0])
    scenario_path = tmp_path / "phase3-scenario.json"
    scenario_path.write_text(json.dumps(data["scenario"]), encoding="utf-8")
    rounds = []
    for week in range(4):
        round_id = f"week-{week + 1}"
        policy_version = f"{data['policy_version']}-week-{week + 1}"
        visibility = ("public", "aggregate", "private", "public")[week]
        deadline_at = fixture_now[0] + timedelta(days=week + 1)
        store.create_round(
            RoundRecord(
                round_id,
                policy=RoundPolicy(
                    "phase3-minimal-round", "1", "0.3.0",
                    policy_version=policy_version, deadline_at=deadline_at,
                    visibility=visibility, seed=data["seed"],
                ),
                created_at=fixture_now[0],
            ),
            teams=("team-alpha", "team-bravo", "team-invalid"),
        )
        rounds.append((round_id, policy_version, visibility, deadline_at))

    server = practice_server.create_server(
        scenario_path=scenario_path, port=0, round_store=store,
        bootstrap_credential="teacher-bootstrap",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    expected_hashes = []
    auth_by_round = {}
    try:
        for week, (round_id, policy_version, visibility, deadline_at) in enumerate(rounds):
            instructor = _open(server, round_id, f"teacher-{round_id}")
            alpha = _issue(server, f"alice-{round_id}", "student", "team-alpha", round_id)
            bravo = _issue(server, f"bob-{round_id}", "student", "team-bravo", round_id)
            invalid = _issue(server, f"ivan-{round_id}", "student", "team-invalid", round_id)
            auth_by_round[round_id] = (instructor, alpha)
            students = ((alpha, "team-alpha", False), (bravo, "team-bravo", False), (invalid, "team-invalid", True))
            for token, team, is_invalid in students:
                plan = _plan(team, invalid=is_invalid)
                if team == "team-alpha":
                    plan["flexibility_fee_per_mwh"] = float(week)
                draft_status, draft_response = _request(
                    server, "PUT", f"/api/rounds/{round_id}/draft",
                    {"plan": plan, "revision": 1}, token, bootstrap=False,
                )
                assert draft_status == 200, draft_response
                assert draft_response["draft"]["payload"] == plan
                draft_read_status, draft_read = _request(
                    server, "GET", f"/api/rounds/{round_id}/draft",
                    token=token, bootstrap=False,
                )
                assert draft_read_status == 200
                assert draft_read["draft"]["payload"] == plan
                key = f"{round_id}-{team}"
                status, response = _request(server, "POST", f"/api/rounds/{round_id}/submit", {"plan": plan}, token, bootstrap=False, key=key)
                assert status == 201, response
                assert response["submission"]["team_id"] == team
                retry_status, retry_response = _request(server, "POST", f"/api/rounds/{round_id}/submit", {"plan": plan}, token, bootstrap=False, key=key)
                assert retry_status == 200 and retry_response == response
                assert _request(server, "GET", f"/api/rounds/{round_id}", token=token, bootstrap=False)[0] == 200
            deadline_status, round_payload = _request(server, "GET", f"/api/rounds/{round_id}", token=alpha, bootstrap=False)
            assert deadline_status == 200
            assert round_payload["policy"]["deadline_at"] == deadline_at.isoformat()
            conflict_status, conflict = _request(
                server, "POST", f"/api/rounds/{round_id}/submit",
                {"plan": {**_plan("team-alpha"), "capacity_mw": 11.0}}, alpha,
                bootstrap=False, key=f"{round_id}-team-alpha",
            )
            assert conflict_status == 409 and conflict["error"]["code"] == "duplicate_submission"
            before_late = server.round_store.export_round_bundle(round_id)
            store.connection.execute(
                "UPDATE rounds SET deadline_at = ? WHERE round_id = ?",
                ("2020-01-01T00:00:00Z", round_id),
            )
            late_status, late_response = _request(
                server, "POST", f"/api/rounds/{round_id}/submit",
                {"plan": _plan("team-alpha")}, alpha,
                bootstrap=False, key=f"{round_id}-late-submit",
            )
            assert late_status == 409
            assert late_response["error"]["code"] == "deadline_passed"
            after_late = server.round_store.export_round_bundle(round_id)
            assert after_late["round"]["state"] == "open"
            assert after_late["submissions"] == before_late["submissions"]
            assert _request(server, "GET", f"/api/rounds/{round_id}", bootstrap=False)[0] == 401
            cross_team_status, cross_team = _request(server, "GET", f"/api/rounds/{round_id}?team_id=team-bravo", token=alpha, bootstrap=False)
            assert cross_team_status == 403 and cross_team["error"]["code"] == "forbidden"
            other_round_id = rounds[week - 1][0] if week else "not-this-week"
            cross_round_status, cross_round = _request(server, "GET", f"/api/rounds/{other_round_id}", token=alpha, bootstrap=False)
            assert cross_round_status == 403 and cross_round["error"]["code"] == "forbidden"
            evaluate_status, evaluate_response = _request(server, "POST", f"/api/instructor/rounds/{round_id}/evaluate", {}, instructor, bootstrap=False)
            assert evaluate_status == 200, evaluate_response
            pre_publish_boards = [
                _request(server, "GET", f"/api/rounds/{round_id}/leaderboard", token=token, bootstrap=False)
                for token in (alpha, bravo, instructor)
            ]
            assert all(status == 200 and board == {"published": False, "results": []} for status, board in pre_publish_boards)
            publish_status, publish_response = _request(server, "POST", f"/api/instructor/rounds/{round_id}/transition", {"state": "published"}, instructor, bootstrap=False)
            assert publish_status == 200, publish_response
            student_boards = [_request(server, "GET", f"/api/rounds/{round_id}/leaderboard", token=token, bootstrap=False)[1] for token, _, _ in students[:2]]
            instructor_board = _request(server, "GET", f"/api/rounds/{round_id}/leaderboard", token=instructor, bootstrap=False)[1]
            if visibility == "public":
                assert all({row["team_id"] for row in board["results"]} == {"team-alpha", "team-bravo", "team-invalid"} for board in student_boards)
                assert {row["team_id"] for row in instructor_board["results"]} == {"team-alpha", "team-bravo", "team-invalid"}
            elif visibility == "aggregate":
                assert all(board["results"] == [{"team_count": 3}] for board in student_boards), student_boards
                assert instructor_board["results"] == [{"team_count": 3}], instructor_board
            else:
                assert [row["team_id"] for row in student_boards[0]["results"]] == ["team-alpha"]
                assert [row["team_id"] for row in student_boards[1]["results"]] == ["team-bravo"]
                assert {row["team_id"] for row in instructor_board["results"]} == {"team-alpha", "team-bravo", "team-invalid"}
            audit_status, bundle = _request(server, "GET", f"/api/instructor/rounds/{round_id}/audit", token=instructor, bootstrap=False)
            assert audit_status == 200
            replay_status, replay = _request(server, "POST", f"/api/instructor/rounds/{round_id}/audit/replay", bundle, instructor, bootstrap=False)
            assert replay_status == 200
            assert replay["output_hash"] == bundle["metadata"]["output_hash"]
            assert replay["ranked_results"] == bundle["results"]
            persisted = server.round_store.export_round_bundle(round_id)
            assert len(persisted["submissions"]) == 3
            assert any(event["action"] == "round.lock" for event in persisted["audit_events"])
            assert {item["team_id"] for item in bundle["batch_input"]["submissions"]} == {"team-alpha", "team-bravo", "team-invalid"}
            audit_hash = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
            expected_hashes.append((bundle["metadata"]["input_hash"], bundle["metadata"]["output_hash"], audit_hash, bundle["results"]))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        store.connection.close()

    reopened = RoundStore(database_path)
    for index, (round_id, _, _, _) in enumerate(rounds):
        persisted = reopened.export_round_bundle(round_id)
        assert persisted["round"]["state"] == "published"
        assert len(persisted["submissions"]) == 3
        assert len(persisted["team_results"]) == 3
        persisted_bundle = next(event["metadata"]["bundle"] for event in persisted["audit_events"] if event["action"] == "evaluation.artifact")
        replayed = replay_audit_bundle(persisted_bundle)
        persisted_audit_hash = hashlib.sha256(json.dumps(persisted_bundle, sort_keys=True).encode()).hexdigest()
        assert (replayed["input_hash"], replayed["output_hash"], persisted_audit_hash, list(replayed["ranked_results"])) == expected_hashes[index]
        assert any(event["action"] == "round.lock" for event in persisted["audit_events"])
    assert len({item[0] for item in expected_hashes}) == 4
    assert len({item[1] for item in expected_hashes}) == 4
    assert len({item[2] for item in expected_hashes}) == 4

    restarted_server = practice_server.create_server(
        scenario_path=scenario_path, port=0, round_store=reopened,
        bootstrap_credential="teacher-bootstrap",
    )
    restarted_thread = threading.Thread(target=restarted_server.serve_forever, daemon=True)
    restarted_thread.start()
    try:
        for index, (round_id, _, visibility, _) in enumerate(rounds):
            instructor, alpha = auth_by_round[round_id]
            status, round_view = _request(restarted_server, "GET", f"/api/rounds/{round_id}", token=instructor, bootstrap=False)
            assert status == 200 and round_view["state"] == "published"
            submission_status, submission = _request(restarted_server, "GET", f"/api/rounds/{round_id}/submission", token=alpha, bootstrap=False)
            assert submission_status == 200 and submission["submission"]["team_id"] == "team-alpha"
            student_tokens = [alpha, _issue(restarted_server, f"bob-restart-{round_id}", "student", "team-bravo", round_id)]
            student_boards = [_request(restarted_server, "GET", f"/api/rounds/{round_id}/leaderboard", token=token, bootstrap=False)[1] for token in student_tokens]
            instructor_board_status, instructor_board = _request(restarted_server, "GET", f"/api/rounds/{round_id}/leaderboard", token=instructor, bootstrap=False)
            assert instructor_board_status == 200
            if visibility == "public":
                assert all({row["team_id"] for row in board["results"]} == {"team-alpha", "team-bravo", "team-invalid"} for board in student_boards)
                assert {row["team_id"] for row in instructor_board["results"]} == {"team-alpha", "team-bravo", "team-invalid"}
            elif visibility == "aggregate":
                assert all(board["results"] == [{"team_count": 3}] for board in student_boards), student_boards
                assert instructor_board["results"] == [{"team_count": 3}], instructor_board
            else:
                assert [row["team_id"] for row in student_boards[0]["results"]] == ["team-alpha"]
                assert [row["team_id"] for row in student_boards[1]["results"]] == ["team-bravo"]
                assert {row["team_id"] for row in instructor_board["results"]} == {"team-alpha", "team-bravo", "team-invalid"}
            audit_status, bundle = _request(restarted_server, "GET", f"/api/instructor/rounds/{round_id}/audit", token=instructor, bootstrap=False)
            assert audit_status == 200
            assert bundle["metadata"]["input_hash"] == expected_hashes[index][0]
            replay_status, replay = _request(restarted_server, "POST", f"/api/instructor/rounds/{round_id}/audit/replay", bundle, instructor, bootstrap=False)
            assert replay_status == 200
            assert replay["output_hash"] == expected_hashes[index][1]
            assert replay["ranked_results"] == expected_hashes[index][3]
            retract_status, retract_response = _request(restarted_server, "POST", f"/api/instructor/rounds/{round_id}/transition", {"state": "retracted"}, instructor, bootstrap=False)
            assert retract_status == 200, retract_response
            participant_tokens = [alpha, student_tokens[1], instructor]
            hidden_boards = [_request(restarted_server, "GET", f"/api/rounds/{round_id}/leaderboard", token=token, bootstrap=False) for token in participant_tokens]
            assert all(status == 200 and board == {"published": False, "results": []} for status, board in hidden_boards)
            retained_status, retained = _request(restarted_server, "GET", f"/api/instructor/rounds/{round_id}/audit", token=instructor, bootstrap=False)
            assert retained_status == 200 and retained["results"] == expected_hashes[index][3]
    finally:
        restarted_server.shutdown()
        restarted_server.server_close()
        restarted_thread.join(timeout=2)
