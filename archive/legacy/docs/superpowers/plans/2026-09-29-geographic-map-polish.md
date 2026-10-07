# Geographic Map and Schematic Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dependency-free, interactive geographic ERCOT view below the schematic map while centering, shrinking, and thinning the existing schematic visualization.

**Architecture:** Keep one scenario model and one resource interaction path. Render the existing topology view from `renderMap()` and add a second SVG renderer for the same buses, corridors, footprint, and zones; both renderers call the existing tooltip/drawer handlers. Store only geographic viewport state in the browser, and apply it as an SVG transform so the scenario and evaluator payload remain unchanged.

**Tech Stack:** Static HTML, CSS, vanilla browser JavaScript, SVG, pytest source-contract tests, local Python practice server.

---

### Task 1: Add the geographic map markup and test contracts

**Files:**
- Modify: `web/index.html:26-61`
- Modify: `tests/test_web_assets.py` in the map landmark tests

- [ ] **Step 1: Write the failing source-contract assertions**

Extend `test_web_source_files_contain_practice_interface_landmarks()` with assertions for:

```python
assert 'id="geographic-map-panel"' in html
assert 'id="geographic-map"' in html
assert 'id="geographic-map-viewport"' in html
assert 'id="geographic-zoom-in"' in html
assert 'id="geographic-zoom-out"' in html
assert 'id="geographic-reset"' in html
assert 'Read-only geographic locator' in html
```

Extend `test_map_first_source_has_period_layers_tooltips_and_accessible_drawer()` with:

```python
assert 'aria-label="Geographic map controls"' in html
assert 'role="group" aria-labelledby="geographic-map-title geographic-map-description"' in html
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `pytest tests/test_web_assets.py -q`

Expected: FAIL because the geographic panel and controls do not yet exist.

- [ ] **Step 3: Add the semantic geographic panel below the schematic map**

In `web/index.html`, place a new `<section id="geographic-map-panel" class="geographic-map-panel">` immediately after the existing schematic `.map-frame` and before the shared legend. Include:

```html
<div class="panel-heading geographic-map-heading">
  <div>
    <p class="eyebrow">Geographic locator</p>
    <h3>ERCOT region view</h3>
  </div>
  <div class="geographic-map-actions" aria-label="Geographic map controls">
    <button id="geographic-zoom-in" class="secondary-button" type="button" aria-label="Zoom in geographic map">+</button>
    <button id="geographic-zoom-out" class="secondary-button" type="button" aria-label="Zoom out geographic map">−</button>
    <button id="geographic-reset" class="secondary-button" type="button">Reset view</button>
  </div>
</div>
<p class="field-help">Read-only geographic locator: drag or zoom to see where teaching buses and corridors sit in ERCOT. Use the schematic above to reason about topology and shared paths.</p>
<div id="geographic-map-frame" class="geographic-map-frame">
  <svg id="geographic-map" viewBox="0 0 960 500" role="group" aria-labelledby="geographic-map-title geographic-map-description" tabindex="0">
    <title id="geographic-map-title">Geographic ERCOT teaching-region map</title>
    <desc id="geographic-map-description">A read-only geographic view of the teaching buses, zones, corridors, and ERCOT footprint.</desc>
    <g id="geographic-map-viewport">
      <g id="geographic-grid-layer" aria-hidden="true"></g>
      <g id="geographic-footprint-layer" role="group" aria-label="ERCOT geographic footprint"></g>
      <g id="geographic-zones-layer" role="group" aria-label="Geographic teaching zones"></g>
      <g id="geographic-corridors-layer" role="group" aria-label="Geographic transmission corridors"></g>
      <g id="geographic-buses-layer" role="group" aria-label="Geographic candidate buses"></g>
    </g>
  </svg>
</div>
```

- [ ] **Step 4: Run the focused tests and confirm they pass**

Run: `pytest tests/test_web_assets.py -q`

Expected: PASS for the new markup assertions; existing JavaScript-function assertions may still pass before the renderer is added because they do not yet require it.

### Task 2: Implement shared geographic rendering and viewport navigation

**Files:**
- Modify: `web/app.js` near the existing map state, projection helpers, and `renderMap()`
- Modify: `tests/test_web_assets.py` in map source-contract tests

- [ ] **Step 1: Add failing source-contract assertions for the renderer and controls**

Add to `test_map_first_source_has_period_layers_tooltips_and_accessible_drawer()`:

```python
assert "function renderGeographicMap" in javascript
assert "function setGeographicZoom" in javascript
assert "function resetGeographicViewport" in javascript
assert "pointerdown" in javascript
assert "geographic-zoom-in" in javascript
assert "geographic-reset" in javascript
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `pytest tests/test_web_assets.py::test_map_first_source_has_period_layers_tooltips_and_accessible_drawer -q`

Expected: FAIL on the missing geographic renderer/control hooks.

- [ ] **Step 3: Add bounded geographic viewport state and coordinate helpers**

Extend the top-level `state` object with:

```javascript
geographicZoom: 1,
geographicPan: { x: 0, y: 0 },
geographicDrag: null,
```

Add constants for the geographic SVG viewport (`width: 960`, `height: 500`) and functions:

```javascript
function geographicTransform() {
  const { x, y } = state.geographicPan;
  return `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${state.geographicZoom.toFixed(3)})`;
}

function setGeographicZoom(nextZoom, anchor = { x: 480, y: 250 }) {
  const previous = state.geographicZoom;
  const zoom = Math.min(3.2, Math.max(1, nextZoom));
  const scale = zoom / previous;
  state.geographicPan = {
    x: anchor.x - (anchor.x - state.geographicPan.x) * scale,
    y: anchor.y - (anchor.y - state.geographicPan.y) * scale,
  };
  state.geographicZoom = zoom;
  renderGeographicMap();
}

function resetGeographicViewport() {
  state.geographicZoom = 1;
  state.geographicPan = { x: 0, y: 0 };
  renderGeographicMap();
}
```

Clamp pan values to the rendered frame after zoom/drag so the map cannot be dragged permanently out of view.

- [ ] **Step 4: Implement `renderGeographicMap()` using the scenario’s existing geometry**

Reuse `busPoint()`, `corridorPath()`, `polygonRings()`, `mapBounds()`, `projectPoint()`, `bindingResourceIds()`, `headroomClass()`, and `resourceEventHandlers()`. Clear the geographic layers, set `geographic-map-viewport`’s transform, and render:

```javascript
function renderGeographicMap() {
  if (!state.scenario) return;
  const viewport = $("geographic-map-viewport");
  if (!viewport) return;
  viewport.setAttribute("transform", geographicTransform());
  ["geographic-grid-layer", "geographic-footprint-layer", "geographic-zones-layer", "geographic-corridors-layer", "geographic-buses-layer"].map($).forEach((layer) => layer?.replaceChildren());
  // Use mapBounds() and projectPoint() with a frame of x=55, y=40, width=850, height=410.
  // Render the footprint and zone labels, then corridors and buses with the same resource ids/classes.
  // Every corridor and bus must call resourceEventHandlers() so hover/focus/click stays synchronized with the drawer.
}
```

Geographic strokes should be visually lighter than the schematic, but retain `is-binding`, `is-selected`, and headroom classes so period changes and evaluator results remain understandable.

- [ ] **Step 5: Wire zoom, reset, wheel, and pointer drag interactions**

Add `setupGeographicMapControls()` and call it once during initialization. Wire the three buttons, `wheel` on `#geographic-map` with `preventDefault()` and an SVG-local anchor, and pointer events:

```javascript
map.addEventListener("pointerdown", beginGeographicDrag);
map.addEventListener("pointermove", continueGeographicDrag);
map.addEventListener("pointerup", endGeographicDrag);
map.addEventListener("pointercancel", endGeographicDrag);
```

Ignore drag start when the target is an interactive bus/corridor, retain keyboard focus on buttons, and set `aria-label`/`title` text for the controls.

- [ ] **Step 6: Render both maps whenever the scenario or period changes**

Call `renderGeographicMap()` after `renderMap()` in the existing scenario-loading and period-change paths. When a new scenario is loaded, call `resetGeographicViewport()` before the first render so stale pan/zoom state cannot carry across scenarios. Preserve `state.selectedResource` and the shared period selector behavior.

- [ ] **Step 7: Run focused tests and confirm they pass**

Run: `pytest tests/test_web_assets.py -q`

Expected: PASS.

### Task 3: Polish scale, centering, and responsive styling

**Files:**
- Modify: `web/styles.css` map rules and responsive rules
- Modify: `tests/test_web_assets.py` with scale/style contracts

- [ ] **Step 1: Add failing style-contract assertions**

Add a test such as:

```python
def test_source_has_centered_schematic_and_geographic_map_styles():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    assert ".map-frame" in css and "margin-inline:auto" in css
    assert ".geographic-map-frame" in css
    assert ".geographic-map-actions" in css
    assert ".map-corridor{fill:none;stroke:" in css
```

- [ ] **Step 2: Run the style test and confirm it fails**

Run: `pytest tests/test_web_assets.py::test_source_has_centered_schematic_and_geographic_map_styles -q`

Expected: FAIL because the new geographic styles and centered map rule are absent.

- [ ] **Step 3: Update schematic sizing and centering**

Adjust the existing CSS so the schematic map is centered and visually lighter:

```css
.map-frame { margin-inline: auto; width: min(100%, 1120px); }
#ercot-map { max-width: 100%; margin-inline: auto; }
.map-corridor { stroke-width: 3px; }
.map-corridor:hover, .map-corridor:focus { stroke-width: 5px; }
.map-corridor.is-binding { stroke-width: 6px; }
.map-corridor.is-selected { stroke-width: 7px; }
.map-zone-label, .map-corridor-label { font-size: 10px; }
.bus-label { font-size: 10px; stroke-width: 3px; }
```

Keep hit areas unchanged so smaller labels and thinner visual strokes do not reduce accessibility or clickability.

- [ ] **Step 4: Add geographic map styling and responsive behavior**

Add styles for `.geographic-map-panel`, `.geographic-map-heading`, `.geographic-map-actions`, `.geographic-map-frame`, `#geographic-map`, `.geographic-map-frame.is-dragging`, and geographic SVG classes. The map frame should have `touch-action: none`, a bounded height, a subtle background, and horizontal overflow protection. On screens below 620px, stack the action buttons and reduce the geographic map minimum height without hiding controls.

- [ ] **Step 5: Run focused tests and confirm they pass**

Run: `pytest tests/test_web_assets.py -q`

Expected: PASS.

### Task 4: Verify behavior end-to-end

**Files:**
- Modify: `tests/test_web_assets.py` only if verification exposes a missing stable source contract

- [ ] **Step 1: Run the complete automated suite**

Run: `pytest -q`

Expected: all existing evaluator, server, serialization, documentation, and web asset tests pass.

- [ ] **Step 2: Start the local practice server**

Run: `PYTHONPATH=src python -m ercot_game.practice_server --host 127.0.0.1 --port 8010`

Expected: the server listens on `http://127.0.0.1:8010/`.

- [ ] **Step 3: Browser-smoke the two-map workflow**

Open `http://127.0.0.1:8010/` and verify:

1. The schematic SVG is centered, labels are smaller, and corridors are visibly thinner.
2. The geographic ERCOT panel appears below it with footprint, zones, buses, and corridors.
3. Zoom in, zoom out, reset, wheel zoom, and pointer drag update only the geographic view.
4. Hover/focus/click on a geographic bus or corridor updates the shared tooltip and resource drawer.
5. Changing the period updates both maps while preserving the viewport until reset or a new scenario load.
6. Running a feasible and infeasible evaluation preserves all existing result behavior.
7. The browser console has no errors or warnings.

- [ ] **Step 4: Record final verification evidence**

Capture the final `pytest -q` result and browser smoke result in the completion response, including any browser-only limitation that cannot be represented by source-contract tests.
