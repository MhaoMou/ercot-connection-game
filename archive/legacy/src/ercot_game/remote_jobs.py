"""Transport-agnostic orchestration for asynchronous evaluation jobs.

The dispatcher owns job lifecycle and artifact verification. It deliberately
does not know how a scheduler or remote host launches a worker; deployments
provide a :class:`RemoteJobTransport` implementation for that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import json
from pathlib import Path
from typing import Callable, Protocol
import time
import uuid

from .evaluation_jobs import ARTIFACT_FORMAT_VERSION
from .multiteam import replay_audit_bundle


class RemoteJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    RETRYABLE_FAILED = "retryable-failed"
    TERMINAL_FAILED = "terminal-failed"
    CANCELLED = "cancelled"


class RemoteJobError(ValueError):
    """Raised when a remote job or returned artifact violates the contract."""


class RemoteJobTransport(Protocol):
    def submit(self, package_path: Path) -> str:
        """Submit an immutable package and return its remote job identity."""

    def status(self, remote_job_id: str) -> RemoteJobStatus:
        """Return the transport's current status for a remote job."""

    def fetch_artifact(self, remote_job_id: str) -> bytes:
        """Return the completed artifact bytes."""

    def cancel(self, remote_job_id: str) -> RemoteJobStatus:
        """Request cancellation and return the resulting status."""


@dataclass(frozen=True)
class RemoteJobRecord:
    job_id: str
    remote_job_id: str
    package_path: Path
    round_id: str
    batch_input_hash: str
    status: RemoteJobStatus
    attempt: int
    max_attempts: int
    updated_at: float
    output_hash: str | None = None
    artifact_path: Path | None = None
    error: str | None = None


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RemoteJobError(f"could not read JSON: {path}") from error
    if not isinstance(payload, dict):
        raise RemoteJobError(f"JSON object required: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _record_to_dict(record: RemoteJobRecord) -> dict[str, object]:
    return {
        "job_id": record.job_id,
        "remote_job_id": record.remote_job_id,
        "package_path": str(record.package_path),
        "round_id": record.round_id,
        "batch_input_hash": record.batch_input_hash,
        "status": record.status.value,
        "attempt": record.attempt,
        "max_attempts": record.max_attempts,
        "updated_at": record.updated_at,
        "output_hash": record.output_hash,
        "artifact_path": str(record.artifact_path) if record.artifact_path else None,
        "error": record.error,
    }


def _record_from_dict(payload: dict[str, object]) -> RemoteJobRecord:
    try:
        return RemoteJobRecord(
            str(payload["job_id"]),
            str(payload["remote_job_id"]),
            Path(str(payload["package_path"])),
            str(payload["round_id"]),
            str(payload["batch_input_hash"]),
            RemoteJobStatus(str(payload["status"])),
            int(payload["attempt"]),
            int(payload["max_attempts"]),
            float(payload["updated_at"]),
            str(payload["output_hash"]) if payload.get("output_hash") is not None else None,
            Path(str(payload["artifact_path"])) if payload.get("artifact_path") else None,
            str(payload["error"]) if payload.get("error") is not None else None,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RemoteJobError("dispatcher state contains an invalid job record") from error


class RemoteJobDispatcher:
    """Persisted lifecycle manager around an injected remote transport."""

    _TERMINAL = frozenset({RemoteJobStatus.COMPLETE, RemoteJobStatus.TERMINAL_FAILED, RemoteJobStatus.CANCELLED})

    def __init__(
        self,
        state_path: Path,
        transport: RemoteJobTransport,
        *,
        max_attempts: int = 3,
        timeout_seconds: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.state_path = Path(state_path)
        self.transport = transport
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self._records = self._load()

    def _load(self) -> dict[str, RemoteJobRecord]:
        if not self.state_path.exists():
            return {}
        payload = _read_json(self.state_path)
        jobs = payload.get("jobs", {})
        if not isinstance(jobs, dict):
            raise RemoteJobError("dispatcher state jobs must be an object")
        return {str(job_id): _record_from_dict(value) for job_id, value in jobs.items() if isinstance(value, dict)}

    def _persist(self) -> None:
        _write_json_atomic(self.state_path, {"jobs": {job_id: _record_to_dict(record) for job_id, record in self._records.items()}})

    def get(self, job_id: str) -> RemoteJobRecord:
        try:
            return self._records[job_id]
        except KeyError as error:
            raise KeyError(job_id) from error

    def find_for_round(self, round_id: str) -> RemoteJobRecord | None:
        candidates = [record for record in self._records.values() if record.round_id == round_id]
        return max(candidates, key=lambda record: record.updated_at, default=None)

    def submit(self, package_path: Path) -> RemoteJobRecord:
        package_path = Path(package_path)
        manifest = _read_json(package_path / "manifest.json")
        job_id = str(manifest.get("evaluation_job_id") or "")
        batch_input_hash = str(manifest.get("batch_input_hash") or "")
        if not job_id or not batch_input_hash:
            raise RemoteJobError("package manifest is missing job or batch identity")
        existing = self._records.get(job_id)
        if existing is not None:
            return existing
        remote_job_id = self.transport.submit(package_path)
        record = RemoteJobRecord(
            job_id,
            remote_job_id,
            package_path,
            str(manifest.get("round_id") or ""),
            batch_input_hash,
            RemoteJobStatus.QUEUED,
            1,
            self.max_attempts,
            float(self.clock()),
        )
        self._records[job_id] = record
        self._persist()
        return record

    def _save(self, record: RemoteJobRecord) -> RemoteJobRecord:
        self._records[record.job_id] = record
        self._persist()
        return record

    def _verify_artifact(self, record: RemoteJobRecord, artifact_bytes: bytes) -> tuple[Path, str]:
        try:
            artifact = json.loads(artifact_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RemoteJobError("remote artifact is not valid JSON") from error
        if not isinstance(artifact, dict):
            raise RemoteJobError("remote artifact must be a JSON object")
        if artifact.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
            raise RemoteJobError("remote artifact format is unsupported")
        manifest = artifact.get("manifest")
        if not isinstance(manifest, dict) or manifest.get("batch_input_hash") != record.batch_input_hash:
            raise RemoteJobError("remote artifact batch input hash does not match package")
        local_manifest = _read_json(record.package_path / "manifest.json")
        if manifest != local_manifest:
            raise RemoteJobError("remote artifact manifest does not match package")
        evaluation = artifact.get("evaluation")
        if not isinstance(evaluation, dict) or evaluation.get("output_hash") != artifact.get("output_hash"):
            raise RemoteJobError("remote artifact output hash is inconsistent")
        audit_bundle = artifact.get("audit_bundle")
        if not isinstance(audit_bundle, dict):
            raise RemoteJobError("remote artifact is missing its audit bundle")
        try:
            replayed = replay_audit_bundle(audit_bundle)
        except (KeyError, TypeError, ValueError) as error:
            raise RemoteJobError("remote artifact audit replay failed") from error
        if replayed.get("output_hash") != artifact.get("output_hash"):
            raise RemoteJobError("remote artifact audit replay hash mismatch")
        artifact_path = record.package_path / "remote_artifact.json"
        temporary = artifact_path.with_suffix(".tmp")
        temporary.write_bytes(artifact_bytes)
        temporary.replace(artifact_path)
        return artifact_path, str(artifact["output_hash"])

    def poll(self, job_id: str) -> RemoteJobRecord:
        record = self.get(job_id)
        if record.status in self._TERMINAL:
            return record
        now = float(self.clock())
        if self.timeout_seconds is not None and now - record.updated_at > self.timeout_seconds:
            try:
                self.transport.cancel(record.remote_job_id)
            finally:
                return self._save(replace(record, status=RemoteJobStatus.TERMINAL_FAILED, error="remote evaluation timed out", updated_at=now))
        remote_status = self.transport.status(record.remote_job_id)
        if remote_status is RemoteJobStatus.RETRYABLE_FAILED:
            if record.attempt >= record.max_attempts:
                return self._save(replace(record, status=RemoteJobStatus.TERMINAL_FAILED, error="remote evaluation exhausted retry attempts", updated_at=now))
            remote_job_id = self.transport.submit(record.package_path)
            return self._save(replace(record, remote_job_id=remote_job_id, attempt=record.attempt + 1, status=RemoteJobStatus.QUEUED, updated_at=now, error="retrying remote evaluation"))
        if remote_status is RemoteJobStatus.COMPLETE:
            try:
                artifact_path, output_hash = self._verify_artifact(record, self.transport.fetch_artifact(record.remote_job_id))
            except RemoteJobError as error:
                self._save(replace(
                    record,
                    status=RemoteJobStatus.TERMINAL_FAILED,
                    updated_at=now,
                    error=str(error),
                ))
                raise
            return self._save(replace(record, status=RemoteJobStatus.COMPLETE, artifact_path=artifact_path, output_hash=output_hash, updated_at=now, error=None))
        if remote_status is RemoteJobStatus.CANCELLED:
            return self._save(replace(record, status=RemoteJobStatus.CANCELLED, updated_at=now))
        return self._save(replace(record, status=remote_status, updated_at=now))

    def cancel(self, job_id: str) -> RemoteJobRecord:
        record = self.get(job_id)
        if record.status in self._TERMINAL:
            return record
        status = self.transport.cancel(record.remote_job_id)
        return self._save(replace(record, status=status, updated_at=float(self.clock())))
