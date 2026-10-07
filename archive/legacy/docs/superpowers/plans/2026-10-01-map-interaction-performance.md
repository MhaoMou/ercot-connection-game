# ERCOT Map Interaction Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Planning Region and Planning Interface selection update the drawer and map selection state without reconstructing static, public, or county SVG layers.

**Architecture:** Keep the existing public data and projection model. Split geographic rendering into a cached full render for data/viewport changes and a cheap interaction-state update for selection and binding classes. Keep the schematic map behavior intact while replacing selection-triggered full redraws with DOM lookup updates.

**Tech Stack:** Existing browser JavaScript, SVG, Python pytest/static source-contract tests, browser performance APIs.

---

### Task 1: Establish regression contracts

**Files:**
- Create: `tests/test_map_interaction_performance.py`
- Test: `tests/test_map_interaction_performance.py`

- [ ] **Step 1: Write failing source-contract tests** for selection not calling `renderMap`, incremental lookup maps, metrics, and documentation.
- [ ] **Step 2: Run the focused tests and confirm they fail against the monolithic renderer.**

### Task 2: Add renderer caches and metrics

**Files:**
- Modify: `web/app.js`

- [ ] **Step 1: Add development-visible `state.publicMetrics` counters and geographic layer cache state.**
- [ ] **Step 2: Add timing counters around public candidates, counties, public rendering, planning rendering, full geographic rendering, and selection updates.**

### Task 3: Separate full geographic rendering from interaction updates

**Files:**
- Modify: `web/app.js`

- [ ] **Step 1: Preserve static/base/public SVG nodes across selection-only updates.**
- [ ] **Step 2: Store Planning Region/Interface DOM elements in lookup maps while rendering them.**
- [ ] **Step 3: Implement incremental selected and binding class/ARIA updates for both schematic and geographic maps.**
- [ ] **Step 4: Make `openResourceDrawer`, close-drawer, and `focusResource` use the cheap interaction path.**

### Task 4: Verify behavior and measure performance

**Files:**
- Modify: `docs/ERCOT_MAP_PERFORMANCE.md`

- [ ] **Step 1: Run focused tests, full regression tests, and browser checks for selection, interface selection, drawer close/reopen, binding navigation, and zero network requests.**
- [ ] **Step 2: Record before/after timings, render counters, initial-load timings, and pan/zoom/toggle observations.**
- [ ] **Step 3: Document remaining bottlenecks and explicitly distinguish initial-load costs from selection latency.**
