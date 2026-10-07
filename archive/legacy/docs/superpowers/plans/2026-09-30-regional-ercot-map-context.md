# Regional ERCOT Map Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the geographic map's empty upper backdrop with a full regional SVG context map while keeping Texas/ERCOT highlighted and all existing interactions intact.

**Architecture:** Keep the existing single `#geographic-map` SVG and its viewport transform. Expand the geographic projection bounds to a regional extent, render a local code-native context layer first, then render the existing Texas counties, teaching footprint, corridors, and buses above it. Use CSS classes to distinguish dark surrounding context from the highlighted Texas region.

**Tech Stack:** Existing HTML, vanilla JavaScript SVG rendering, CSS, pytest source-contract tests, local browser preview.

---

### Task 1: Lock the regional map contract with tests

**Files:**
- Modify: `tests/test_web_assets.py` near the existing geographic map contract tests
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Add failing source-contract assertions**

Add assertions that the geographic map contains a regional context layer and that the source defines the regional projection and context classes. The assertions should verify:

```python
assert 'id="geographic-context-layer"' in html
assert "REGIONAL_GEOGRAPHIC_BOUNDS" in javascript
assert "geographic-regional-land" in javascript
assert ".geographic-regional-land" in css
assert javascript.index('renderGeographicBasemap') < javascript.index('renderGeographicCounties')
```

Also assert that the existing single geographic map remains present and no `geographic-grid-layer` is introduced.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pytest -q tests/test_web_assets.py -k "geographic"
```

Expected: the new regional-bound and class assertions fail because the implementation has not been added yet.

### Task 2: Expand the projection and render the regional context

**Files:**
- Modify: `web/app.js` near `TEXAS_GEOGRAPHIC_BOUNDS`, `projectGeographicPoint`, and `renderGeographicBasemap`

- [ ] **Step 1: Define explicit regional bounds and use them only for the geographic map**

Add a constant such as:

```javascript
const REGIONAL_GEOGRAPHIC_BOUNDS = {
  minLon: -109.5,
  maxLon: -88.0,
  minLat: 22.0,
  maxLat: 38.8,
};
```

Keep `TEXAS_GEOGRAPHIC_BOUNDS` available for Texas-specific reasoning, but make `projectGeographicPoint` use the regional bounds so the projection fills the full SVG viewport with equal longitude/latitude scale.

- [ ] **Step 2: Add compact local SVG geometry for regional context**

Inside `renderGeographicBasemap`, add maintainable coordinate arrays for:

- dark regional water covering the full viewport;
- neighboring U.S. states as muted land polygons;
- northern Mexico as a muted land polygon;
- Texas as the highlighted land polygon;
- subtle state/country boundary paths and regional labels.

All arrays must be in longitude/latitude coordinates and projected with the existing `project` callback. The geometry should cover the regional bounds without changing any bus or corridor coordinates.

- [ ] **Step 3: Preserve and reorder existing basemap landmarks**

Render the regional land/water geometry first, then the existing Texas outline, coast, city labels, highway guides, Gulf label, and Mexico label. Do not move counties, footprint, corridors, or buses into the context function.

- [ ] **Step 4: Run the focused tests**

Run:

```bash
pytest -q tests/test_web_assets.py -k "geographic"
```

Expected: all geographic source-contract tests pass.

### Task 3: Apply the visual hierarchy in CSS and accessible copy

**Files:**
- Modify: `web/styles.css` near the geographic map styles
- Modify: `web/index.html` in the geographic map description/help text

- [ ] **Step 1: Add regional context styles**

Add styles with these responsibilities:

```css
.geographic-regional-water { fill: #d8e3e7; }
.geographic-regional-land { fill: #718084; stroke: #aab8b9; }
.geographic-regional-land.is-texas { fill: #d9e4d7; stroke: #557c75; }
.geographic-regional-boundary { fill: none; stroke: #aebcbd; }
```

Use a contrast level that keeps surrounding regions visibly darker than Texas while retaining legibility for buses, corridors, county boundaries, and labels. Avoid adding a grid pattern.

- [ ] **Step 2: Update accessible map text**

Change the SVG description and nearby instructional copy to explain that the map shows Texas, neighboring states, northern Mexico, and the Gulf as geographic context, while the highlighted Texas layer contains the teaching resources.

- [ ] **Step 3: Run the focused tests**

Run:

```bash
pytest -q tests/test_web_assets.py -k "geographic"
```

Expected: all focused tests pass.

### Task 4: Browser visual QA and full verification

**Files:**
- Modify: `tests/test_web_assets.py` only if a verified regression case is missing

- [ ] **Step 1: Refresh the local browser preview**

Open or refresh `http://127.0.0.1:8000/` and inspect the geographic map at desktop width. Confirm the regional backdrop fills the upper panel, Texas is highlighted, Mexico and the Gulf are visible, and no second grid graph appears.

- [ ] **Step 2: Exercise interactions**

Verify zoom in, zoom out, reset, drag/pan, bus hover/focus, corridor hover/focus, and resource drawer selection. Confirm labels and bus positions remain physically consistent after zoom and pan.

- [ ] **Step 3: Check narrow layout**

Resize to a narrow/mobile width and confirm the map remains fully visible, controls remain usable, and no context layer causes horizontal overflow.

- [ ] **Step 4: Run the full test suite**

Run:

```bash
pytest -q
```

Expected: all tests pass, with the existing full-suite baseline preserved.

## File map

- `web/app.js`: projection bounds, regional SVG geometry, and rendering order.
- `web/styles.css`: dark contextual basemap, highlighted Texas, boundaries, and label contrast.
- `web/index.html`: map description and teaching copy.
- `tests/test_web_assets.py`: source-level contract for one geographic map, layer order, and regional context.
