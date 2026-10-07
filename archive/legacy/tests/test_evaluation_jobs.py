from __future__ import annotations

import json
from pathlib import Path

import pytest

from ercot_game.evaluation_jobs import (
    ARTIFACT_FORMAT_VERSION,
    JOB_SCHEMA_VERSION,
    JobIntegrityError,
    JobState,
    LocalEvaluationJobStore,
    create_local_job,
    replay_local_artifact,
    run_local_job,
)
from ercot_game.io import scenario_from_dict


FIXTURE = Path(__file__).parents[1] / "data/fixtures/phase3_round.json"


def load_round():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_local_job_package_contains_versioned_manifest_and_canonical_batch(tmp_path):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])

    package = create_local_job(
        tmp_path,
        scenario,
        data["submissions"],
        round_id="round-4a",
        job_id="job-1",
        policy_version=data["policy_version"],
        seed=data["seed"],
    )

    assert package.state == JobState.PACKAGED
    assert package.manifest["job_schema_version"] == JOB_SCHEMA_VERSION
    assert package.manifest["round_id"] == "round-4a"
    assert package.manifest["batch_input_hash"] == package.batch_input["canonical_hash"]
    assert package.manifest["scenario_hash"]
    assert package.manifest["evaluator_source_hash"]
    assert (package.path / "manifest.json").exists()
    assert (package.path / "batch_input.json").exists()


def test_local_worker_writes_replayable_immutable_artifact_and_is_idempotent(tmp_path):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    package = create_local_job(
        tmp_path,
        scenario,
        data["submissions"],
        round_id="round-4a",
        job_id="job-2",
        policy_version=data["policy_version"],
        seed=data["seed"],
    )

    first = run_local_job(package.path)
    second = run_local_job(package.path)

    assert first == second
    assert first["artifact_format_version"] == ARTIFACT_FORMAT_VERSION
    assert first["status"] == "complete"
    assert first["manifest"]["batch_input_hash"] == first["evaluation"]["input_hash"]
    assert first["output_hash"] == first["evaluation"]["output_hash"]
    assert json.dumps(replay_local_artifact(package.path), sort_keys=True) == json.dumps(first["evaluation"], sort_keys=True)
    assert json.loads((package.path / "artifact.json").read_text()) == first


def test_local_job_store_tracks_states_and_rejects_tampered_batch(tmp_path):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    package = create_local_job(
        tmp_path,
        scenario,
        data["submissions"],
        round_id="round-4a",
        job_id="job-3",
        policy_version=data["policy_version"],
        seed=data["seed"],
    )
    store = LocalEvaluationJobStore(tmp_path)
    assert store.get_state("job-3") == JobState.PACKAGED
    store.transition("job-3", JobState.RUNNING)
    assert store.get_state("job-3") == JobState.RUNNING

    batch_path = package.path / "batch_input.json"
    batch = json.loads(batch_path.read_text())
    batch["seed"] = 999
    batch_path.write_text(json.dumps(batch, sort_keys=True, separators=(",", ":")))

    with pytest.raises(JobIntegrityError):
        run_local_job(package.path)
    assert store.get_state("job-3") == JobState.TERMINAL_FAILED
