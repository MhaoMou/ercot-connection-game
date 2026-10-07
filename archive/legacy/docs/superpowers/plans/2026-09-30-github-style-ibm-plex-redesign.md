# GitHub-Style IBM Plex Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the ERCOT teaching interface with a light GitHub Primer-inspired visual system and locally bundled IBM Plex typography without changing application behavior.

**Architecture:** Keep the existing HTML structure, JavaScript behavior, SVG map, and API contracts. Add local IBM Plex font assets and use a focused CSS token/override layer to replace the green-heavy palette, excessive shadows, large radii, and oversized typography with neutral surfaces, blue actions, semantic states, and compact spacing. Extend source-contract tests to protect the visual system and existing map structure.

**Tech Stack:** Static HTML, vanilla CSS, local WOFF2 font assets, existing vanilla JavaScript/SVG, pytest source-contract tests, local browser preview.

---

### Task 1: Add failing visual-system contract tests

**Files:**
- Modify: `tests/test_web_assets.py` near existing web asset/style contract tests
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write the failing assertions**

Add a focused test that requires:

```python
assert 'font-family: "IBM Plex Sans"' in css or "font-family:'IBM Plex Sans'" in css
assert "@font-face" in css
assert "--font-mono" in css
assert "--accent-blue" in css
assert "#0969da" in css
assert "--shadow: none" in css or "box-shadow:none" in css
assert "IBM Plex Sans" in html or "IBM Plex Sans" in css
```

Add assertions that the geographic map IDs and `geographic-map-viewport` remain present and that the legacy schematic `#map-frame` remains hidden.

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run:

```bash
pytest -q tests/test_web_assets.py -k "visual_system or geographic_map_markup"
```

Expected: the new visual-system test fails because the current stylesheet still uses the old green-heavy tokens and does not define local IBM Plex fonts.

### Task 2: Add local IBM Plex font assets and declarations

**Files:**
- Create: `web/fonts/IBMPlexSans-Regular.woff2`
- Create: `web/fonts/IBMPlexSans-SemiBold.woff2`
- Create: `web/fonts/IBMPlexMono-Regular.woff2`
- Modify: `web/styles.css` at the root token/declaration section
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Obtain the official open-source WOFF2 files**

Download the regular and semibold IBM Plex Sans files and regular IBM Plex Mono file from the official IBM Plex package/repository into `web/fonts/`. Verify each file exists and is non-empty before using it.

- [ ] **Step 2: Add `@font-face` declarations and fallback stacks**

Add declarations with `font-display: swap` and these stacks:

```css
:root {
  --font-sans: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "IBM Plex Mono", Menlo, Consolas, monospace;
}

@font-face {
  font-family: "IBM Plex Sans";
  src: url("/fonts/IBMPlexSans-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: "IBM Plex Sans";
  src: url("/fonts/IBMPlexSans-SemiBold.woff2") format("woff2");
  font-weight: 600;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: "IBM Plex Mono";
  src: url("/fonts/IBMPlexMono-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
```

- [ ] **Step 3: Add asset and fallback tests**

Assert that the three font files exist, have non-zero size, that the CSS references all three paths, and that the root `font-family` uses `var(--font-sans)`.

- [ ] **Step 4: Run the focused tests**

Run:

```bash
pytest -q tests/test_web_assets.py -k "visual_system or web_asset"
```

Expected: all font and asset contract tests pass.

### Task 3: Replace the visual tokens and component styling

**Files:**
- Modify: `web/styles.css`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Replace the root design tokens**

Use semantic tokens with a GitHub-like light palette:

```css
:root {
  --ink: #1f2328;
  --muted: #656d76;
  --paper: #f6f8fa;
  --panel: #ffffff;
  --line: #d0d7de;
  --accent-blue: #0969da;
  --accent-blue-dark: #0550ae;
  --accent-blue-soft: #ddf4ff;
  --success: #1a7f37;
  --warning: #9a6700;
  --danger: #cf222e;
  --orange: #bc4c00;
  --red: #cf222e;
  --yellow: #bf8700;
  --shadow: none;
  --radius-sm: 6px;
  --radius-md: 8px;
  --font-sans: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "IBM Plex Mono", Menlo, Consolas, monospace;
}
```

Keep aliases needed by existing selectors, such as `--teal`, `--teal-dark`, and `--teal-soft`, mapped to the new blue tokens until all dependent rules are migrated.

- [ ] **Step 2: Flatten the global shell and panels**

Set `body` to `var(--paper)`, use `var(--font-sans)`, reduce the header title scale, remove the large panel shadow, reduce panel radius to `var(--radius-md)`, and use 1px neutral borders. Preserve the current max width and responsive breakpoints.

- [ ] **Step 3: Restyle controls and statuses**

Use blue primary buttons, neutral outlined secondary buttons, white inputs with `var(--line)` borders, compact control heights, and a blue 2px focus ring. Map `.status-banner`, `.notice`, `.pill-success`, `.pill-danger`, and related states to semantic tokens with readable text contrast.

- [ ] **Step 4: Reduce nested-card density**

Flatten `.guidance-grid`, `.fieldset-block`, `.repeatable-card`, `.diagnostic-card`, `.round-summary`, and `.resource-drawer` by reducing background tint, shadow, padding, and radius while keeping section boundaries visible through borders and spacing.

- [ ] **Step 5: Apply monospace selectively**

Use `var(--font-mono)` for IDs, metric values, raw diagnostics, leaderboard identifiers, bus/corridor labels where helpful, and numeric input values. Keep instructional prose and headings in IBM Plex Sans.

- [ ] **Step 6: Preserve the map hierarchy**

Keep the current dark geographic context and Texas highlight. Restyle only the surrounding map frame, legend, drawer, and controls so the map remains prominent without reintroducing the old green-heavy page chrome.

- [ ] **Step 7: Run the focused tests**

Run:

```bash
pytest -q tests/test_web_assets.py -k "visual_system or geographic"
```

Expected: all visual-system and geographic structure tests pass.

### Task 4: Verify static assets, responsive behavior, and the full application

**Files:**
- Modify: `tests/test_web_assets.py` only if a verified regression case is missing

- [ ] **Step 1: Verify font asset routes**

Confirm the static server allows the three font files and rejects unknown assets as before.

- [ ] **Step 2: Perform browser visual QA**

Refresh `http://127.0.0.1:8000/` and verify the IBM Plex typography, neutral GitHub-like palette, flatter panels, compact controls, semantic statuses, and readable map frame.

- [ ] **Step 3: Exercise behavior**

Verify period selection, map zoom/pan/reset, bus and corridor hover/focus, resource drawer selection, connection/generator cards, validation messages, and classroom panels remain functional.

- [ ] **Step 4: Check narrow layout and focus states**

Inspect the page at narrow width and with keyboard navigation. Confirm no horizontal overflow, readable help text, visible focus rings, and usable controls.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: all tests pass with no API, evaluator, scenario, or classroom regressions.

## File map

- `web/fonts/`: locally served IBM Plex WOFF2 assets.
- `web/styles.css`: font declarations, semantic palette, spacing, borders, controls, panels, and responsive overrides.
- `tests/test_web_assets.py`: visual-system, font asset, and map-preservation contracts.
