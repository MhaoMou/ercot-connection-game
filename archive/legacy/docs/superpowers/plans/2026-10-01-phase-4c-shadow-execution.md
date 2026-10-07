# Phase 4C Shadow Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute one real multi-team locked batch locally and on Electrify, then prove that rankings, diagnostics, and replayable artifacts are identical while local execution remains authoritative.

**Architecture:** Reuse the existing Phase 4A immutable job package and Phase 3 evaluator without changing evaluator mathematics, scenario data, or service behavior. Use the existing three-team `data/fixtures/phase3_round.json` fixture as the locked batch, stage the identical package in an isolated Electrify directory, run the same worker in both environments, and compare canonical evaluation content plus artifact hashes.

**Tech Stack:** Python job package, JSON, SHA-256, SSH/rsync, pytest, existing Phase 3 evaluator.

---

### Task 1: Establish the shadow batch and comparison contract

**Files:**
- Read: `data/fixtures/phase3_round.json`
- Read: `src/ercot_game/evaluation_jobs.py`
- Create: `docs/superpowers/plans/2026-10-01-phase-4c-shadow-execution.md`

- [x] Confirm the fixture contains multiple teams and locked-round inputs.
- [x] Confirm the comparison will include status, ranking order, scores, feasibility, binding resources, diagnostics, input hash, and output hash.
- [x] Confirm local evaluation remains the authoritative result and remote output is only a shadow comparison.

### Task 2: Create the identical local package

**Files:**
- Read: `data/fixtures/phase3_round.json`
- Use: `src/ercot_game/evaluation_jobs.py`

- [x] Load the production Teaching Scenario V2 with the existing scenario parser.
- [x] Create a job package with a fixed round/job identity, production Planning Model version, policy, seed, and three team submissions.
- [x] Run the package locally, replay its audit bundle, and write a normalized comparison record without changing production data.

### Task 3: Execute the identical package on Electrify

**Files:**
- Create: isolated remote directory under `/home/minghao/ercot_gate4c_shadow_20261001`
- Use: smoke-only Python 3.10 compatibility shim if required by the host runtime

- [x] Perform the safe remote preflight and verify the isolated directory is unused.
- [x] Transfer only the Phase 4A source, the immutable package, and the temporary compatibility shim.
- [x] Run the worker in the foreground and replay the remote artifact.
- [x] Do not connect to the production service, classroom database, scheduler, or student workflow.

### Task 4: Compare complete shadow results

**Files:**
- Create: `docs/ERCOT_PHASE4C_SHADOW_EXECUTION.md`

- [x] Compare local and remote status and canonical input hashes.
- [x] Compare ranking order, score, feasibility, binding resources, and diagnostics for every team.
- [x] Compare replayed output hashes and exact artifact SHA-256 values.
- [x] Record the runtime limitation, remote directory, verification scope, and unproven production behavior.

### Task 5: Regression verification and handoff

**Files:**
- Modify: `docs/ERCOT_PHASE4B_ELECTRIFY_SMOKE.md`
- Modify: `docs/ERCOT_PHASE4A_LOCAL_JOBS.md`

- [x] Run the focused multiteam/job/Planning Model tests after the validator correction: 39 passed.
- [x] Run the full regression suite: 596 passed.
- [x] Update the Phase 4 handoff to identify Gate 4C as complete without starting scheduler integration automatically.
