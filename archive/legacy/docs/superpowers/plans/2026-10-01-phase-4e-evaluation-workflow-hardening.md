# Phase 4E Evaluation Workflow Hardening Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with verification after each behavior change.

**Goal:** Harden the Gate 4D asynchronous evaluation lifecycle without changing scoring or network behavior.

**Architecture:** Extend the existing persisted `RemoteJobDispatcher` state machine. Keep integrity failures terminal and explicit, preserve the local synchronous path, and verify the HTTP instructor boundary through focused tests.

**Tech Stack:** Python 3.11+, standard-library HTTP server, pytest tests already used by the project.

---

### Task 1: Add lifecycle regression tests

**Files:**
- Modify: `tests/test_remote_jobs.py`

- [ ] Add tests proving a new dispatcher instance recovers a submitted job and polls the same remote identity.
- [ ] Add a deterministic-clock timeout test proving cancellation occurs once and the job becomes terminal-failed.
- [ ] Add a test proving an invalid completed artifact is persisted as terminal-failed and cannot be polled again as active.
- [ ] Add a test proving repeated HTTP status polling after remote completion does not create a second evaluation run.

### Task 2: Implement minimal dispatcher hardening

**Files:**
- Modify: `src/ercot_game/remote_jobs.py`

- [ ] Save a terminal-failed record before re-raising `RemoteJobError` from artifact verification.
- [ ] Preserve existing timeout cancellation behavior and ensure terminal records remain idempotent.
- [ ] Keep all existing status values, IDs, hashes, and transport interfaces unchanged.

### Task 3: Document Gate 4E verification

**Files:**
- Create: `docs/ERCOT_PHASE4E_EVALUATION_WORKFLOW_HARDENING.md`

- [ ] Record the lifecycle contract, changes, exact tests run, and any unavailable environment verification.

### Task 4: Run verification

- [ ] Run the focused remote-job tests and server regression tests.
- [ ] Run the full project suite if `pytest` is available.
- [ ] Report exact pass/fail counts and do not mark Gate 4E complete if a P0/P1 issue remains.
