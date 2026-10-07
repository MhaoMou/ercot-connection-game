# Phase 4D Remote Job Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in asynchronous evaluation-job boundary for the instructor service with persistent dispatch state, artifact verification, retry/cancel semantics, and local synchronous fallback.

**Architecture:** Keep `evaluate_locked_round` and the existing evaluator authoritative. Add a transport-agnostic dispatcher that submits immutable Phase 4A packages, polls remote status, verifies/replays returned artifacts, and persists job metadata in JSON. When configured on the HTTP server, instructor evaluation returns a queued job and new status/cancel routes complete or cancel it; the default server path remains the existing synchronous evaluator.

**Tech Stack:** Python 3.11 standard library, JSON, dataclasses, `Protocol`, existing Phase 4A job package, existing Phase 3 HTTP service, pytest.

---

### Task 1: Define the dispatcher contract with failing tests

**Files:**
- Create: `tests/test_remote_jobs.py`
- Read: `src/ercot_game/evaluation_jobs.py`

- [x] Test queued/running/complete polling with a fake transport.
- [x] Test returned artifact replay, batch-hash validation, and local artifact persistence.
- [x] Test retryable failure resubmission, terminal failure, idempotent polling, and cancellation.
- [x] Run the focused tests and verify they fail because the dispatcher module did not exist.

### Task 2: Implement the transport-agnostic dispatcher

**Files:**
- Create: `src/ercot_game/remote_jobs.py`

- [x] Define `RemoteJobStatus`, `RemoteJobRecord`, `RemoteJobError`, and a `RemoteJobTransport` protocol.
- [x] Persist dispatcher records atomically in a JSON state file so a service restart can recover job identity and package paths.
- [x] Submit immutable Phase 4A packages and record remote job IDs, attempt counts, hashes, and timestamps.
- [x] Poll remote state, retry only explicitly retryable failures within `max_attempts`, and keep terminal failures terminal.
- [x] Fetch completed artifacts, verify manifest/input hashes, replay the audit bundle, and store the artifact only after validation.
- [x] Make repeated status polls and cancellation idempotent.

### Task 3: Add opt-in instructor-service integration

**Files:**
- Modify: `src/ercot_game/practice_server.py`
- Test: `tests/test_practice_server.py` or `tests/test_remote_jobs.py`

- [x] Add an optional dispatcher argument to `create_server` and `PracticeHTTPServer` without changing default behavior.
- [x] Route configured instructor evaluations to an immutable Phase 4A package and return `202` with `evaluation_job_id` and `batch_input_hash`.
- [x] Add authenticated instructor status polling and cancellation routes.
- [x] On a verified complete artifact, persist exact ranked team results, audit metadata, and round transition using existing store APIs.
- [x] On terminal failure, expose a structured error and preserve the immutable package for diagnosis.
- [x] Ensure unauthenticated and student callers cannot use dispatcher control routes.

### Task 4: Verify fallback and service behavior

**Files:**
- Create: `docs/ERCOT_PHASE4D_REMOTE_JOB_INTEGRATION.md`
- Modify: `docs/ERCOT_PHASE4C_SHADOW_EXECUTION.md`

- [x] Verify the default instructor path remains synchronous and all existing server tests remain valid.
- [x] Verify the configured fake transport completes a locked multi-team package through the HTTP status route.
- [x] Verify retry and cancel behavior through the dispatcher contract.
- [x] Record that no real scheduler or production Electrify queue exists yet, so the transport remains an explicit deployment adapter.

### Task 5: Regression audit

- [x] Run focused remote-job and server tests.
- [x] Run the full regression suite with localhost socket permission.
- [x] Report exact pass counts and the remaining scheduler-specific deployment boundary.
