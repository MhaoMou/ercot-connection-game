# Phase 4A Local Evaluation Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package, execute, validate, and replay a deterministic classroom evaluation locally before adding any Electrify dependency.

**Architecture:** Add a small `evaluation_jobs` module that wraps the existing Phase 3 `build_batch_input` and `evaluate_locked_round` functions. A job directory contains a manifest and canonical batch input; a local worker validates hashes and versions, runs the existing evaluator, and writes an immutable artifact. A simple repository/state machine tracks lifecycle without changing the HTTP service or scoring code.

**Tech Stack:** Python 3.11 standard library, JSON, SHA-256, dataclasses, pytest.

---

### Task 1: Add failing Gate 4A contract tests

**Files:**
- Create: `tests/test_evaluation_jobs.py`

- [ ] **Step 1: Test deterministic package creation, required manifest metadata, and self-contained batch input.**
- [ ] **Step 2: Test local worker execution, artifact hashes, and replay through the existing audit mechanism.**
- [ ] **Step 3: Test tampered input rejection, idempotent reruns, and terminal failure state.**
- [ ] **Step 4: Run the focused tests and verify they fail because the job module does not exist.**

### Task 2: Implement the job package and state machine

**Files:**
- Create: `src/ercot_game/evaluation_jobs.py`

- [ ] **Step 1: Define `JobState`, `JOB_SCHEMA_VERSION`, `ARTIFACT_FORMAT_VERSION`, and allowed transitions.**
- [ ] **Step 2: Implement stable scenario/source hashing and manifest construction.**
- [ ] **Step 3: Implement `LocalEvaluationJobStore` with JSON-backed job state.**

### Task 3: Implement the local worker and artifact validation

**Files:**
- Modify: `src/ercot_game/evaluation_jobs.py`
- Modify: `src/ercot_game/__init__.py` only if public exports are needed

- [ ] **Step 1: Implement package creation using `build_batch_input`.**
- [ ] **Step 2: Implement `run_local_job` using `evaluate_locked_round` without duplicating evaluator logic.**
- [ ] **Step 3: Verify scenario, evaluator, policy, Planning Model, batch, and output hashes before artifact ingestion.**
- [ ] **Step 4: Make successful reruns return the existing artifact without creating a second semantic result.**
- [ ] **Step 5: Mark infrastructure/validation failures explicitly without publishing partial results.**

### Task 4: Document and verify Gate 4A

**Files:**
- Create: `docs/ERCOT_PHASE4A_LOCAL_JOBS.md`

- [ ] **Step 1: Document package layout, lifecycle, local commands/API, fallback boundary, and Electrify handoff.**
- [ ] **Step 2: Run focused tests and the full regression suite.**
- [ ] **Step 3: Run a real production-scenario package/replay smoke test and record hashes.**
