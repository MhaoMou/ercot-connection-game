# Academic GitHub-Style Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task.

**Goal:** Redesign the ERCOT teaching interface as compact academic/scientific software with GitHub-style information architecture while preserving all existing map, evaluator, classroom, validation, API, and accessibility behavior.

**Architecture:** Keep the current server-rendered HTML, single `app.js`, and local static assets. Add in-page navigation and semantic layout wrappers without renaming JavaScript-facing IDs or dynamic classes. Consolidate the stylesheet into one ordered design system, add local Source Serif 4 assets, and limit JavaScript changes to navigation highlighting and dynamic header metadata if needed.

**Tech Stack:** Existing HTML5, CSS, vanilla JavaScript, Python static server, local WOFF2 fonts, pytest asset/API regression tests.

---

### Task 1: Establish preserved contracts and design-system tests

**Files:**
- Modify: `tests/test_web_assets.py`
- Inspect: `web/index.html`, `web/app.js`, `web/styles.css`

- [ ] Add tests that require the four in-page navigation targets, compact academic header metadata, local Source Serif 4 font declarations/assets, and preservation of all existing map/form/classroom IDs.
- [ ] Add tests that assert the geographic map remains present exactly once, the legacy schematic map remains hidden, and the navigation uses anchors rather than SPA tab panels.
- [ ] Run the focused web tests and confirm the new contracts fail before implementation.

### Task 2: Add local academic typography assets and server routes

**Files:**
- Create: `web/fonts/SourceSerif4-Regular.woff2`
- Create: `web/fonts/SourceSerif4-SemiBold.woff2`
- Modify: `src/ercot_game/practice_server.py`
- Modify: `docs/phase-2-practice-interface.md`

- [ ] Add the two local Source Serif 4 files and serve them through the existing static asset route.
- [ ] Keep IBM Plex Sans and IBM Plex Mono routes unchanged.
- [ ] Document the new font routes and verify successful HTTP responses and non-empty bodies.

### Task 3: Add compact application header and section navigation

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js` only if navigation highlighting needs event handling
- Modify: `web/styles.css`

- [ ] Replace the landing-style header copy with a compact title, subtitle, and dynamic scenario metadata container while preserving `practice-disclaimer` and `status-banner` IDs.
- [ ] Add a horizontal navigation row with anchors to Network, Plan, Evaluation, and Classroom sections. Use `aria-current`, keyboard focus, horizontal overflow on mobile, and IntersectionObserver-based active highlighting without hiding sections.
- [ ] Keep Classroom visually secondary when the round panel is hidden in Practice mode.

### Task 4: Recompose Network layout around the geographic map

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`

- [ ] Add a stable Network anchor to the existing map panel without renaming map IDs or layers.
- [ ] On wide screens, use a 70–75% geographic map region and a 25–30% technical selected-resource panel where the existing structure allows it; on narrow screens, stack them.
- [ ] Keep period selection, zoom/pan/reset controls, map legend, tooltip behavior, bus/corridor interaction, and geographic map SVG unchanged.
- [ ] Convert repeated instructional blocks into compact documentation callouts while retaining their text and accessible descriptions.

### Task 5: Refine Plan editor and technical details

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`

- [ ] Add the Plan anchor and compact settings-style team-parameter layout while preserving input IDs, labels, units, range help, and validation targets.
- [ ] Style dynamically generated connection and generator cards as readable configuration rows with visible IDs, bus/site relationships, capacity, profiles, corridor choices, actions, and error messages.
- [ ] Use IBM Plex Mono for technical identifiers, numerical values, costs, and raw diagnostics; retain IBM Plex Sans for controls and labels.

### Task 6: Establish strict Evaluation hierarchy

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`

- [ ] Add the Evaluation anchor and order visible result content as feasibility, total score, primary physical/economic metrics, detailed diagnostics, then raw server response.
- [ ] Preserve all result IDs used by `app.js`, including score, allocation, curtailment, revenue, feasibility, diagnostics, evaluation identity, notes, and raw response.
- [ ] Use text plus border/icon treatment for feasible, infeasible, warning, informational, and neutral states; do not rely on color alone.

### Task 7: Regression and browser audit

**Files:**
- Modify: `tests/test_web_assets.py` only for discovered contract gaps

- [ ] Run focused web/font/static-route tests.
- [ ] Run the complete pytest suite with local socket binding enabled.
- [ ] Use the existing live browser to verify desktop and narrow layouts, section navigation, active highlighting, map controls and selection, plan editing/validation, evaluation rendering, and Practice-mode classroom visibility.
- [ ] Report any behavior that cannot be verified rather than changing application logic to accommodate the audit.

### Task 8: Final review and documentation

**Files:**
- Modify: `docs/phase-2-practice-interface.md` if UI/navigation details changed

- [ ] Review the final diff for accidental DOM-ID/class changes, duplicate CSS rules, dependency additions, or evaluation/map logic changes.
- [ ] Record the final test count and browser checks in the handoff response.
