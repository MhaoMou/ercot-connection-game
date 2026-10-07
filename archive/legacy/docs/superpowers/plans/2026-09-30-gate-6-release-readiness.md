# Gate 6 Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit and harden the current ERCOT instructional planning application for student/instructor release without changing the Planning Model V1, Teaching Scenario V2, or evaluator mathematics.

**Architecture:** Keep the existing public-network, planning-model, teaching-scenario separation. Make only presentation, terminology, documentation, deployment-hygiene, and test changes that address observed release risks. Record every unverified viewport or workflow explicitly instead of inferring a pass.

**Tech Stack:** Python 3.11+, stdlib HTTP server, vanilla HTML/CSS/JavaScript, pytest, local browser automation.

---

### Task 1: Establish Gate 6 evidence and focused regression coverage

**Files:**
- Create: `tests/test_gate6_release_readiness.py`
- Inspect: `web/index.html`, `web/app.js`, `src/ercot_game/practice_server.py`, `README.md`

- [ ] **Step 1: Add focused assertions for the release mental model and relative asset paths.**
- [ ] **Step 2: Run the focused tests and confirm they fail against the current stale tooltip/disclosure text.**
- [ ] **Step 3: Keep the test assertions limited to production-facing planning-mode behavior; do not assert away legacy fixtures or evaluator field names.**

### Task 2: Fix concrete production-facing terminology and first-screen disclosure

**Files:**
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/styles.css` only if the new concise disclosure needs existing layout support
- Test: `tests/test_gate6_release_readiness.py`

- [ ] **Step 1: Make planning-mode map tooltips say Planning Region / Planning Interface and distinguish scenario values from public geography.**
- [ ] **Step 2: Add a concise visible public-data-informed disclosure that explains Public Network → Planning Model → Teaching Scenario without exposing Gate/development history.**
- [ ] **Step 3: Keep the deeper HIFLD/EIA provenance and limitations behind the existing About network data disclosure.**
- [ ] **Step 4: Run the focused tests and a browser smoke check for the updated text.**

### Task 3: Release audit of interaction, accessibility, responsiveness, and performance

**Files:**
- Create: `docs/ERCOT_RELEASE_READINESS.md`
- Inspect: `web/styles.css`, `web/app.js`, `web/index.html`

- [ ] **Step 1: Exercise default map layers, all 12 regions, all 20 interfaces, selection/binding states, repeated zoom/pan/reset, and layer toggles in the live browser.**
- [ ] **Step 2: Exercise feasible, infeasible, region-bound, and interface-bound result explanations.**
- [ ] **Step 3: Exercise Classroom through its implemented service workflow and use automated tests for supported persistence/version behavior.**
- [ ] **Step 4: Check browser console, request paths, generated asset availability, SVG symbol references, focusable controls, and public SVG element counts.**
- [ ] **Step 5: Record desktop/tablet/mobile results honestly; mark any viewport unavailable in the browser environment as NOT VERIFIED.**

### Task 4: Documentation, instructor/student notes, reproducibility, and hygiene

**Files:**
- Create: `docs/ERCOT_INSTRUCTOR_RELEASE_NOTE.md`
- Create: `docs/ERCOT_STUDENT_QUICKSTART.md`
- Modify: `README.md`
- Inspect: `data/`, `tools/`, `docs/`, `web/`

- [ ] **Step 1: Update README setup/default-scenario documentation to identify the production Teaching Scenario V2 path and explicit legacy fixture isolation.**
- [ ] **Step 2: Add concise instructor and student notes with the real/public, derived, and instructional boundaries.**
- [ ] **Step 3: Run the deterministic generation/audit smoke checks and record artifact status and hashes where available.**
- [ ] **Step 4: Record repository hygiene and security findings without deleting provenance-critical data.**

### Task 5: Full verification and final decision

**Files:**
- Inspect: all files changed above

- [ ] **Step 1: Run focused Gate 6 tests.**
- [ ] **Step 2: Run the full pytest suite with local socket permission for HTTP tests.**
- [ ] **Step 3: Re-run browser smoke checks after the final source state and inspect console logs.**
- [ ] **Step 4: Apply the release decision: RELEASE READY, RELEASE READY WITH KNOWN LIMITATIONS, or NOT RELEASE READY.**
- [ ] **Step 5: Report all P0/P1/P2 findings and explicit unverified areas in `docs/ERCOT_RELEASE_READINESS.md`.**

