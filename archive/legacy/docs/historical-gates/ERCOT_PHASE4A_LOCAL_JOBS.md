# Phase 4A Local Evaluation Jobs

Status: **PASS — contract-only local worker implemented**

Phase 4A establishes the evaluation-job boundary before any Electrify
integration. It packages the existing Phase 3 canonical batch input, runs the
existing evaluator locally, and writes a self-contained replayable artifact.

No remote job is submitted by this phase.

## Package layout

`create_local_job(...)` writes one directory per logical evaluation job:

```text
<root>/<evaluation_job_id>/
├── manifest.json
├── batch_input.json
├── state.json
└── artifact.json       # created after successful execution
```

The manifest records the job schema, round, scenario, evaluator, policy,
Planning Model, seed, tie-break mode, scenario hash, canonical batch hash, and
evaluator-source hash. The batch input is produced by the existing
`build_batch_input(...)` function and is already canonicalized and ordered.

## Local lifecycle

```text
created → packaged → running → artifact-ready
                         └──→ terminal-failed
```

The JSON-backed `LocalEvaluationJobStore` enforces valid transitions. A
successful rerun of an artifact-ready job returns the existing artifact and
does not evaluate the batch again.

## Worker behavior

`run_local_job(package_path)`:

1. verifies the package schema and required fields;
2. verifies the scenario, batch, Planning Model, and evaluator-source hashes;
3. recomputes the canonical batch input;
4. calls the existing `evaluate_locked_round(...)` function;
5. writes the evaluation result plus a Phase 3 audit bundle;
6. marks the job artifact-ready.

The worker does not implement scoring, allocation, curtailment, dispatch, or
ranking. Those remain exclusively inside the existing evaluator/orchestration
modules.

## Artifact and replay

The artifact format is `phase4-artifact-v1` and contains:

- the original manifest;
- the complete evaluation result;
- the existing replayable audit bundle;
- the authoritative output hash;
- the complete status.

`replay_local_artifact(...)` delegates to the existing
`replay_audit_bundle(...)` validation path. A mismatch in the manifest, input
hash, source hash, or output hash raises `JobIntegrityError`. Partial results
are never written as successful artifacts.

## Failure boundary

Gate 4A treats package corruption, source/version mismatch, evaluator failure,
and replay mismatch as terminal local-job failures. Retry policy and remote
attempt metadata will be added only when a real Electrify backend is selected.
The current classroom service can continue using its existing synchronous
path without depending on this package or on remote infrastructure.

## Verified smoke test

The focused tests use the Phase 3 multi-team fixture and verify:

- versioned manifest creation;
- canonical batch hashing;
- local evaluator execution;
- idempotent rerun behavior;
- artifact replay;
- tamper rejection;
- terminal failure state.

A production Teaching Scenario V2 package/replay smoke test should be run from
the documented command below before any Electrify smoke job:

```bash
PYTHONPATH=src python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory

from ercot_game.cli import _load_scenario
from ercot_game.evaluation_jobs import create_local_job, run_local_job, replay_local_artifact

scenario = _load_scenario(Path("data/teaching/ercot_connection_scenario_v2.json"))
submissions = [{
    "team_id": "phase4a-smoke",
    "connections": [],
    "generators": [],
    "intervention_budget_k": 0,
    "curtailment_depth_mu": 0.0,
    "flexibility_fee_per_mwh": 0.0,
}]
with TemporaryDirectory() as directory:
    package = create_local_job(Path(directory), scenario, submissions, round_id="phase4a-smoke", job_id="smoke-1")
    artifact = run_local_job(package.path)
    replay_local_artifact(package.path)
    print(artifact["status"], artifact["manifest"]["batch_input_hash"], artifact["output_hash"])
PY
```

The verified smoke run completed with:

```text
status: complete
scenario_id: ercot-planning-teaching-v2
planning_model_version: 1.0.0
batch_input_hash: 128f0805c427816b7d2c79b13c9bb41c4437dc936d26a0518c46e7fd4e089a21
output_hash: 664ed77692f2bafe59309ceba25305fb06294636c97821d58dd8611b2e173939
replayed_output_hash: 664ed77692f2bafe59309ceba25305fb06294636c97821d58dd8611b2e173939
```

## Handoff to Electrify

The isolated Electrify smoke job is documented in
[ERCOT_PHASE4B_ELECTRIFY_SMOKE.md](ERCOT_PHASE4B_ELECTRIFY_SMOKE.md), and the
Teaching Scenario V2 multi-team shadow comparison is documented in
[ERCOT_PHASE4C_SHADOW_EXECUTION.md](ERCOT_PHASE4C_SHADOW_EXECUTION.md). Local
execution remains authoritative until a production job mechanism is selected
and separately verified.
