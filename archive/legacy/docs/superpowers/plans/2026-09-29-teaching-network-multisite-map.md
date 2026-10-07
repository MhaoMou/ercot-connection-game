# Teaching-Scale ERCOT Network and Multi-Site Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace the three-bus single-site prototype with a teaching-scale ERCOT map and canonical multi-site/multi-generator evaluator and practice interface.

**Architecture:** Extend the domain model first, normalize legacy single-site plans into canonical arrays, and preserve deterministic team-level scoring while adding site/generator diagnostics. Replace the fixture with a larger schematic teaching network, then update JSON serialization/server responses and the browser UI so the map is the primary scenario surface and the editor supports repeatable connection and generator cards.

**Tech Stack:** Python 3.13 standard library, dataclasses/frozen domain models, pytest, dependency-free HTML/CSS/JavaScript, SVG map rendering.

---

## File map

- Modify `src/ercot_game/models.py`: canonical connection/generator/team-plan dataclasses and compatibility properties.
- Modify `src/ercot_game/io.py`: canonical plan/scenario serialization and semantic hashing.
- Modify `src/ercot_game/validate.py`: multi-site, generator-reference, shared-resource, and range validation.
- Modify `src/ercot_game/allocation.py`: per-site allocation with shared corridor limits.
- Modify `src/ercot_game/recourse.py`: aggregate recourse and site/generator dispatch inputs.
- Modify `src/ercot_game/scoring.py`: aggregate team score while retaining site/generator breakdowns.
- Modify `src/ercot_game/evaluator.py`: compatibility normalization, deterministic multi-site evaluation, and expanded diagnostics.
- Modify `src/ercot_game/practice_serialization.py`: JSON-safe canonical scenario/result responses.
- Modify `src/ercot_game/practice_server.py`: preserve API contracts while accepting canonical plans.
- Replace `data/fixtures/ercot_small.json`: teaching-scale buses, corridors, time series, and map presentation metadata.
- Modify `web/index.html`, `web/styles.css`, `web/app.js`: map-first interface, tooltips/drawer, period selector, repeatable site/generator editors, tutorials, and ranges.
- Modify/add `tests/test_models_and_io.py`, `tests/test_validation.py`, `tests/test_allocation.py`, `tests/test_recourse.py`, `tests/test_scoring.py`, `tests/test_evaluator.py`, `tests/test_practice_serialization.py`, `tests/test_practice_server.py`, `tests/test_web_assets.py`, and `tests/test_documentation.py`.
- Add `docs/phase-3-multiteam-handoff.md` only if the implementation needs a revised future handoff; do not claim Phase 3 is implemented.

### Task 1: Canonical domain model and compatibility normalization

**Files:**
- Modify: `src/ercot_game/models.py`, `src/ercot_game/io.py`
- Test: `tests/test_models_and_io.py`

- [ ] Write tests for `ConnectionPlan`, site-attached `GeneratorPlan`, and canonical `TeamPlan.connections`/`TeamPlan.generators` tuples.
- [ ] Write tests that legacy `{bus_id, path_corridors, capacity_mw, profile, generator}` input normalizes to one connection and zero/one generator with stable IDs.
- [ ] Implement frozen dataclasses with immutable tuples and explicit field names:

```python
@dataclass(frozen=True)
class ConnectionPlan:
    connection_id: str
    bus_id: str
    path_corridors: tuple[str, ...]
    capacity_mw: float
    profile: tuple[float, ...]

@dataclass(frozen=True)
class GeneratorPlan:
    generator_id: str
    connection_id: str
    capacity_mw: float
    marginal_cost_per_mwh: float
```

- [ ] Add `normalize_plan_payload(payload)` in `io.py`; accept canonical arrays and the legacy shorthand, reject ambiguous payloads containing conflicting legacy and canonical values, and assign deterministic compatibility IDs (`connection-legacy`, `generator-legacy`).
- [ ] Make `plan_to_dict` emit canonical arrays and retain a clearly documented compatibility view only where existing tests require it.
- [ ] Run `pytest tests/test_models_and_io.py -q` and update expected hashes only when semantic content—not presentation metadata—actually changes.

### Task 2: Multi-site validation and evaluator mechanics

**Files:**
- Modify: `src/ercot_game/validate.py`, `src/ercot_game/allocation.py`, `src/ercot_game/recourse.py`, `src/ercot_game/scoring.py`, `src/ercot_game/evaluator.py`
- Test: `tests/test_validation.py`, `tests/test_allocation.py`, `tests/test_recourse.py`, `tests/test_scoring.py`, `tests/test_evaluator.py`

- [ ] Add failing tests for empty connections, duplicate connection IDs, duplicate generator IDs, unknown buses/corridors, unknown generator connection IDs, mismatched profile lengths, negative/non-finite values, and out-of-range `curtailment_depth_mu`/budget.
- [ ] Add allocation tests proving that two sites can use different buses and that a shared corridor capacity is consumed across sites deterministically.
- [ ] Add generator tests proving multiple generators dispatch in deterministic `(marginal_cost_per_mwh, generator_id)` order and never exceed capacity or site demand.
- [ ] Implement validation so all connections reference known resources, all generators reference known connection IDs, and every time series has the scenario horizon length.
- [ ] Implement deterministic shared-corridor allocation: compute each site’s available resources, cap corridor use by the scenario’s per-period corridor capacity, and allocate remaining shared capacity in sorted `connection_id` order. Record binding and curtailed site IDs.
- [ ] Update recourse to consume aggregate site shortfalls and generator availability, dispatch generators by cost then ID, and return per-generator/per-site time series.
- [ ] Update scoring to aggregate site-level energy cost, IT value, generator cost, flexibility fee, curtailment cost, and unserved penalty without changing the meaning of the existing team total.
- [ ] Update `evaluate()` to return canonical site results, generator dispatch results, aggregate diagnostics, deterministic ordering, evaluator version bump, and semantic input hash.
- [ ] Run `pytest tests/test_validation.py tests/test_allocation.py tests/test_recourse.py tests/test_scoring.py tests/test_evaluator.py -q`.

### Task 3: Teaching-scale ERCOT fixture and map metadata

**Files:**
- Replace: `data/fixtures/ercot_small.json`
- Test: `tests/test_presentation_metadata.py`, `tests/test_models_and_io.py`, `tests/test_evaluator.py`

- [ ] Generate a deterministic fixture with 24–36 buses, 40–60 corridors, six time periods, several teaching zones, constrained and unconstrained resources, and valid nonnegative time series.
- [ ] Add schematic longitude/latitude coordinates for every bus, corridor paths with closed polygon/line semantics as required, an ERCOT footprint, and a U.S. locator inset.
- [ ] Include metadata labels/tutorial hints only in presentation fields so semantic hashes remain unchanged when map styling changes.
- [ ] Add tests asserting bus/corridor count ranges, unique IDs, valid references, horizon consistency, map geometry validity, and deterministic scenario serialization/hash.
- [ ] Run `pytest tests/test_presentation_metadata.py tests/test_models_and_io.py tests/test_evaluator.py -q`.

### Task 4: API serialization and server compatibility

**Files:**
- Modify: `src/ercot_game/practice_serialization.py`, `src/ercot_game/practice_server.py`
- Test: `tests/test_practice_serialization.py`, `tests/test_practice_server.py`

- [ ] Extend scenario responses with the larger map, zones, selected-period data, canonical bus/corridor arrays, and tutorial metadata while keeping JSON-safe primitives.
- [ ] Extend evaluation responses with canonical `connection_results`, `generator_dispatch`, site diagnostics, team totals, evaluator version, and input hash.
- [ ] Preserve malformed JSON, invalid plan, evaluator error, safe 500, request-size, immutable-state, and static-file contracts.
- [ ] Add tests for legacy and canonical request bodies, multi-site response serialization, deterministic key/order behavior, and unchanged map-independent semantic hashes.
- [ ] Run the server tests with local socket access and `pytest tests/test_practice_serialization.py tests/test_practice_server.py -q`.

### Task 5: Map-first educational interface

**Files:**
- Modify: `web/index.html`, `web/styles.css`, `web/app.js`
- Test: `tests/test_web_assets.py`

- [ ] Remove the Scenario Brief panel and make the map the primary scenario surface.
- [ ] Render all bus/corridor metadata, a U.S. locator inset, zone labels, period selector, legend, and responsive SVG layers.
- [ ] Add hover and keyboard-focus tooltips; add click/tap selection and a persistent accessible detail drawer for bus/corridor/site information.
- [ ] Add explanatory “What this means” and “How to use it” copy to the map, plan editor, generator editor, and results panel.
- [ ] Add range labels and field guidance for `K`, `μ`, profiles, capacities, fees, generator capacity, and generator cost.
- [ ] Add source-level tests for no Scenario Brief markup, map tooltips/focus handlers, period switching, detail drawer, tutorial copy, and required range text.
- [ ] Run `pytest tests/test_web_assets.py -q` and manually verify map focus, hover/tap, tooltip, drawer, and period changes in the browser.

### Task 6: Repeatable multi-site and multi-generator editor

**Files:**
- Modify: `web/index.html`, `web/styles.css`, `web/app.js`
- Test: `tests/test_web_assets.py`, `tests/test_practice_server.py`

- [ ] Replace the single connection fields with repeatable connection cards supporting add, duplicate, remove, bus selection, capacity, profile, and corridor checkboxes.
- [ ] Replace the single generator toggle with repeatable generator cards containing generator ID, connection-site selection, capacity, and marginal cost.
- [ ] Build exactly the canonical JSON shape in the browser and ensure IDs are unique, references remain valid after removal, and empty cards receive field-specific errors.
- [ ] Clear stale results on any site/generator/team-level edit and validate successful response schema before rendering.
- [ ] Add tests for multiple sites, multiple generators, duplicate IDs, invalid references, zero-site/zero-generator cases, and response rendering.
- [ ] Run the full browser/server tests with local socket access.

### Task 7: Documentation and migration handoff

**Files:**
- Modify: `README.md`, `docs/phase-1-evaluator.md`, `docs/phase-2-practice-interface.md`, `docs/phase-2-handoff.md`
- Test: `tests/test_documentation.py`

- [ ] Document canonical multi-site/multi-generator plans, legacy normalization, map interactions, tutorial panels, parameter ranges, and site/generator diagnostics.
- [ ] Explain that the larger network is a teaching abstraction and that server evaluation remains authoritative.
- [ ] Update the Phase 3 handoff with multi-team ordering, persistent rounds, instructor controls, fairness, and Gymnasium/RL wrapper implications.
- [ ] Add documentation checks for canonical field names, nested generator constraints, documented routes/commands, fixture paths, and local links.
- [ ] Run `pytest tests/test_documentation.py -q`.

### Task 8: Full verification and browser pilot checklist

**Status:** Complete. Full pytest, API pilot cases, and browser smoke verification passed after the final evaluator-version and ID-validation fixes.

**Files:**
- Test: all `tests/`
- Documentation: `docs/phase-2-practice-interface.md`

- [ ] Run `pytest -q` with local socket permissions; expected result is all tests passing.
- [ ] Start the server with the teaching fixture and verify `GET /`, `/api/scenario`, and `/api/evaluate` using a canonical multi-site plan.
- [ ] Execute five pilot plans: feasible single-site, feasible multi-site, shared-corridor congestion, multiple-generator dispatch, and invalid-reference/curtailment case.
- [ ] Verify map values, detail drawer values, diagnostics, score totals, site/generator IDs, and stale-result clearing against server JSON.
- [ ] Record any remaining usability issues in the Phase 2 handoff without expanding into multi-team persistence or RL implementation.
