from __future__ import annotations

import json
import hashlib
import http.client
from pathlib import Path
import threading

import pytest

from ercot_game.evaluation_jobs import create_local_job, run_local_job
from ercot_game.io import scenario_from_dict
from ercot_game import practice_server
from ercot_game.round_models import RoundPolicy, RoundRecord, RoundState
from ercot_game.round_store import RoundStore
from ercot_game.remote_jobs import RemoteJobError, RemoteJobStatus, RemoteJobDispatcher


FIXTURE = Path(__file__).parents[1] / "data/fixtures/phase3_round.json"


class FakeTransport:
    def __init__(self) -> None:
        self.statuses: dict[str, RemoteJobStatus] = {}
        self.artifacts: dict[str, bytes] = {}
        self.submissions: list[Path] = []
        self.cancellations: list[str] = []

    def submit(self, package_path: Path) -> str:
        remote_id = f"remote-{len(self.submissions) + 1}"
        self.submissions.append(package_path)
        self.statuses[remote_id] = RemoteJobStatus.QUEUED
        return remote_id

    def status(self, remote_job_id: str) -> RemoteJobStatus:
        return self.statuses[remote_job_id]

    def fetch_artifact(self, remote_job_id: str) -> bytes:
        return self.artifacts[remote_job_id]

    def cancel(self, remote_job_id: str) -> RemoteJobStatus:
        self.cancellations.append(remote_job_id)
        self.statuses[remote_job_id] = RemoteJobStatus.CANCELLED
        return self.statuses[remote_job_id]


def make_package(tmp_path: Path) -> Path:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scenario = scenario_from_dict(data["scenario"])
    package = create_local_job(
        tmp_path / "packages",
        scenario,
        data["submissions"],
        round_id="remote-job-round",
        job_id="job-1",
        policy_version=data["policy_version"],
        seed=data["seed"],
    )
    return package.path


def test_dispatcher_polls_and_ingests_verified_artifact_idempotently(tmp_path):
    package_path = make_package(tmp_path)
    transport = FakeTransport()
    dispatcher = RemoteJobDispatcher(tmp_path / "dispatch.json", transport)

    submitted = dispatcher.submit(package_path)
    assert submitted.status is RemoteJobStatus.QUEUED
    assert submitted.attempt == 1

    transport.statuses[submitted.remote_job_id] = RemoteJobStatus.RUNNING
    assert dispatcher.poll(submitted.job_id).status is RemoteJobStatus.RUNNING

    artifact = run_local_job(package_path)
    transport.artifacts[submitted.remote_job_id] = (package_path / "artifact.json").read_bytes()
    transport.statuses[submitted.remote_job_id] = RemoteJobStatus.COMPLETE

    completed = dispatcher.poll(submitted.job_id)
    assert completed.status is RemoteJobStatus.COMPLETE
    assert completed.output_hash == artifact["output_hash"]
    assert completed.artifact_path is not None
    assert json.loads(completed.artifact_path.read_text()) == artifact
    assert dispatcher.poll(submitted.job_id) == completed


def test_dispatcher_retries_retryable_failure_and_stops_after_limit(tmp_path):
    package_path = make_package(tmp_path)
    transport = FakeTransport()
    dispatcher = RemoteJobDispatcher(tmp_path / "dispatch.json", transport, max_attempts=2)

    first = dispatcher.submit(package_path)
    transport.statuses[first.remote_job_id] = RemoteJobStatus.RETRYABLE_FAILED
    retried = dispatcher.poll(first.job_id)
    assert retried.status is RemoteJobStatus.QUEUED
    assert retried.attempt == 2
    assert retried.remote_job_id == "remote-2"

    transport.statuses[retried.remote_job_id] = RemoteJobStatus.RETRYABLE_FAILED
    failed = dispatcher.poll(first.job_id)
    assert failed.status is RemoteJobStatus.TERMINAL_FAILED
    assert failed.attempt == 2


def test_dispatcher_cancel_is_idempotent_and_terminal(tmp_path):
    package_path = make_package(tmp_path)
    transport = FakeTransport()
    dispatcher = RemoteJobDispatcher(tmp_path / "dispatch.json", transport)
    submitted = dispatcher.submit(package_path)

    cancelled = dispatcher.cancel(submitted.job_id)
    assert cancelled.status is RemoteJobStatus.CANCELLED
    assert dispatcher.cancel(submitted.job_id) == cancelled
    assert transport.cancellations == [submitted.remote_job_id]


def test_dispatcher_rejects_artifact_with_wrong_batch_hash(tmp_path):
    package_path = make_package(tmp_path)
    transport = FakeTransport()
    dispatcher = RemoteJobDispatcher(tmp_path / "dispatch.json", transport)
    submitted = dispatcher.submit(package_path)
    artifact = run_local_job(package_path)
    payload = json.loads((package_path / "artifact.json").read_text())
    payload["manifest"]["batch_input_hash"] = "tampered"
    transport.artifacts[submitted.remote_job_id] = json.dumps(payload).encode("utf-8")
    transport.statuses[submitted.remote_job_id] = RemoteJobStatus.COMPLETE

    with pytest.raises(RemoteJobError, match="batch input hash"):
        dispatcher.poll(submitted.job_id)
    assert dispatcher.get(submitted.job_id).status is RemoteJobStatus.TERMINAL_FAILED
    assert dispatcher.get(submitted.job_id).error == "remote artifact batch input hash does not match package"
    assert artifact["output_hash"]


def test_dispatcher_recovers_persisted_job_after_restart(tmp_path):
    package_path = make_package(tmp_path)
    transport = FakeTransport()
    state_path = tmp_path / "dispatcher.json"
    first_dispatcher = RemoteJobDispatcher(state_path, transport)
    submitted = first_dispatcher.submit(package_path)

    recovered_dispatcher = RemoteJobDispatcher(state_path, transport)
    recovered = recovered_dispatcher.find_for_round("remote-job-round")

    assert recovered == submitted
    transport.statuses[submitted.remote_job_id] = RemoteJobStatus.RUNNING
    assert recovered_dispatcher.poll(submitted.job_id).status is RemoteJobStatus.RUNNING


def test_dispatcher_timeout_is_terminal_and_cancels_once(tmp_path):
    package_path = make_package(tmp_path)
    transport = FakeTransport()
    now = [100.0]
    dispatcher = RemoteJobDispatcher(
        tmp_path / "dispatcher.json",
        transport,
        timeout_seconds=5.0,
        clock=lambda: now[0],
    )
    submitted = dispatcher.submit(package_path)
    now[0] = 106.0

    timed_out = dispatcher.poll(submitted.job_id)
    repeated = dispatcher.poll(submitted.job_id)

    assert timed_out.status is RemoteJobStatus.TERMINAL_FAILED
    assert timed_out.error == "remote evaluation timed out"
    assert repeated == timed_out
    assert transport.cancellations == [submitted.remote_job_id]


def test_configured_instructor_service_queues_and_ingests_remote_result(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(data["scenario"]), encoding="utf-8")
    store = RoundStore(tmp_path / "round.sqlite")
    store.create_round(
        RoundRecord(
            "round-remote",
            policy=RoundPolicy("phase3-minimal-round", "1", "0.3.0", policy_version=data["policy_version"], seed=data["seed"]),
        ),
        teams=tuple(item["team_id"] for item in data["submissions"]),
    )
    store.transition_round("round-remote", RoundState.OPEN, actor_id="teacher")
    for item in data["submissions"]:
        payload = item["payload"] if "payload" in item else item
        store.insert_submission(
            "round-remote",
            item["team_id"],
            payload,
            hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            f"submission-{item['team_id']}",
        )
    transport = FakeTransport()
    dispatcher = RemoteJobDispatcher(tmp_path / "dispatcher.json", transport)
    server = practice_server.create_server(
        scenario_path=scenario_path,
        port=0,
        round_store=store,
        bootstrap_credential="bootstrap",
        evaluation_dispatcher=dispatcher,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method: str, path: str, token: str | None = None, body: object | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        headers = {"X-Bootstrap-Credential": "bootstrap"}
        encoded = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            encoded = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response, payload

    try:
        session_response, session = request("POST", "/api/session", body={"actor_id": "teacher", "round_id": "round-remote", "role": "instructor"})
        assert session_response.status == 201
        queued_response, queued = request("POST", "/api/instructor/rounds/round-remote/evaluate", session["token"], {})
        assert queued_response.status == 202
        package_path = transport.submissions[0]
        run_local_job(package_path)
        transport.artifacts["remote-1"] = (package_path / "artifact.json").read_bytes()
        transport.statuses["remote-1"] = RemoteJobStatus.COMPLETE
        completed_response, completed = request("GET", "/api/instructor/rounds/round-remote/evaluate/status", session["token"])
        assert queued["status"] == RemoteJobStatus.QUEUED.value
        assert completed_response.status == 200
        assert completed["status"] == RemoteJobStatus.COMPLETE.value
        assert completed["state"] == RoundState.EVALUATED.value
        repeated_response, repeated = request("GET", "/api/instructor/rounds/round-remote/evaluate/status", session["token"])
        assert repeated_response.status == 200
        assert repeated == completed
        assert server.round_store.export_round_bundle("round-remote")["team_results"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
