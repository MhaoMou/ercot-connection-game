# Phase 4E Evaluation Workflow Hardening Design

**Status:** Approved for implementation by the user's request to proceed with Gate 4E.

## Goal

Make the opt-in asynchronous evaluation path safe and diagnosable across service restarts, timeouts, cancellation, artifact-integrity failures, and repeated status polling while preserving the local evaluator as the scoring authority.

## Scope

The pass covers `RemoteJobDispatcher` lifecycle behavior and the instructor-service status boundary. It does not change evaluator mathematics, Planning Model data, Teaching Scenario data, browser plan behavior, or the default synchronous path.

## Design

1. Persisted records remain the source of truth for logical job identity, retry attempt, status, package path, and hashes. A new dispatcher instance must recover those records and continue polling the same remote job.
2. A configured timeout requests remote cancellation and records a terminal failure with an actionable error. Repeated polling must not issue another cancellation.
3. A returned artifact that fails format, manifest, hash, or audit replay validation must be persisted as terminal failure before the integrity error is surfaced. It must never publish rankings and must not be retried as a normal job.
4. Completed, cancelled, and failed jobs remain terminal and idempotent. Repeated server status requests must return the same terminal state without duplicate result runs or transitions.
5. The existing synchronous evaluator remains the default fallback when no dispatcher is configured.

## Verification

Add focused tests for restart recovery, timeout/cancel idempotence, integrity-failure terminalization, and repeated completed status polling. Run the focused remote-job and web/server regression tests, then the complete suite when the local test runner is available. Document any unavailable verification honestly.
