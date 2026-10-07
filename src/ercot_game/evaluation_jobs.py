"""Local, replayable evaluation jobs for the Phase 4A contract checkpoint.

This module packages the existing Phase 3 batch input and evaluator result. It
does not implement scoring or remote execution; the existing multiteam module
remains the only evaluation authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import time
import uuid
from collections.abc import Iterable, Mapping

from .io import scenario_from_dict, scenario_to_dict
from .models import EvaluationConfig, Scenario
from .multiteam import (
    POLICY_VERSION,
    build_audit_bundle,
    build_batch_input,
    evaluate_locked_round,
    replay_audit_bundle,
)


JOB_SCHEMA_VERSION = "phase4-job-v1"
ARTIFACT_FORMAT_VERSION = "phase4-artifact-v1"


class JobState(StrEnum):
    CREATED = "created"
    PACKAGED = "packaged"
    RUNNING = "running"
    ARTIFACT_READY = "artifact-ready"
    INGESTED = "ingested"
    RETRYABLE_FAILED = "retryable-failed"
    TERMINAL_FAILED = "terminal-failed"


_ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED: frozenset({JobState.PACKAGED, JobState.TERMINAL_FAILED}),
    JobState.PACKAGED: frozenset({JobState.RUNNING, JobState.TERMINAL_FAILED}),
    JobState.RUNNING: frozenset({JobState.ARTIFACT_READY, JobState.RETRYABLE_FAILED, JobState.TERMINAL_FAILED}),
    JobState.RETRYABLE_FAILED: frozenset({JobState.RUNNING, JobState.TERMINAL_FAILED}),
    JobState.ARTIFACT_READY: frozenset({JobState.INGESTED}),
    JobState.INGESTED: frozenset(),
    JobState.TERMINAL_FAILED: frozenset(),
}


class JobIntegrityError(ValueError):
    """Raised when a job package or artifact is incomplete or tampered with."""


@dataclass(frozen=True)
class LocalJobPackage:
    path: Path
    manifest: dict[str, object]
    batch_input: dict[str, object]
    state: JobState


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def evaluator_source_hash() -> str:
    """Hash evaluator/orchestration source used by the local worker."""
    package_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for filename in ("evaluator.py", "multiteam.py", "io.py"):
        digest.update(filename.encode("utf-8"))
        digest.update((package_root / filename).read_bytes())
    return digest.hexdigest()


def _planning_model_version(scenario: Scenario | Mapping[str, object]) -> str | None:
    metadata = scenario.metadata if isinstance(scenario, Scenario) else scenario.get("metadata", {})
    if isinstance(metadata, Mapping):
        value = metadata.get("planning_model_version")
        if value is not None:
            return str(value)
    presentation = scenario.presentation if isinstance(scenario, Scenario) else scenario.get("presentation", {})
    if isinstance(presentation, Mapping):
        model = presentation.get("planning_model", {})
        if isinstance(model, Mapping) and model.get("model_version") is not None:
            return str(model["model_version"])
    return None


def _state_path(package_path: Path) -> Path:
    return package_path / "state.json"


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JobIntegrityError(f"could not read JSON package file: {path.name}") from error
    if not isinstance(payload, dict):
        raise JobIntegrityError(f"package file must contain an object: {path.name}")
    return payload


class LocalEvaluationJobStore:
    """Small JSON-backed repository for Gate 4A job state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def package_path(self, job_id: str) -> Path:
        return self.root / job_id

    def get_state(self, job_id: str) -> JobState:
        payload = _read_json(_state_path(self.package_path(job_id)))
        try:
            return JobState(str(payload["state"]))
        except (KeyError, ValueError) as error:
            raise JobIntegrityError(f"invalid state for job {job_id}") from error

    def transition(self, job_id: str, target: JobState) -> JobState:
        package_path = self.package_path(job_id)
        current = self.get_state(job_id)
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise ValueError(f"cannot transition job from {current.value} to {target.value}")
        _write_json(_state_path(package_path), {"state": target.value, "updated_at": time.time()})
        return target


def create_local_job(
    root: Path,
    scenario: Scenario,
    submissions: Iterable[Mapping[str, object]],
    *,
    round_id: str,
    job_id: str | None = None,
    config: EvaluationConfig | Mapping[str, object] | None = None,
    policy_version: str = POLICY_VERSION,
    seed: int | None = None,
    tie_break_mode: str = "default",
) -> LocalJobPackage:
    """Write a self-contained canonical job package to ``root/job_id``."""
    job_id = job_id or uuid.uuid4().hex
    package_path = Path(root) / job_id
    package_path.mkdir(parents=True, exist_ok=False)
    batch = build_batch_input(
        scenario,
        submissions,
        config=config,
        policy_version=policy_version,
        seed=seed,
        tie_break_mode=tie_break_mode,
    )
    scenario_payload = batch["scenario"]
    if not isinstance(scenario_payload, Mapping):
        raise JobIntegrityError("batch scenario is not an object")
    manifest: dict[str, object] = {
        "job_schema_version": JOB_SCHEMA_VERSION,
        "evaluation_job_id": job_id,
        "round_id": round_id,
        "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.metadata.get("scenario_version"),
        "evaluator_version": scenario.evaluator_version,
        "policy_version": policy_version,
        "planning_model_version": _planning_model_version(scenario),
        "seed": seed,
        "tie_break_mode": tie_break_mode,
        "batch_input_hash": batch["canonical_hash"],
        "scenario_hash": _sha256_json(scenario_payload),
        "evaluator_source_hash": evaluator_source_hash(),
        "created_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    _write_json(package_path / "manifest.json", manifest)
    _write_json(package_path / "batch_input.json", batch)
    _write_json(_state_path(package_path), {"state": JobState.CREATED.value, "updated_at": time.time()})
    store = LocalEvaluationJobStore(Path(root))
    store.transition(job_id, JobState.PACKAGED)
    return LocalJobPackage(package_path, manifest, batch, JobState.PACKAGED)


def _load_package(package_path: Path) -> LocalJobPackage:
    manifest = _read_json(package_path / "manifest.json")
    batch = _read_json(package_path / "batch_input.json")
    try:
        state = JobState(_read_json(_state_path(package_path))["state"])
    except (KeyError, ValueError) as error:
        raise JobIntegrityError("job state is invalid") from error
    if manifest.get("job_schema_version") != JOB_SCHEMA_VERSION:
        raise JobIntegrityError("unsupported job schema version")
    if not isinstance(manifest.get("evaluation_job_id"), str):
        raise JobIntegrityError("job manifest is missing evaluation_job_id")
    return LocalJobPackage(package_path, manifest, batch, state)


def _validate_package(package: LocalJobPackage) -> Scenario:
    manifest = package.manifest
    batch = package.batch_input
    required_batch = {"scenario", "evaluator_version", "policy_version", "shared_resource_policy", "tie_break_mode", "seed", "configuration", "submissions", "canonical_json", "canonical_hash"}
    if not required_batch.issubset(batch):
        raise JobIntegrityError("job batch input is structurally incomplete")
    scenario_payload = batch.get("scenario")
    if not isinstance(scenario_payload, Mapping):
        raise JobIntegrityError("job scenario is invalid")
    canonical_json = batch.get("canonical_json")
    canonical_hash = batch.get("canonical_hash")
    if not isinstance(canonical_json, str) or hashlib.sha256(canonical_json.encode("utf-8")).hexdigest() != canonical_hash:
        raise JobIntegrityError("job canonical input hash mismatch")
    if _sha256_json(scenario_payload) != manifest.get("scenario_hash"):
        raise JobIntegrityError("job scenario hash mismatch")
    if batch.get("canonical_hash") != manifest.get("batch_input_hash"):
        raise JobIntegrityError("job batch hash mismatch")
    if batch.get("evaluator_version") != manifest.get("evaluator_version"):
        raise JobIntegrityError("job evaluator version mismatch")
    if manifest.get("evaluator_source_hash") != evaluator_source_hash():
        raise JobIntegrityError("job evaluator source hash mismatch")
    scenario = scenario_from_dict(scenario_payload)
    if scenario.scenario_id != manifest.get("scenario_id") or scenario.evaluator_version != manifest.get("evaluator_version"):
        raise JobIntegrityError("job scenario metadata mismatch")
    if _planning_model_version(scenario) != manifest.get("planning_model_version"):
        raise JobIntegrityError("job Planning Model version mismatch")
    records = batch.get("submissions")
    if not isinstance(records, list):
        raise JobIntegrityError("job submissions are invalid")
    submissions = [record["payload"] for record in records if isinstance(record, Mapping) and isinstance(record.get("payload"), Mapping)]
    recomputed = build_batch_input(
        scenario,
        submissions,
        config=batch.get("configuration"),
        policy_version=str(batch["policy_version"]),
        seed=batch.get("seed"),  # type: ignore[arg-type]
        tie_break_mode=str(batch["tie_break_mode"]),
    )
    if recomputed["canonical_json"] != canonical_json or recomputed["canonical_hash"] != canonical_hash:
        raise JobIntegrityError("job canonical input does not replay")
    return scenario


def run_local_job(package_path: Path) -> dict[str, object]:
    """Execute the existing evaluator once and persist an immutable artifact."""
    package = _load_package(Path(package_path))
    artifact_path = package.path / "artifact.json"
    if artifact_path.exists() and package.state in {JobState.ARTIFACT_READY, JobState.INGESTED}:
        return _read_json(artifact_path)
    store = LocalEvaluationJobStore(package.path.parent)
    if package.state == JobState.PACKAGED:
        store.transition(str(package.manifest["evaluation_job_id"]), JobState.RUNNING)
    try:
        scenario = _validate_package(package)
        records = package.batch_input["submissions"]
        assert isinstance(records, list)
        submissions = [record["payload"] for record in records if isinstance(record, Mapping) and isinstance(record.get("payload"), Mapping)]
        evaluation = evaluate_locked_round(
            scenario,
            submissions,
            config=package.batch_input.get("configuration"),
            policy_version=str(package.batch_input["policy_version"]),
            seed=package.batch_input.get("seed"),  # type: ignore[arg-type]
            tie_break_mode=str(package.batch_input["tie_break_mode"]),
        )
        if evaluation.get("status") != "complete":
            raise JobIntegrityError(str(evaluation.get("error") or "local evaluation failed"))
        if evaluation.get("input_hash") != package.manifest.get("batch_input_hash"):
            raise JobIntegrityError("evaluation input hash does not match job manifest")
        audit_bundle = build_audit_bundle(evaluation)
        artifact = {
            "artifact_format_version": ARTIFACT_FORMAT_VERSION,
            "status": evaluation.get("status"),
            "manifest": package.manifest,
            "evaluation": evaluation,
            "audit_bundle": audit_bundle,
            "output_hash": evaluation.get("output_hash"),
        }
        _write_json(artifact_path, artifact)
        store.transition(str(package.manifest["evaluation_job_id"]), JobState.ARTIFACT_READY)
        return _read_json(artifact_path)
    except Exception:
        current = store.get_state(str(package.manifest["evaluation_job_id"]))
        if current == JobState.RUNNING:
            store.transition(str(package.manifest["evaluation_job_id"]), JobState.TERMINAL_FAILED)
        raise


def replay_local_artifact(package_path: Path) -> dict[str, object]:
    """Replay and verify the stored audit bundle from a local job package."""
    package = _load_package(Path(package_path))
    artifact = _read_json(package.path / "artifact.json")
    if artifact.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
        raise JobIntegrityError("unsupported artifact format version")
    if artifact.get("manifest") != package.manifest:
        raise JobIntegrityError("artifact manifest mismatch")
    audit_bundle = artifact.get("audit_bundle")
    if not isinstance(audit_bundle, Mapping):
        raise JobIntegrityError("artifact is missing audit bundle")
    try:
        replayed = replay_audit_bundle(audit_bundle)
    except (KeyError, TypeError, ValueError) as error:
        raise JobIntegrityError("local artifact replay failed") from error
    if replayed.get("output_hash") != artifact.get("output_hash"):
        raise JobIntegrityError("artifact output hash mismatch")
    return replayed
