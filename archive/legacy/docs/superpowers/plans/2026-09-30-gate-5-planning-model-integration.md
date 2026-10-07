# Gate 5 ERCOT Planning Model Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the approved Gate 4.6 regional artifact into a versioned ERCOT planning model, derive a separate instructional teaching scenario, and integrate both with the existing evaluator and web application without changing evaluator mathematics.

**Architecture:** A versioned public planning artifact contains only derived planning regions, interfaces, anchors, geometry, and provenance. A separate versioned teaching scenario joins that model to deterministic instructional limits, prices, and evaluation configuration. A Python adapter validates the join and emits the existing generic `Scenario` shape so evaluator equations remain unchanged.

**Tech Stack:** Python 3.12+, JSON artifacts, existing evaluator/server, pytest, existing SVG/map frontend.

---

### Task 1: Record the evaluator compatibility boundary

**Files:**
- Create: `docs/ERCOT_PLANNING_MODEL_GATE5.md`
- Test: `tests/test_gate5_planning_model.py`

- [ ] Write tests asserting the report names the three-layer architecture, evaluator compatibility decision, stable planning terminology, provenance requirements, and the hard-stop condition.
- [ ] Run the focused test and confirm it fails because the report does not exist.
- [ ] Write the Gate 5 report with a compatibility table showing planning regions/interfaces adapt to legacy evaluator buses/corridors, while no evaluator equation or recourse rule changes.
- [ ] Run the focused test and confirm it passes.

### Task 2: Promote the frozen Gate 4.6 planning artifact

**Files:**
- Create: `tools/ercot_reduced_network/promote.py`
- Create: `data/processed/ercot_planning_model_v1.json`
- Test: `tests/test_gate5_planning_model.py`

- [ ] Add a deterministic promoter that reads `data/processed/reduced/candidate_12_v2.json`, verifies its Gate 4.6 identity/counts, adds stable `model_id`, `model_version`, schema, source artifact, and provenance fields, and writes sorted JSON.
- [ ] Run the promoter to generate the production-facing artifact without changing Gate 4.6 geometry or IDs.
- [ ] Add tests for 12 regions, 20 interfaces, stable versions, absence of teaching capacities/limits, and preserved source provenance.

### Task 3: Build the versioned teaching scenario and adapter

**Files:**
- Create: `tools/ercot_reduced_network/build_teaching_scenario.py`
- Create: `data/teaching/ercot_connection_scenario_v2.json`
- Create: `src/ercot_game/planning_adapter.py`
- Test: `tests/test_gate5_planning_model.py`

- [ ] Write failing tests for model/scenario version matching, deterministic teaching parameters, planning-region/interface conversion to the existing `Scenario`, and preservation of map presentation metadata.
- [ ] Implement deterministic evidence-informed calibration from the public artifact’s geometry, branch voltage/count evidence, plant/generator evidence, and explicit instructional modifiers. Keep values clearly instructional and separate from public physical data.
- [ ] Generate the scenario with six periods, prices/IT values, evaluator configuration, region headroom, interface capacity, student-generator policy, calibration provenance, and model reference.
- [ ] Implement adapter loading and validation; return the legacy `Scenario` with planning IDs and presentation aliases, without modifying evaluator functions.
- [ ] Run focused tests and then existing evaluator tests.

### Task 4: Make the practice server use the production teaching scenario

**Files:**
- Modify: `src/ercot_game/practice_server.py`
- Modify: `src/ercot_game/practice_serialization.py`
- Modify: `src/ercot_game/cli.py`
- Test: `tests/test_gate5_planning_model.py`, `tests/test_practice_server.py`

- [ ] Add explicit production teaching-model loading while preserving `--scenario` fixture loading for tests and legacy/debug use.
- [ ] Make the no-argument server default load the versioned teaching scenario through the adapter.
- [ ] Add `planning_model`, `planning_regions`, and `planning_interfaces` response fields while retaining `buses` and `corridors` compatibility fields.
- [ ] Add a non-user-facing debug path for the old synthetic fixture; do not expose two competing ordinary-user networks.
- [ ] Verify API responses and existing fixture-based server tests.

### Task 5: Add versioned canonical plan fields and safe migration

**Files:**
- Modify: `src/ercot_game/io.py`
- Modify: `src/ercot_game/practice_server.py`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Test: `tests/test_gate5_planning_model.py`, `tests/test_models_and_io.py`, `tests/test_web_assets.py`

- [ ] Add `plan_schema_version`, `planning_model_version`, `connection_region_id`, and `planning_interface_ids` as canonical external fields.
- [ ] Require explicit version metadata for new planning plans; retain old `bus_id/path_corridors` only as explicit legacy compatibility, never silently reinterpret them.
- [ ] Normalize new fields at the adapter boundary into existing evaluator `bus_id/path_corridors` fields.
- [ ] Update visible labels/help/map payloads to Planning Region, Connection Region, and Planning Interface while preserving DOM IDs, selectors, accessible names, and event wiring.
- [ ] Keep canonical plans and stored round data versioned so old plans cannot silently reinterpret.

### Task 6: Integrate the planning map layer and retire ordinary synthetic exposure

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Test: `tests/test_web_assets.py`

- [ ] Add planning-region, planning-interface, and planning-anchor rendering using the production response fields; subdue public transmission and preserve geographic projection/zoom/pan/reset.
- [ ] Keep old synthetic map rendering available only through the debug path until migration tests pass, then remove it from ordinary UI controls.
- [ ] Preserve resource selection, Map→Plan, Evaluation→Map, and accessibility behavior.
- [ ] Verify static asset serving and browser smoke behavior where available.

### Task 7: Regression audit and Gate 5 handoff

**Files:**
- Modify: `docs/ERCOT_PLANNING_MODEL_GATE5.md`
- Test: full existing suite plus Gate 5 tests

- [ ] Run targeted Gate 5 tests, evaluator tests, server tests, web asset tests, and the full suite.
- [ ] Verify scenario loading, period selection, map interactions, plan CRUD, generators, validation, evaluation, stale-result handling, classroom behavior, and legacy fixture compatibility.
- [ ] Record exact commands/results and any browser-only behavior that could not be verified.
- [ ] Stop and report if evaluator semantics prove incompatible; do not redesign evaluator math in this gate.
