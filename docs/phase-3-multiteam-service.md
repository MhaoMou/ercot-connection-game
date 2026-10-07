# Phase 3 multi-team classroom service

Phase 3 is the local, instructor-controlled classroom service around the Phase 1
deterministic evaluator. It is designed for repeatable teaching rounds, not for
ERCOT operations, market settlement, interconnection approval, or production
student identity management.

## Local service architecture

The initial deployment is one Python process with the standard-library HTTP
server, the Phase 1 evaluator loaded in-process, and one SQLite database file.
SQLite owns round state, team membership, sessions, mutable drafts, immutable
submissions, evaluation runs, published team results, and audit events. The
multi-team adapter is the semantic boundary: it canonicalizes submissions,
invokes `evaluate_week`, validates evaluator output, ranks results, and emits a
replayable audit bundle. It must not duplicate scoring or feasibility rules.

The database is the durable classroom artifact. Back it up after locking and
again after publishing. Keep the scenario JSON, evaluator version, policy
version, canonical input hash, seed, and service revision with the backup.

## Route workflow

The bootstrap credential is used only by a trusted local instructor to issue
round-scoped sessions. After that, every protected route uses `Authorization:
Bearer <token>`. `POST /api/instructor/rounds` is the global instructor setup
capability: it accepts any authenticated instructor bearer session as the
setup authority, even though that session was originally issued for a
particular round. Students are never accepted for this route.

| Route | Classroom use |
| --- | --- |
| `POST /api/session` | Issue a student/team or instructor session with the bootstrap credential. |
| `GET /api/rounds/{id}` | Read round state and the caller's scope. |
| `GET /api/rounds/{id}/draft` | Read only the authenticated team's draft. |
| `PUT /api/rounds/{id}/draft` | Replace a team's mutable draft while the round is open. |
| `POST /api/rounds/{id}/submit` | Store one immutable official plan; require an idempotency key. |
| `GET /api/rounds/{id}/submission` | Read only the authenticated team's submission receipt. |
| `GET /api/rounds/{id}/leaderboard` | Read published results subject to visibility policy. |
| `POST /api/instructor/rounds` | Create a draft round or clone a source round; instructor/global setup capability. |
| `POST /api/instructor/rounds/{id}/transition` | Move `draft → open → locked → evaluated → published`; retract only from published. |
| `POST /api/instructor/rounds/{id}/evaluate` | Lock/snapshot if needed, run the joint evaluator, and persist results. |
| `GET /api/instructor/rounds/{id}/audit` | Export the authoritative audit bundle. |
| `POST /api/instructor/rounds/{id}/audit/replay` | Verify and replay a supplied bundle. |

Creating a round and registering teams is a trusted setup operation backed by
SQLite. The instructor should verify the team list before opening the round;
students should never be able to add, remove, or rename teams through a student
session.

### Create or clone a round

`POST /api/instructor/rounds` requires `Authorization: Bearer <instructor
token>` and accepts this JSON shape:

```json
{
  "round_id": "week-2",
  "policy": {
    "scenario_id": "ercot-small-week-01",
    "scenario_version": "1",
    "evaluator_version": "0.3.0",
    "policy_version": "phase3-week-2",
    "deadline_seconds": 3600,
    "deadline_at": null,
    "visibility": "private",
    "tie_break_mode": "default",
    "seed": null,
    "display_timezone": "UTC"
  },
  "teams": ["team-alpha", {"team_id": "team-beta", "display_name": "Beta"}],
  "clone_from": "week-1"
}
```

`round_id` and `policy` are required for a new round; `teams` is an array of
strings or `{team_id, display_name}` objects. New rounds always start in
`draft`. When `clone_from` is present, the source policy and team memberships
are copied unless an explicit `policy` or `teams` override is supplied. Policy
overrides are merged field-by-field with the source policy. The source round
is never mutated, and drafts, submissions, evaluations, results, and audit
history are not copied. A clone source must exist.

Success returns `201` with the deterministic round representation and a
`request_id`. Structured errors include `request_id`: malformed or invalid
payloads return `400` (`validation_failed`), missing authentication returns
`401` (`unauthorized`), a student or other unauthorized role returns `403`
(`forbidden`), a missing `clone_from` source returns `404` (`not_found`), and
an existing `round_id` returns `409` (`round_exists`).

## Classroom operational runbook

1. Copy the versioned scenario fixture and choose the evaluator and policy
   versions, deadline, timezone-aware UTC deadline, visibility mode, and tie
   policy. Create the round and register all teams.
2. Issue instructor and team sessions over the trusted local channel. Confirm
   each student token is bound to exactly one round and one team.
3. Transition to `open`. Students may save drafts repeatedly, inspect their own
   draft, and submit a plan before the deadline.
4. At the deadline, the instructor explicitly transitions to `locked` (or the
   evaluation route takes the lock snapshot). A late submission is rejected
   but does not automatically lock the round. No draft or official submission
   writes are accepted after lock.
5. Evaluate the complete snapshot jointly. Inspect the run status, input hash,
   diagnostics, invalid-plan records, and audit export before publishing.
6. Transition to `published` only after the instructor has checked the policy
   and artifact. Retract a publication if a material issue is found; do not
   edit the stored result in place. Correct by creating a new controlled round
   or a separately documented rerun.
7. Export the SQLite file and audit bundle. For a weekly course, clone the
   operational checklist for each week and retain the month-long series as
   separate versioned rounds.

## Official semantics and visibility policy

All accepted submissions are canonicalized before evaluation. Shared buses and
corridors are one common resource pool for the batch. Allocation uses the
published canonical `(connection_id, team_id)` order; HTTP arrival order and
screen order cannot change capacity allocation or ranking. The same canonical
input produces the same complete evaluation payload, including input/output
metadata, allocations, scores, official revenue, diagnostics, and ranked
results, as well as the same input hash.

Invalid plans remain visible to the instructor as invalid submissions and are
assigned official revenue `0.0`; they are not silently dropped and are not
replaced with a fabricated evaluator score. A failed evaluator run is a failed
round outcome, not an excuse to publish partial or synthetic team results.

The evaluator and its versioned policy are authoritative. Clients may perform
friendly validation, but they do not score, allocate resources, rank teams, or
override official revenue. Default ranking is descending authoritative total;
equal totals share a rank. If seeded tie-breaking is enabled, the seed is part
of the policy and audit artifact.

Before publication, the leaderboard is empty. After publication, `private`
visibility gives a student only that student's result while an instructor sees
the complete ranking. `public` visibility gives every authenticated round
participant the published ranking fields, but never another team's plan or
private diagnostics. `aggregate` exposes only the supported aggregate count;
it does not expose congestion diagnostics or another team's plan. Retracting a
round removes published visibility from the leaderboard for the affected
student, other students, and the instructor in every visibility mode,
including `private`, while preserving the immutable submission, result, and
audit data for instructor audit/results access.

## Recovery, retry, and failure behavior

Draft saves are replaceable and can use positive compare-and-swap revisions.
Official submissions are immutable. Repeating the same successful submission
with the same idempotency key replays the original receipt; reusing a key with a
different team or payload is an error. A timeout should be retried with the
same key, never with a new official plan. Deadline, lock, invalid transition,
validation, authentication, authorization, and evaluator failures return
structured error codes and request IDs where applicable.

If the process stops, reopen the SQLite file, verify the last round state and
audit hash, and resume only the allowed transition. A successful evaluation
retry returns the stored evaluation run and does not create a second result
artifact or duplicate `evaluation.artifact` audit event. If an audit replay
detects an input, metadata, scenario, result, or output-hash mismatch,
quarantine the bundle and do not publish it. Never repair an immutable row with
ad-hoc SQL.

## Audit export and replay

An audit bundle contains the scenario, evaluator and policy versions, shared
resource policy, seed, canonical batch input, submissions, ranked results, and
input/output hashes. Replay re-runs the same semantic batch and must reproduce
the stored ranked results and output hash. Changing the scenario, policy,
seed, submission identity, or result record must fail hash or structure checks.
The instructor should replay the exported bundle after backup and before final
grade export.

## Repeatable weekly and month-long operation

Each weekly round is an independent immutable snapshot with an explicit policy,
scenario, deadline, and audit artifact. A four-week or month-long classroom
run assumes stable team IDs, a fresh round ID per week, UTC-aware clocks,
deterministic seeds, no dependence on submission timing, and a retained backup
for every lock/evaluate/publish boundary. The service is intentionally small:
serialize evaluations rather than requiring a distributed job queue, monitor
SQLite disk space, and record any material recovery action as an audit event;
ordinary successful evaluation retries remain idempotent and reuse the stored
audit artifact.

The acceptance fixture creates four rounds and registers their teams directly
in SQLite; it also moves each persisted deadline behind the injected fixture
clock directly to exercise the deadline boundary. For each round, the HTTP
workflow opens the round, issues fresh scoped sessions, saves and reads every
team draft, submits each immutable plan, verifies idempotent retries and
cross-round/team rejection, and asserts a structured `deadline_passed`
rejection with unchanged submissions and an unchanged `open` state. It then
evaluates, asserts the HTTP leaderboard is empty for the two valid student
participants and the instructor before publication, publishes, inspects
visibility, exports and replays the audit
bundle, and retracts the round. The process is then stopped, the SQLite
connection is closed, the same database is reopened, and a new HTTP server is
started over it. Post-restart HTTP requests must recover each round's state,
submission receipt, public/aggregate/private visibility for multiple student
and instructor participants, instructor audit bundle, replayed ranked results,
and persisted input/output metadata hashes, including the fetched audit
bundle's input hash. It then verifies that retraction hides leaderboard data
for all three participant types while the instructor can still retrieve the
persisted audit/results. This is a service restart check, not merely a fresh
in-memory recomputation.

## Boundary with Gymnasium/RL and external execution

Gymnasium/RL adapters, remote execution, Electrify integration, real-time grid
data, production authentication, and official ERCOT claims are future work.
Any future environment must call the same versioned evaluator, preserve
canonical hashes and deterministic seeds, distinguish training rewards from
official classroom revenue, and keep the service/audit boundary explicit.
