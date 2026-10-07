# Phase 4D Remote Job Integration

Status: **PASS — opt-in instructor-service job boundary implemented**

Date: 2026-10-01

## What changed

The instructor service now has an opt-in asynchronous evaluation path built
around the immutable Phase 4A job package. The existing synchronous evaluator
remains the default when no dispatcher is configured.

Configured deployments expose:

```text
POST /api/instructor/rounds/{round_id}/evaluate
GET  /api/instructor/rounds/{round_id}/evaluate/status
POST /api/instructor/rounds/{round_id}/evaluate/cancel
```

The evaluate request locks the submission snapshot, creates a versioned job
package, submits it through an injected transport, and returns `202 Accepted`.
Status polling verifies the returned artifact's format, exact package manifest,
batch hash, output hash, and replayable audit bundle before persisting ranked
team results and transitioning the round to `evaluated`.

## Lifecycle contract

```text
queued → running → complete
   │        │
   ├────────┴→ retryable-failed → queued (bounded retries)
   │
   ├→ cancelled
   └→ terminal-failed
```

Dispatcher state is persisted in JSON so job identity, package path, remote
job ID, attempt count, hashes, and terminal status survive a service restart.
Repeated submission, polling, completion ingestion, and cancellation are
idempotent at the dispatcher boundary.

## Verification

- Dispatcher contract tests: retry, terminal failure, cancellation,
  idempotence, artifact replay, and tamper rejection.
- Instructor-service integration test: queued `202`, remote completion,
  artifact ingestion, ranked-result persistence, and round transition.
- Focused Gate 4D tests: `5 passed`.
- Existing synchronous Phase 3 path remains covered by the existing server
  regression suite.
- Full project regression suite: `601 passed`.

## Deployment boundary

The service accepts a `RemoteJobTransport` implementation. This pass does not
invent a scheduler protocol or pretend that Electrify's foreground SSH smoke
run is a production queue. A deployment still needs a transport adapter for
its selected scheduler or worker service implementing submit, status, artifact
fetch, and cancel. Until that adapter is selected and tested, local execution
remains the authoritative fallback.

No evaluator mathematics, Planning Model data, Teaching Scenario data, or
scoring behavior was changed by this integration.
