# Cozy Pixel Semantic Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an original, reusable cozy-RPG semantic icon family to the ERCOT teaching interface without changing application behavior, accessible text, or JavaScript contracts.

**Architecture:** Define all artwork once in a hidden inline SVG `<symbol>` library using a shared 24×24 logical grid, then place decorative `<svg><use>` instances beside existing labels and actions. Keep each symbol object-specific in silhouette and palette; do not add icons to low-level utility controls. Verify definitions, references, accessibility, placements, and rendered 16px/24px readability.

**Tech Stack:** Existing HTML, CSS, vanilla JavaScript, pytest source-contract tests, inline SVG rectangles/stepped polygons.

---

## File map

- Modify `web/index.html`: add the hidden symbol library and decorative `<svg><use>` instances beside approved existing text/actions. Do not change IDs, labels, form semantics, or event hooks.
- Modify `web/styles.css`: add one authoritative semantic-icon style block for sizing, crisp rendering, alignment, and limited state treatments. Do not add animation or utility-control icon styling.
- Modify `tests/test_web_assets.py`: add source-contract tests for symbol definitions, resolved `<use>` references, approved placements, preserved accessible text, and excluded utility controls.
- Do not modify `web/app.js`: the icon system is static presentation and must not require event or selector changes.

### Task 1: Add failing source-contract tests

**Files:**
- Modify: `tests/test_web_assets.py`

- [ ] **Step 1: Add the symbol and placement contract test.**

Add a test that parses the inline HTML with regular expressions and checks the exact symbol IDs, all `<use href="#...">` references, and approved semantic placements. Use the existing `WEB_ROOT` fixture and preserve the project's dependency-free source-contract style:

```python
def test_cozy_semantic_icon_family_is_defined_and_selectively_placed():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    expected = {
        "icon-network", "icon-plan", "icon-evaluation", "icon-classroom",
        "icon-connection", "icon-generator", "icon-bus", "icon-corridor",
        "icon-help", "icon-error", "icon-success",
    }
    definitions = set(re.findall(r'<symbol[^>]+id="([^"]+)"', html))
    references = set(re.findall(r'<use[^>]+href="#([^"]+)"', html))
    assert expected <= definitions
    assert references <= definitions
    assert references

    for icon_id in expected:
        assert f'<symbol id="{icon_id}"' in html
    for action_id in ("add-connection", "add-generator", "evaluate-button", "explore-network-button"):
        assert f'id="{action_id}"' in html
    assert 'href="#icon-network"' in html
    assert 'href="#icon-plan"' in html
    assert 'href="#icon-evaluation"' in html
    assert 'href="#icon-classroom"' in html
    assert 'href="#icon-connection"' in html
    assert 'href="#icon-generator"' in html
    assert 'href="#icon-bus"' in html
    assert 'href="#icon-corridor"' in html
    assert 'href="#icon-help"' in html
    assert 'href="#icon-error"' in html
    assert 'href="#icon-success"' in html
    assert 'class="semantic-icon" aria-hidden="true"' in html
    assert '.semantic-icon' in css
    assert 'viewBox="0 0 24 24"' in html

    # The legend explains buses and corridors only; other state icons belong in
    # their actual state contexts rather than being decorative legend entries.
    legend = html.split('<div class="legend"', 1)[1].split('</div>', 1)[0]
    assert 'href="#icon-bus"' in legend
    assert 'href="#icon-corridor"' in legend
    for excluded in ("icon-help", "icon-error", "icon-success"):
        assert f'href="#{excluded}"' not in legend

    # Utility controls remain simple in this pass.
    for control_id in ("geographic-zoom-in", "geographic-zoom-out", "geographic-reset", "close-drawer"):
        control = html.split(f'id="{control_id}"', 1)[1].split('>', 1)[0]
        assert "semantic-icon" not in control
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run:

```bash
pytest -q tests/test_web_assets.py -k semantic_icon_family
```

Expected: FAIL because the symbol definitions and semantic-icon placements do not exist yet.

### Task 2: Add the hidden inline SVG symbol library

**Files:**
- Modify: `web/index.html` immediately after the opening `<body>` tag.

- [ ] **Step 1: Add the hidden symbol container and 24×24 symbols.**

Add a `<svg class="semantic-icon-library" aria-hidden="true" width="0" height="0" focusable="false">` containing `<symbol viewBox="0 0 24 24">` definitions for the eleven IDs in the test. Use integer-aligned `<rect>` elements and stepped `<path>` polygons. Every symbol must have a differentiated silhouette:

```html
<svg class="semantic-icon-library" aria-hidden="true" width="0" height="0" focusable="false">
  <defs>
    <symbol id="icon-network" viewBox="0 0 24 24">
      <path fill="#46372d" d="M3 20h2l6-13h2l6 13h2l-7-16h-2zM5 17h14v2H5z"/>
      <path fill="#5f8d4e" d="M2 4h5v5H2zM17 3h5v5h-5zM10 14h5v5h-5z"/>
      <path fill="#fff4d6" d="M3 5h2v2H3zM18 4h2v2h-2zM11 15h2v2h-2z"/>
      <path fill="#d99b45" d="M8 9h2v2H8zM15 10h2v2h-2z"/>
    </symbol>
    <symbol id="icon-plan" viewBox="0 0 24 24">
      <path fill="#46372d" d="M2 5h16l4 4v10H2z"/>
      <path fill="#fff4d6" d="M4 7h13l3 3v7H4z"/>
      <path fill="#d99b45" d="M17 5h2v5h-2z"/>
      <path fill="#5f8d4e" d="M6 14h3v2H6zM9 12h3v2H9zM12 10h3v2h-3z"/>
      <path fill="#eadcbd" d="M5 8h7v1H5z"/>
    </symbol>
    <symbol id="icon-evaluation" viewBox="0 0 24 24">
      <path fill="#46372d" d="M5 2h12l3 3v17H5z"/>
      <path fill="#fff4d6" d="M7 4h9l2 2v13H7z"/>
      <path fill="#5f8d4e" d="M9 12h2l1 2 4-5 1 2-5 6h-2z"/>
      <path fill="#d99b45" d="M9 7h6v2H9zM9 17h5v1H9z"/>
    </symbol>
    <symbol id="icon-classroom" viewBox="0 0 24 24">
      <path fill="#46372d" d="M2 4h20v13H2zM5 17h3v4H5zM16 17h3v4h-3zM3 21h18v2H3z"/>
      <path fill="#365c3a" d="M4 6h16v9H4z"/>
      <path fill="#fff4d6" d="M7 9h5v1H7zM7 12h3v1H7zM15 9h2v4h-2z"/>
      <path fill="#d99b45" d="M13 12h1v2h-1z"/>
    </symbol>
    <symbol id="icon-connection" viewBox="0 0 24 24">
      <path fill="#46372d" d="M3 8h13v3h3v5h-3v3H3z"/>
      <path fill="#5f8d4e" d="M5 10h9v7H5z"/>
      <path fill="#fff4d6" d="M14 11h3v3h-3z"/>
      <path fill="#d99b45" d="M7 12h3v3H7zM19 9h2v7h-2z"/>
    </symbol>
    <symbol id="icon-generator" viewBox="0 0 24 24">
      <path fill="#46372d" d="M3 6h13v3h4v3h2v8H3z"/>
      <path fill="#5f8d4e" d="M5 8h9v9H5z"/>
      <path fill="#365c3a" d="M16 11h4v6h-4z"/>
      <path fill="#d99b45" d="M8 10h3v5H8zM18 12h1v3h-1z"/>
      <path fill="#fff4d6" d="M6 9h4v1H6z"/>
    </symbol>
    <symbol id="icon-bus" viewBox="0 0 24 24">
      <path fill="#46372d" d="M5 6h14v12H5zM2 9h3v2H2zM19 9h3v2h-3zM2 14h3v2H2zM19 14h3v2h-3z"/>
      <path fill="#5f8d4e" d="M8 9h8v6H8z"/>
      <path fill="#d99b45" d="M10 10h2v4h-2zM14 10h2v4h-2z"/>
      <path fill="#fff4d6" d="M9 8h6v1H9z"/>
    </symbol>
    <symbol id="icon-corridor" viewBox="0 0 24 24">
      <path fill="#46372d" d="M2 9h4V7h4v2h4V7h4v2h4v6h-4v2h-4v-2h-4v2H6v-2H2z"/>
      <path fill="#5f8d4e" d="M4 10h4v4H4zM16 10h4v4h-4z"/>
      <path fill="#d99b45" d="M9 10h6v4H9z"/>
      <path fill="#fff4d6" d="M5 11h2v2H5zM17 11h2v2h-2z"/>
    </symbol>
    <symbol id="icon-help" viewBox="0 0 24 24">
      <path fill="#46372d" d="M8 2h8v2h3v3h2v10h-2v3h-3v2H8v-2H5v-3H3V7h2V4h3z"/>
      <path fill="#d99b45" d="M9 4h6v2h3v3h1v6h-2v3h-3v2H9v-2H6v-3H5V9h2V6h2z"/>
      <path fill="#fff4d6" d="M11 7h3v2h-2v3h-2V9h1zM10 14h3v3h-3z"/>
      <path fill="#c9892d" d="M7 17h2v1H7zM15 6h2v1h-2z"/>
    </symbol>
    <symbol id="icon-error" viewBox="0 0 24 24">
      <path fill="#46372d" d="M3 5h18v14h-5v3H8v-3H3z"/>
      <path fill="#b85450" d="M5 7h14v10h-3v2H9v-2H5z"/>
      <path fill="#71332f" d="M10 9h4v5h-4zM10 15h4v1h-4z"/>
      <path fill="#f5d8d0" d="M11 10h2v3h-2zM11 15h2v1h-2z"/>
    </symbol>
    <symbol id="icon-success" viewBox="0 0 24 24">
      <path fill="#46372d" d="M5 4h14v2h3v12h-3v2H5v-2H2V6h3z"/>
      <path fill="#5f8d4e" d="M7 6h10v2h3v8h-3v2H7v-2H4V8h3z"/>
      <path fill="#fff4d6" d="M8 11h3v2h2v-2h2v3h-2v2h-3v-2H8z"/>
      <path fill="#d99b45" d="M15 8h2v2h-2z"/>
    </symbol>
  </defs>
</svg>
```

Replace each comment with actual multi-tonal artwork. Do not use `currentColor` as the primary fill and do not use smooth curves. Keep all geometry inside the 24×24 viewBox and align edges to integer coordinates.

- [ ] **Step 2: Run the test to verify definitions exist but placements still fail.**

Run:

```bash
pytest -q tests/test_web_assets.py -k semantic_icon_family
```

Expected: the definition/reference checks progress, but the test remains failing until placements are added.

### Task 3: Add semantic icon presentation styling

**Files:**
- Modify: `web/styles.css` near the existing `.pixel-icon` rules.

- [ ] **Step 1: Add compact crisp SVG styling.**

Add:

```css
.semantic-icon-library{position:absolute;width:0;height:0;overflow:hidden}
.semantic-icon{display:inline-block;width:20px;height:20px;flex:0 0 20px;vertical-align:-0.25em;shape-rendering:crispEdges}
.semantic-icon.is-small{width:16px;height:16px;flex-basis:16px}
.semantic-icon.is-large{width:24px;height:24px;flex-basis:24px}
.semantic-icon-pair{display:inline-flex;align-items:center;gap:7px}
.section-nav .semantic-icon{width:20px;height:20px;flex-basis:20px}
.semantic-icon-button{display:inline-flex;align-items:center;gap:8px}
@media (max-width:620px){.semantic-icon{width:18px;height:18px;flex-basis:18px}.semantic-icon.is-large{width:22px;height:22px;flex-basis:22px}}
```

Do not alter utility button geometry, add animation, or make status icons independently focusable.

- [ ] **Step 2: Run the CSS/source tests.**

Run:

```bash
pytest -q tests/test_web_assets.py -k "semantic_icon_family or cozy_pixel_visual_system"
```

Expected: the style contract passes while placement assertions remain until Task 4.

### Task 4: Place the semantic icons without changing behavior

**Files:**
- Modify: `web/index.html` only.

- [ ] **Step 1: Add navigation icons beside existing labels.**

Keep the existing anchor text and IDs unchanged; add a decorative SVG inside each anchor:

```html
<svg class="semantic-icon" aria-hidden="true"><use href="#icon-network"></use></svg>
```

Use the corresponding symbol for each of the four section links.

- [ ] **Step 2: Add meaningful action icons.**

Add `icon-connection`, `icon-generator`, `icon-evaluation`, and `icon-network` beside the existing text in Add Connection Site, Add Generator, Run Practice Evaluation, and Explore Network. Preserve button text exactly and do not change IDs, types, or event attributes.

- [ ] **Step 3: Add selected-resource and legend icons.**

Use `icon-bus`, `icon-corridor`, `icon-connection`, and `icon-generator` only in the corresponding selected-resource content and map legend concepts. The legend gets only Bus and Corridor icons. Do not add Help, Error, or Success to the legend.

- [ ] **Step 4: Add state/help icons only where state text already exists.**

Place `icon-help` next to the existing help disclosure text, `icon-error` beside existing error/validation text, and `icon-success` beside existing feasible/success text. Keep every paired SVG `aria-hidden="true"`; do not duplicate the visible state wording.

- [ ] **Step 5: Run the focused icon test.**

Run:

```bash
pytest -q tests/test_web_assets.py -k semantic_icon_family
```

Expected: PASS.

### Task 5: Verify rendering and run the full regression suite

**Files:**
- Modify only if a symbol requires a small-size simplification: `web/index.html`.
- Modify only if a placement needs alignment adjustment: `web/styles.css`.

- [ ] **Step 1: Inspect actual 16px and 24px renderings.**

Open the live application and inspect each symbol in its normal context at both sizes. Confirm that Network, Plan, Evaluation, Classroom, Connection Site, Generator, Bus, Corridor, Help, Error, and Success retain clear silhouettes and distinct color distribution. If a symbol is muddy at 16px, simplify only that symbol while preserving its dominant silhouette.

- [ ] **Step 2: Inspect repeated-use density.**

Check navigation, the plan action cluster, the selected-resource inspector, the map legend, and validation/result areas. Remove any duplicate icon that makes a small cluster noisy or repeats an object identity already obvious from adjacent text.

- [ ] **Step 3: Run all regression tests.**

Run:

```bash
pytest -q
```

Expected: all existing tests and the new semantic-icon contract pass. No JavaScript or API behavior should change.
