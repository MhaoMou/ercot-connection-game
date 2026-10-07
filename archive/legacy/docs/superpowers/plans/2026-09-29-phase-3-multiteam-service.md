# Phase 3 Multi-Team Classroom Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, deterministic, instructor-controlled multi-team classroom service around the existing Phase 1 evaluator while preserving the Phase 2 single-team practice workflow.

**Architecture:** Add focused persistence and orchestration modules behind the existing Python service. SQLite stores round state and immutable artifacts; a multi-team service canonicalizes accepted submissions and invokes `evaluate_week` without duplicating scoring. Add authenticated student/instructor API routes first, then extend the existing browser with round/submission/leaderboard state.

**Tech Stack:** Python 3 standard library (`sqlite3`, `hashlib`, `hmac`, `secrets`, `http.server`, `json`), existing evaluator/models, static HTML/CSS/JavaScript, pytest.

---

## File map

- Create `src/ercot_game/round_models.py` — typed dataclasses/enums for round states, policies, sessions, submissions, evaluation runs, and results.
- Create `src/ercot_game/round_store.py` — SQLite schema, migrations, transactions, and CRUD operations. No evaluator logic.
- Create `src/ercot_game/multiteam.py` — canonical ordering, submission snapshotting, joint evaluation, ranking, and audit-bundle generation.
- Create `src/ercot_game/auth.py` — classroom token creation, token hashing, session lookup, and role checks.
- Modify `src/ercot_game/practice_server.py` — inject the optional round store/service, route Phase 3 endpoints, preserve Phase 2 routes unchanged.
- Create `data/fixtures/phase3_round.json` — deterministic classroom round policy and seeded team fixture for integration tests.
- Create `tests/test_round_models.py` — state/policy validation tests.
- Create `tests/test_round_store.py` — schema, transaction, idempotency, isolation, and audit-event tests.
- Create `tests/test_multiteam.py` — canonical ordering, joint evaluation, ranking, ties, failures, replay, and artifact tests.
- Create `tests/test_auth.py` — token hashing and role authorization tests.
- Modify `tests/test_practice_server.py` — Phase 3 endpoint contract and lifecycle tests; retain all existing Phase 2 tests.
- Modify `web/index.html` — round/status/leaderboard markup while preserving the map and plan editor.
- Modify `web/app.js` — authenticated round state, draft save/submit flows, and server-provided result rendering.
- Modify `web/styles.css` — status, deadline, submission, and leaderboard states.
- Modify `tests/test_web_assets.py` — source contracts for round state, submission status, and no client-side scoring.
- Create `docs/phase-3-multiteam-service.md` — operator/student API guide and fairness policy.
- Modify `README.md` — describe Phase 3 local classroom service and its safety boundary.

## Task 1: Define round-domain types and policies

**Files:**
- Create: `src/ercot_game/round_models.py`
- Create: `tests/test_round_models.py`

- [ ] **Step 1: Write failing tests for lifecycle and policy validation.**

Test that only `draft -> open -> locked -> evaluated -> published` and `evaluated -> failed`/`published -> retracted` are accepted; invalid transitions raise a structured domain error. Test that a round policy rejects missing scenario/evaluator versions, negative deadlines, unsupported visibility values, and an unseeded randomized tie policy.

- [ ] **Step 2: Run the focused tests and verify they fail because the module does not exist.**

Run: `pytest tests/test_round_models.py -q`

Expected: collection/import failure for `ercot_game.round_models`.

- [ ] **Step 3: Implement the minimal domain model.**

Define string enums `RoundState` and `ActorRole`, immutable dataclasses `RoundPolicy`, `RoundRecord`, `SessionRecord`, `SubmissionRecord`, `EvaluationRunRecord`, and `TeamResultRecord`. Add `transition_allowed(current, target)`, `validate_round_policy(policy)`, and `rank_results(results, tie_break_mode, seed)`; keep ranking independent of presentation order and use descending authoritative total by default.

- [ ] **Step 4: Run the focused tests and the evaluator regression suite.**

Run: `pytest tests/test_round_models.py tests/test_evaluator.py tests/test_reproducibility.py -q`

Expected: all tests pass; no evaluator behavior changes.

## Task 2: Add SQLite persistence and transactional round state

**Files:**
- Create: `src/ercot_game/round_store.py`
- Create: `tests/test_round_store.py`

- [ ] **Step 1: Write failing tests for schema, transactions, and isolation.**

Cover: round creation, team membership, mutable draft replacement, immutable submission insertion, duplicate idempotency-key replay, rejection of writes after lock, audit-event creation for every state transition, and queries that cannot read another team’s private draft/submission.

- [ ] **Step 2: Run the focused tests and verify the expected missing-store failures.**

Run: `pytest tests/test_round_store.py -q`

Expected: import or attribute failures for the new store API.

- [ ] **Step 3: Implement the schema and store API.**

Use `sqlite3.connect(..., isolation_level=None)` with explicit `BEGIN IMMEDIATE` for mutations. Create tables `rounds`, `teams`, `sessions`, `drafts`, `submissions`, `evaluation_runs`, `team_results`, and `audit_events`, with foreign keys, unique `(round_id, team_id)`, unique `(round_id, idempotency_key)`, immutable submission rows, and UTC ISO-8601 timestamps. Expose methods `create_round`, `get_round`, `transition_round`, `upsert_draft`, `get_draft`, `insert_submission`, `get_team_submission`, `lock_submission_snapshot`, `create_evaluation_run`, `store_results`, `record_audit_event`, and `export_round_bundle`.

- [ ] **Step 4: Verify transaction and persistence behavior.**

Run: `pytest tests/test_round_store.py -q`

Expected: all store tests pass, including reopening the same temporary database and retrieving the same records.

## Task 3: Add classroom authentication and authorization

**Files:**
- Create: `src/ercot_game/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests for token handling and role isolation.**

Test creation of student and instructor credentials, storage of only salted/derived token material, constant-time token comparison, session expiry, student access limited to its team, and instructor-only access to round mutation/audit routes.

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `pytest tests/test_auth.py -q`

Expected: missing-module or missing-function failures.

- [ ] **Step 3: Implement minimal classroom authentication.**

Use `secrets.token_urlsafe` for classroom tokens, `hashlib.pbkdf2_hmac` with a per-token salt for stored derivations, and `hmac.compare_digest` for verification. Return an opaque `SessionRecord` containing `actor_id`, `round_id`, `team_id`, and `role`; never include another team’s existence in authorization errors.

- [ ] **Step 4: Verify authentication tests and run the full non-web suite.**

Run: `pytest tests/test_auth.py tests/test_round_models.py tests/test_round_store.py -q`

Expected: all tests pass.

## Task 4: Implement deterministic multi-team evaluation and ranking

**Files:**
- Create: `src/ercot_game/multiteam.py`
- Create: `tests/test_multiteam.py`
- Create: `data/fixtures/phase3_round.json`

- [ ] **Step 1: Write failing tests for canonical batch semantics.**

Test that shuffled submission arrival order produces the same ordered team/connection input, semantic hash, evaluator output, and ranking. Test shared-bus/corridor allocation uses the published canonical key `(team_id, connection_id)`, valid plans with insufficient capacity receive evaluator-derived curtailment, invalid plans receive the configured zero official revenue outcome, and evaluator exceptions mark the batch failed without partial publication.

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `pytest tests/test_multiteam.py -q`

Expected: missing orchestration API failures.

- [ ] **Step 3: Implement the orchestration service.**

Define `canonicalize_submissions`, `build_batch_input`, `evaluate_locked_round`, `rank_team_results`, and `build_audit_bundle`. Normalize each plan through the existing `plan_from_dict`/evaluator boundary, sort stable IDs before evaluation, compute a canonical JSON SHA-256 hash, call `evaluate_week`, preserve evaluator diagnostics, and store ranking/audit metadata through `round_store`.

- [ ] **Step 4: Implement deterministic tie handling and replay.**

Use equal ranks for default ties. If a round enables seeded tie-breaking, derive ordering only from the stored seed and stable team IDs, persist the seed, and include it in the artifact. Add `replay_audit_bundle(bundle)` and assert its totals/ranks equal the stored output.

- [ ] **Step 5: Run orchestration, evaluator, allocation, scoring, and reproducibility tests.**

Run: `pytest tests/test_multiteam.py tests/test_evaluator.py tests/test_allocation.py tests/test_scoring.py tests/test_reproducibility.py -q`

Expected: all tests pass with no changes to the Phase 1 evaluator.

## Task 5: Add Phase 3 HTTP endpoints without regressing Phase 2

**Files:**
- Modify: `src/ercot_game/practice_server.py`
- Modify: `tests/test_practice_server.py`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Write failing endpoint tests.**

Add an isolated temporary database fixture and test `POST /api/session`, round reads, draft read/write, idempotent submission, deadline rejection, lock/evaluate/publish transitions, private submission isolation, leaderboard visibility before/after publication, and audit export. Keep existing `/api/health`, `/api/scenario`, and `/api/evaluate` assertions unchanged.

- [ ] **Step 2: Run the Phase 3 endpoint tests and verify failures.**

Run: `pytest tests/test_practice_server.py -q`

Expected: 404 or missing-route failures only for new Phase 3 endpoints; existing Phase 2 tests remain green.

- [ ] **Step 3: Add request authentication and structured errors.**

Parse `Authorization: Bearer <token>` before private routes, create request IDs, and return JSON errors with stable codes for `unauthorized`, `forbidden`, `round_not_open`, `deadline_passed`, `duplicate_submission`, `invalid_transition`, `validation_failed`, and `evaluation_failed`. Do not leak private team records in error bodies.

- [ ] **Step 4: Wire route handlers to store/auth/orchestration modules.**

Add route dispatch for the API surface in the specification. Keep scenario/static assets and legacy practice evaluation behavior unchanged. Ensure `POST /api/instructor/rounds/{id}/evaluate` locks the snapshot, runs one batch, stores results only after successful completion, and exposes `failed` without publishing a ranking when evaluation fails.

- [ ] **Step 5: Run all server tests.**

Run: `pytest tests/test_practice_server.py tests/test_auth.py tests/test_round_store.py tests/test_multiteam.py -q`

Expected: all tests pass.

## Task 6: Extend the browser with round and submission state

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing source-contract tests.**

Assert that the browser has round-state, team identity, deadline, draft-save, submit, submission-status, leaderboard, and instructor-control hooks; that it calls the Phase 3 endpoints; and that it contains no official score/rank/curtailment calculation logic.

- [ ] **Step 2: Run the focused web tests and verify failures.**

Run: `pytest tests/test_web_assets.py -q -k 'round or submission or leaderboard'`

Expected: missing markup/endpoint-hook assertions.

- [ ] **Step 3: Add accessible round/status markup.**

Add a compact round header with state, team, deadline, save status, and submission status. Add a submit confirmation region, a server-result region, and a leaderboard region with explicit `aria-live` behavior. Keep instructor controls in a separate role-gated container rather than hiding them solely with CSS.

- [ ] **Step 4: Add browser state flow.**

Implement `loadRound`, `loadDraft`, `saveDraft`, `submitPlan`, `loadSubmissionStatus`, and `loadLeaderboard` using server responses. Preserve the local form while offline or during retries, disable submit after lock/deadline responses, show immutable submission timestamps, and render only server-provided score/rank/diagnostic fields.

- [ ] **Step 5: Run web source tests and the live local preview.**

Run: `pytest tests/test_web_assets.py -q`

Then start the practice server with a Phase 3 fixture and verify in the browser that an open round can save/submit, a locked round disables submission, and unpublished private results do not appear in the public leaderboard.

## Task 7: Add end-to-end classroom scenarios, documentation, and audit verification

**Files:**
- Create: `tests/test_phase3_end_to_end.py`
- Create: `docs/phase-3-multiteam-service.md`
- Modify: `README.md`

- [ ] **Step 1: Write end-to-end failing scenarios.**

Exercise two teams submitting in opposite orders, one team replacing a draft, a deadline boundary, a shared-corridor congestion case, an invalid plan, an evaluator failure, publication, retraction, and audit-bundle replay.

- [ ] **Step 2: Implement the classroom fixture and test client helpers.**

Use temporary SQLite databases and the existing HTTP test helper. Create named student/instructor sessions from `data/fixtures/phase3_round.json`; assert each response status, error code, visibility field, and stored artifact hash.

- [ ] **Step 3: Document the operational and fairness contract.**

Document setup, token provisioning, round lifecycle, canonical ordering, shared-resource semantics, invalid-plan policy, visibility, leaderboard fields, replay procedure, backup of the SQLite file, and the practice-only boundary. State that Electrify and Gymnasium remain future phases.

- [ ] **Step 4: Run the complete verification suite.**

Run: `pytest -q`

Expected: all existing Phase 1/Phase 2 tests plus Phase 3 tests pass. Confirm the documented audit bundle replays to identical totals and ranks.

- [ ] **Step 5: Perform a manual browser smoke test.**

Start the service on `127.0.0.1:8000`, open the Phase 3 student route, save a draft, submit it, lock/evaluate/publish from the instructor route, and verify the student sees the published result without gaining access to another team’s plan.

## Final review checkpoint

Before Phase 3 is called complete, review the implementation against every acceptance criterion in `docs/superpowers/specs/2026-09-29-phase-3-multiteam-service-design.md`. Do not proceed to Electrify integration or Gymnasium work until the evaluator version, policy version, canonical input hash, seed, and replay artifact are all persisted and tested.
