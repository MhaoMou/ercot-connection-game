# Phase 3 Multi-Team Classroom Service Design

## Goal

Extend the Phase 2 single-team practice interface into a controlled multi-team classroom service. Students should be able to join a round, maintain a draft plan, submit before the deadline, and view their own evaluation results. Instructors should be able to configure, lock, evaluate, publish, and export a round.

The Phase 1 evaluator remains the only scoring authority. Phase 3 adds persistence, round state, multi-team orchestration, ranking, instructor operations, and replayable artifacts; it does not introduce a second scoring implementation.

The service remains an educational simulator. It must retain the practice-only and non-operational ERCOT disclaimer and must not claim to be an ERCOT interconnection, dispatch, or grading system without a separately validated deployment process.

## Scope and non-goals

### In scope

- Persistent rounds, teams, drafts, submissions, evaluations, and published results.
- Student and instructor roles with authenticated service access.
- Round lifecycle and deadline enforcement.
- Joint multi-team evaluation through the existing evaluator contract.
- Deterministic shared-bus and shared-corridor allocation.
- Ranking, ties, visibility rules, and audit exports.
- Replayable evaluation artifacts with evaluator/scenario versions and hashes.
- A browser workflow that preserves the Phase 2 practice editor where possible.

### Not in scope

- Actual ERCOT submission, market settlement, operational dispatch, or AC power-flow studies.
- Electrify execution or distributed job scheduling. That belongs to Phase 4.
- Gymnasium/RL wrappers. That belongs to Phase 5 after the service contract is frozen.
- Self-service public registration, payment, or internet-scale deployment.
- Replacing the Phase 1 evaluator with browser-side scoring.

## Recommended architecture

Use a single Python classroom service with SQLite persistence and the existing standard-library HTTP surface as the initial deployment. Keep the evaluator as an in-process library call behind a service-layer adapter. This minimizes semantic drift and preserves the current local development workflow while giving the system explicit persistence seams.

The main components are:

1. **Round repository** — stores round configuration, state transitions, deadlines, scenario/evaluator versions, and visibility policy.
2. **Team/session repository** — stores instructor-created teams and credential records. Student identities are represented by stable team membership identifiers, not by public plan data.
3. **Draft/submission repository** — stores the latest draft separately from immutable submitted payloads. Each submission receives an idempotency key and semantic input hash.
4. **Multi-team evaluation service** — loads the locked submissions, normalizes them, invokes the evaluator, stores one immutable artifact per run, and produces ranking records.
5. **Instructor service** — creates/clones rounds, opens or locks them, evaluates, publishes/retracts results, inspects failures, and exports an audit bundle.
6. **Browser client** — adds round/team state and submission status around the existing Phase 2 editor; it never computes official scores.

SQLite is appropriate for the first classroom deployment because the expected workload is small, transactions and constraints are available, and a complete database file can be retained with the round artifact. The persistence interface should remain isolated so a later deployment can replace SQLite without changing evaluator semantics.

## Round lifecycle

Every round has a versioned scenario and evaluator configuration and moves through explicit states:

```text
draft -> open -> locked -> evaluated -> published
                         \-> failed
published -> retracted
```

- `draft`: instructor may edit configuration; students cannot submit.
- `open`: students may edit drafts and submit or replace submissions until the deadline.
- `locked`: submissions are closed; the service snapshots the accepted payload set.
- `evaluated`: the batch has a complete or explicitly failed evaluation artifact.
- `published`: instructor has released the configured results and leaderboard.
- `failed`: evaluation could not produce a complete artifact; no ranking is official.
- `retracted`: previously published results are hidden while preserving the audit history.

State transitions must be validated server-side and recorded with actor, timestamp, reason, and previous/new state. All times are stored in UTC; a round may expose an instructor-selected display timezone.

The first implementation supports one submission per team per round, with replacement allowed while the round is open. The final accepted submission is the one present at lock time. A late request receives a structured error and cannot modify the locked snapshot.

## Multi-team semantics and fairness

The service evaluates all accepted team submissions jointly. It must not use HTTP arrival order, database insertion order, browser display order, or process scheduling as a scoring input.

Before evaluation:

1. Validate every submitted plan against the round schema.
2. Normalize legacy and canonical plan forms through the existing evaluator boundary.
3. Sort teams by stable `team_id` and connections within each team by canonical `connection_id`.
4. Resolve shared bus and corridor requests from that canonical ordering.
5. Persist the ordered input set and its semantic hash.

The initial policy is deterministic canonical allocation, not first-come-first-served. This avoids rewarding network timing and makes shuffled replays identical. For a shared bus or corridor with insufficient capacity, allocation follows the published canonical order and records each accepted, curtailed, or rejected request. The policy must be visible in the round rules before students submit.

A later round may opt into a seeded randomized tie-break policy, but the seed and tie group must be stored in the artifact. Presentation ordering may differ from semantic ordering; it must never affect scores.

Invalid plans are retained as submitted artifacts but receive a structured validation outcome and a defined score policy from the round configuration. The initial policy is zero official revenue for a submission that cannot be normalized or evaluated, while environmental curtailment and unserved energy remain evaluator-derived penalties for otherwise valid plans. Evaluator failures mark the whole batch as failed rather than silently assigning scores.

## Visibility and ranking

Before publication, students see:

- their own submission status;
- their own validation/evaluation diagnostics when the round permits it; and
- only the public aggregate information explicitly configured by the instructor.

After publication, students see their own score, rank/tie group, and the public leaderboard fields configured for the round. Full other-team plans and private diagnostics remain hidden by default.

Ranking is based on the evaluator’s authoritative team total, with descending score as the default. Ties receive the same rank unless the round explicitly enables seeded tie-breaking. The leaderboard stores the ranking policy and evaluator version used to produce it.

## Persistence model

The initial schema contains these logical records:

- `rounds`: configuration, state, open/close/reveal timestamps, scenario ID/version, evaluator version, policy version, display timezone, and public-visibility settings.
- `teams`: stable team ID, display name, round membership, and credential reference.
- `drafts`: mutable latest plan plus revision and updated timestamp.
- `submissions`: immutable payload, normalized payload, semantic input hash, idempotency key, submitted timestamp, and status.
- `evaluation_runs`: immutable batch input hash, seed, status, started/completed timestamps, error details, and artifact location.
- `team_results`: score, rank, tie group, visibility state, and links to the evaluation run.
- `audit_events`: actor, action, target, timestamp, request ID, and structured metadata.

Database transactions must make submission replacement, lock snapshots, state transitions, and publication atomic. The service must reject duplicate idempotency keys with the original result rather than evaluating twice.

## API surface

The first service contract should expose:

- `POST /api/session` — establish a student or instructor session using a classroom credential.
- `GET /api/rounds/{round_id}` — return public round configuration and current state.
- `GET /api/rounds/{round_id}/draft` and `PUT /api/rounds/{round_id}/draft` — read/write the authenticated team draft while open.
- `POST /api/rounds/{round_id}/submit` — create or replace the team’s immutable submission with an idempotency key.
- `GET /api/rounds/{round_id}/submission` — return the team’s status and permitted diagnostics.
- `GET /api/rounds/{round_id}/leaderboard` — return only fields allowed by publication/visibility policy.
- `POST /api/instructor/rounds` — create or clone a round.
- `POST /api/instructor/rounds/{round_id}/transition` — perform a validated lifecycle transition.
- `POST /api/instructor/rounds/{round_id}/evaluate` — lock/evaluate according to policy and create an artifact.
- `GET /api/instructor/rounds/{round_id}/audit` — export a read-only audit bundle.

All endpoints return structured JSON errors with request IDs. Authentication and authorization failures must not reveal whether another team or private submission exists.

## Evaluation and artifacts

The multi-team service creates a deterministic batch input from the locked submissions and passes it through the existing evaluator. It stores:

- exact accepted request payloads;
- normalized canonical plans;
- semantic input hash;
- scenario and evaluator versions;
- policy version and optional random seed;
- ordered team IDs and connection IDs;
- complete evaluator output;
- ranking output;
- validation/evaluation failures; and
- code/configuration metadata needed for replay.

An audit export is a self-contained JSON bundle plus metadata manifest. Replaying the same bundle with the same evaluator version and policy must produce the same team totals and ranking, except where the bundle explicitly records a non-deterministic external failure.

## Browser changes

Preserve the Phase 2 planning editor and map. Add a round header showing round state, team identity, deadline, and submission status. Add draft save state, submit confirmation, immutable submission timestamp, and result/leaderboard visibility states. Instructor controls should be a separate route or explicitly role-gated surface; students must never see controls merely hidden by CSS.

The browser should display server-provided diagnostics and ranking data but must not calculate official revenue, feasibility, curtailment, or rank. It must handle expired rounds, locked rounds, duplicate submissions, validation errors, evaluator failures, and network retries without losing the local draft.

## Testing and acceptance criteria

Phase 3 is complete only when the following are covered:

- round state transitions reject invalid transitions and record audit events;
- submissions are immutable, idempotent, deadline-aware, and isolated by team;
- shuffled HTTP submission order produces identical canonical batch input, scores, and ranks;
- shared bus/corridor allocation is deterministic and replayable;
- equivalent legacy/canonical plans receive equivalent results;
- ties and optional seeded tie-breaking are reproducible;
- invalid plans and evaluator failures follow the published score policy;
- unauthorized requests cannot read or mutate another team’s private data;
- published/retracted leaderboard visibility follows round policy;
- audit bundles replay to the stored result;
- the Phase 2 single-team practice workflow continues to pass unchanged; and
- the educational and non-operational disclaimer remains visible.

## Delivery order

1. Implement repositories, schema migrations, round lifecycle, and test fixtures.
2. Implement batch submission snapshotting, deterministic orchestration, ranking, and audit artifacts.
3. Add authenticated student/instructor API routes and browser state flows.
4. Run classroom-style end-to-end tests with multiple teams and failure cases.
5. Update the handoff and document the frozen API/evaluator boundary before considering Phase 4 or Phase 5.
