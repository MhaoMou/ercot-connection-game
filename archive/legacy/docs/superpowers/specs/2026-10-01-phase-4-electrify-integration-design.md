# Phase 4 Electrify Integration Design

**Status:** Architecture checkpoint — no remote jobs are submitted by this document.

**Goal:** Define a safe, reproducible remote-execution boundary for heavy or parallel classroom evaluation batches while preserving the existing local evaluator as the sole scoring authority.

## 1. Current boundary

The current Phase 3 classroom service evaluates a locked round synchronously in
the Python process:

```text
locked SQLite submission snapshot
        ↓
evaluate_locked_round(...)
        ↓
evaluate_week(...)
        ↓
immutable SQLite results + replayable audit bundle
```

Phase 4 must preserve this path as the deterministic fallback. Electrify is an
execution backend, not a second evaluator and not a source of network or
scenario data.

The frozen production inputs are currently:

- Teaching Scenario V2: `scenario_version = 2.0.0`;
- evaluator version: `0.3.0`;
- shared-resource policy: `phase3-canonical-v1`;
- Planning Model V1 as embedded/provenance-linked scenario data;
- canonical multi-team submission ordering and input hashing from Phase 3.

## 2. Scope

Phase 4 will add:

1. a serializable evaluation job envelope;
2. a local job repository and state machine;
3. an Electrify adapter/worker entry point;
4. artifact upload/download and integrity checks;
5. idempotent result ingestion;
6. retry, timeout, and failure-recovery behavior;
7. local fallback and replay verification;
8. small-batch and failure-injection tests.

Phase 4 will not change:

- Planning Model V1;
- Teaching Scenario V2;
- evaluator mathematics;
- scoring, curtailment, or ranking semantics;
- browser-side official scoring;
- the public geographic dataset;
- Gymnasium/RL interfaces, which belong to Phase 5.

## 3. Proposed job lifecycle

```text
created → packaged → submitted → running → artifact-ready → ingested
                         │           │             │
                         └───────────┴─────────────┴→ retryable-failed
                                                       ↓
                                                  terminal-failed
```

Each job has a stable `evaluation_job_id`. Retries create attempts under the
same logical job; they do not create a new semantic evaluation. Ingestion is
idempotent on `(round_id, batch_input_hash, evaluator_version, policy_version)`.

The existing synchronous path remains available when:

- Electrify credentials are absent;
- the remote queue is unavailable;
- the batch is below the configured offload threshold; or
- an instructor explicitly selects local execution.

## 4. Job envelope

The job package must be self-contained and contain no live database dependency.
The minimum manifest is:

```json
{
  "job_schema_version": "phase4-job-v1",
  "evaluation_job_id": "stable-id",
  "round_id": "classroom-round",
  "scenario_id": "ERCOT-PLANNING-TEACHING-V2",
  "scenario_version": "2.0.0",
  "evaluator_version": "0.3.0",
  "policy_version": "phase3-canonical-v1",
  "planning_model_version": "1.0.0",
  "seed": 0,
  "tie_break_mode": "default",
  "batch_input_hash": "sha256:...",
  "scenario_hash": "sha256:...",
  "evaluator_source_hash": "sha256:...",
  "created_at_utc": "..."
}
```

The package also contains the canonical batch input already accepted by
`evaluate_locked_round`, plus the exact evaluator configuration. Electrify must
not reconstruct a batch from mutable SQLite rows or browser requests.

## 5. Result artifact

The worker returns an immutable artifact containing:

- the original manifest;
- the canonical batch input and hash;
- evaluator status and error information;
- complete team results and rankings;
- output hash;
- worker attempt metadata;
- evaluator stdout/stderr references, if retained;
- creation and completion timestamps.

The service verifies scenario, evaluator, policy, planning-model, input, and
output hashes before writing SQLite results. A mismatch is a terminal failure,
not a best-effort result.

## 6. Failure and recovery policy

- A malformed submission remains a normal evaluator outcome under the existing
  invalid-plan policy.
- A worker crash, timeout, missing artifact, hash mismatch, or evaluator
  exception is an evaluation-job failure.
- A failed remote job must not publish partial rankings.
- Retry is allowed only for infrastructure failures and preserves the same
  canonical input hash.
- After retry exhaustion, the instructor can run the immutable package locally
  and compare the local artifact hash/output before publishing.
- Student requests never wait on an interactive SSH session.
- The browser receives a job status, not an intermediate or guessed score.

## 7. Electrify assumptions to verify before implementation

Before writing the adapter, confirm with a minimal non-production probe:

1. authenticated non-interactive job submission method;
2. available Python/runtime environment;
3. artifact staging and retrieval mechanism;
4. scheduler queue and resource limits;
5. wall-time and storage limits;
6. network policy for job submission and artifact retrieval;
7. retry/cancellation semantics;
8. whether jobs can run without an interactive SSH session;
9. how secrets are supplied without committing credentials;
10. expected cost and latency for representative classroom batches.

No student-facing service should depend on a manually maintained SSH shell.

## 8. Rollout order

### Gate 4A — Contract-only implementation

Implement the job manifest, artifact schema, hash verification, local job
state machine, and local worker that calls the existing evaluator. No Electrify
dependency is required.

### Gate 4B — Electrify smoke job

Submit one tiny, non-classroom evaluation package. Verify runtime, artifact
transfer, hashes, failure behavior, and cleanup. Do not connect this job to
student or instructor routes yet.

### Gate 4C — Shadow execution

For a controlled round, run local and Electrify evaluations from the same
immutable package. Compare output hashes, team totals, rankings, diagnostics,
and replay results. Local results remain authoritative.

### Gate 4D — Opt-in batch execution

Allow an instructor-only flag to offload a locked batch. Preserve local
fallback, status visibility, retries, and artifact replay.

### Gate 4E — Release decision

Enable remote execution by default only if shadow and failure-injection tests
show semantic equivalence and operational reliability.

## 9. Acceptance criteria

Phase 4 is complete only when:

- the same job package produces identical local and Electrify results;
- shuffled submission order remains identical after remote execution;
- duplicate job delivery is idempotent;
- failed jobs never publish partial results;
- a remote artifact can be replayed locally;
- timeout and worker-crash recovery are tested;
- missing credentials cleanly select local fallback;
- evaluator/scenario/policy/hash metadata is persisted;
- no student-facing request requires an interactive SSH session; and
- the full existing regression suite remains green.

## 10. Recommendation

Proceed first with Gate 4A: contract-only job packaging and a local worker.
This provides most of the reliability value without committing the classroom
service to an unverified Electrify interface. Only after the local package is
replayable should we perform the Electrify smoke job.
