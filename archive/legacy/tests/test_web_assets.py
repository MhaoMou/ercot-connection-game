import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading

import pytest

from ercot_game import practice_server


FIXTURE = Path(__file__).parents[1] / "data/fixtures/ercot_small.json"
WEB_ROOT = Path(__file__).parents[1] / "web"


# These regressions intentionally inspect function-scoped HTML/JS contracts: this
# dependency-free project does not ship a browser DOM runtime for pytest.
TAG_RE = re.compile(
    r"""
    <(?P<closing>/?)\s*(?P<name>[A-Za-z][\w:.-]*)
    (?P<attributes>(?:"[^"]*"|'[^']*'|[^'">/]|/(?!\s*>))*)
    (?P<self_closing>/?)\s*>
    """,
    re.VERBOSE,
)


def attribute_value(tag, name):
    for attribute_name, value in _attributes(tag):
        if attribute_name == name:
            return value
    return None


def _attributes(tag):
    """Yield opening-tag attributes with quote-aware value scanning."""
    opening = re.match(r"<[A-Za-z][\w:.-]*", tag)
    if not opening:
        return
    index = opening.end()
    end = len(tag) - 1
    if tag.rstrip().endswith("/>"):
        end = tag.rfind("/>")
    while index < end:
        while index < end and tag[index].isspace():
            index += 1
        if index >= end or tag[index] == "/":
            return
        name_start = index
        while index < end and not tag[index].isspace() and tag[index] not in "=/>":
            index += 1
        attribute_name = tag[name_start:index]
        if not attribute_name:
            index += 1
            continue
        while index < end and tag[index].isspace():
            index += 1
        if index >= end or tag[index] != "=":
            yield attribute_name, ""
            continue
        index += 1
        while index < end and tag[index].isspace():
            index += 1
        if index < end and tag[index] in "\"'":
            quote = tag[index]
            index += 1
            value_start = index
            while index < end and tag[index] != quote:
                index += 1
            yield attribute_name, tag[value_start:index]
            if index < end:
                index += 1
        else:
            value_start = index
            while index < end and not tag[index].isspace() and tag[index] != ">":
                index += 1
            yield attribute_name, tag[value_start:index]


def has_attribute(tag, name):
    return any(attribute_name == name for attribute_name, _ in _attributes(tag))


def has_class(tag, class_name):
    return class_name in (attribute_value(tag, "class") or "").split()


def balanced_element_ranges(source, element):
    """Return ranges for complete same-element blocks, including nested blocks."""
    stack = []
    ranges = []
    for match in TAG_RE.finditer(source):
        if match.group("name") != element:
            continue
        if match.group("closing"):
            if stack:
                start = stack.pop()
                ranges.append((start, match.end()))
        elif not match.group("self_closing"):
            stack.append(match.start())
    return ranges


def balanced_elements(source, element):
    return [source[start:end] for start, end in balanced_element_ranges(source, element)]


def strict_balanced_elements(source, element, context="markup"):
    """Return complete blocks and reject malformed same-element markup."""
    raw_tokens = re.findall(rf"</?{re.escape(element)}(?=\s|/?>)", source)
    tag_matches = [
        match
        for match in TAG_RE.finditer(source)
        if match.group("name") == element
    ]
    assert len(raw_tokens) == len(tag_matches), (
        f"{context} contains malformed <{element}> markup"
    )

    markup_stack = []
    element_stack = []
    ranges = []
    for match in TAG_RE.finditer(source):
        name = match.group("name")
        if match.group("closing"):
            if markup_stack and markup_stack[-1][0] != name:
                assert name != element and markup_stack[-1][0] != element, (
                    f"{context} contains mismatched SVG markup near {match.group(0)!r}"
                )
            if markup_stack and markup_stack[-1][0] == name:
                markup_stack.pop()
            if name != element:
                continue
            assert element_stack, f"{context} contains an unmatched </{element}>"
            start = element_stack.pop()
            ranges.append((start, match.end()))
            continue
        if match.group("self_closing"):
            if name == element:
                if element != "use":
                    raise AssertionError(
                        f"{context} contains a self-closing <{element}/> element"
                    )
                ranges.append((match.start(), match.end()))
            continue
        markup_stack.append((name, match.start()))
        if name == element:
            element_stack.append(match.start())
    assert not element_stack, f"{context} contains an unbalanced <{element}> element"
    return [source[start:end] for start, end in ranges]


def opening_tag(block, element):
    match = re.match(rf"<{re.escape(element)}(?=\s|>)", block, re.DOTALL)
    assert match, f"missing opening {element} tag"
    quote = None
    for index in range(match.end(), len(block)):
        character = block[index]
        if character in "\"'":
            quote = None if quote == character else character if quote is None else quote
        elif character == ">" and quote is None:
            return block[: index + 1]
    raise AssertionError(f"unclosed opening {element} tag")


def _semantic_icon_instances(source, context):
    instances = []
    for svg in strict_balanced_elements(source, "svg", context):
        svg_tag = opening_tag(svg, "svg")
        if not has_class(svg_tag, "semantic-icon"):
            continue
        assert attribute_value(svg_tag, "aria-hidden") == "true", svg_tag
        assert attribute_value(svg_tag, "viewBox") == "0 0 24 24", svg_tag
        uses = strict_balanced_elements(svg, "use", context)
        assert len(uses) == 1, f"{context} semantic icon must contain one <use>"
        use_tag = opening_tag(uses[0], "use")
        assert attribute_value(use_tag, "aria-hidden") == "true", use_tag
        href = attribute_value(use_tag, "href")
        assert href and re.fullmatch(r"#[A-Za-z][\w-]*", href), use_tag
        instances.append((svg, svg_tag, use_tag, href[1:]))
    return instances


def semantic_icon_references(source, context="semantic icon context"):
    """Validate every semantic icon and return its exact referenced IDs."""
    return [icon_id for _, _, _, icon_id in _semantic_icon_instances(source, context)]


def semantic_icon_constructor_references(source):
    return re.findall(r'createSemanticIcon\("([A-Za-z][\w-]*)"\)', source)


def assert_resolved_icon_references(source, definitions, context):
    """Require every static or extracted JS <use> href to resolve to a symbol."""
    for match in TAG_RE.finditer(source):
        if match.group("name") != "use" or match.group("closing"):
            continue
        use_tag = match.group(0)
        href = attribute_value(use_tag, "href")
        assert href and re.fullmatch(r"#[A-Za-z][\w-]*", href), use_tag
        assert href[1:] in definitions, (
            f"{context} <use> href must resolve to the semantic icon library: {use_tag}"
        )


def assert_exact_semantic_icon_references(source, expected, context):
    actual = semantic_icon_references(source, context)
    assert sorted(actual) == sorted(expected), (
        f"{context} must contain exactly semantic icons {list(expected)!r}; "
        f"found {actual!r}"
    )


def semantic_icon_reference(source, icon_id, context="semantic icon context"):
    """Assert and return one complete semantic-icon instance in source."""
    matches = [instance for instance in _semantic_icon_instances(source, context) if instance[3] == icon_id]
    assert matches, f"{context} must contain a resolved #{icon_id} semantic icon"
    assert len(matches) == 1, f"{context} must contain exactly one #{icon_id} semantic icon"
    svg, _, _, _ = matches[0]
    assert svg.endswith("</svg>"), f"{context} semantic icon must be balanced"
    return svg


def assert_symbol_geometry(symbol, context):
    geometry_names = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}
    geometry_tags = [
        match.group(0)
        for match in TAG_RE.finditer(symbol)
        if match.group("name") in geometry_names and not match.group("closing")
    ]
    assert geometry_tags, f"{context} must contain non-empty SVG geometry"

    coordinate_attributes = {"cx", "cy", "r", "rx", "ry", "x", "x1", "x2", "y", "y1", "y2"}
    for geometry_tag in geometry_tags:
        values = []
        for name in coordinate_attributes:
            value = attribute_value(geometry_tag, name)
            if value is not None:
                values.extend(re.findall(r"-?(?:\d+(?:\.\d*)?|\.\d+)", value))
        points = attribute_value(geometry_tag, "points")
        if points is not None:
            values.extend(re.findall(r"-?(?:\d+(?:\.\d*)?|\.\d+)", points))
        path = attribute_value(geometry_tag, "d")
        if path is not None:
            assert path.strip(), f"{context} path geometry must be non-empty"
            values.extend(re.findall(r"-?(?:\d+(?:\.\d*)?|\.\d+)", path))
        assert all(0 <= float(value) <= 24 for value in values), (
            f"{context} geometry coordinates must stay within the 0..24 viewBox: {geometry_tag}"
        )


def javascript_function(source, name):
    match = re.search(rf"(?<![\w$])function {re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    assert match, f"missing JavaScript function: {name}"
    depth = 0
    function_start = match.start() + match.group(0).find("function")
    index = match.end() - 1
    while index < len(source):
        character = source[index]
        if character in "\"'`":
            quote = character
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline == -1 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            index = len(source) if comment_end == -1 else comment_end + 2
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[function_start:index + 1]
        index += 1
    raise AssertionError(f"unbalanced JavaScript function: {name}")


def compact_javascript(source):
    return re.sub(r"\s+", "", source)


def element_with_id(source, element, element_id):
    for block in balanced_elements(source, element):
        if attribute_value(opening_tag(block, element), "id") == element_id:
            return block
    raise AssertionError(f"missing complete {element} element: {element_id}")


@pytest.fixture
def running_server():
    server = practice_server.create_server(scenario_path=FIXTURE, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, path):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    connection.request("GET", path)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response, body


def test_web_source_files_contain_practice_interface_landmarks():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "ERCOT Practice Interface" in html
    assert "practice-only" in html
    assert 'id="scenario-panel"' not in html
    assert "Scenario brief" not in html
    assert 'id="ercot-map"' in html
    assert 'id="plan-form"' in html
    assert 'id="period-selector"' in html
    assert 'id="connection-cards"' in html
    assert 'id="generator-cards"' in html
    assert 'id="add-connection"' in html
    assert 'id="add-generator"' in html
    assert 'id="resource-drawer"' in html
    assert 'id="evaluate-button"' in html
    assert 'id="results-panel"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-describedby="connections-help connections-error"' in html
    assert '<svg id="ercot-map"' in html
    assert 'role="group" aria-labelledby="map-title map-description"' in html
    assert '<svg id="ercot-map"' in html and 'role="img"' not in html.split('<svg id="ercot-map"', 1)[1].split('>', 1)[0]
    assert 'id="legend-low-item"' in html
    assert 'id="legend-clear-item"' in html
    assert 'id="map-tooltip"' in html
    assert 'id="map-zones-layer"' in html
    assert 'id="map-locator-layer"' in html
    assert "@media" in css
    assert ".team-controls .form-grid{display:grid;grid-template-columns:1fr;gap:14px}" in css
    assert ".team-controls .form-grid>label{display:grid;gap:5px;align-content:start}" in css
    assert 'fetch("/api/scenario?period=0",' in javascript
    assert 'fetch("/api/evaluate"' in javascript
    assert "aria-label" in javascript
    assert "presentation" in javascript


def test_cozy_pixel_visual_system_contract_preserves_single_geographic_map():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "@font-face" in css
    assert 'font-family:"IBM Plex Sans"' in css or 'font-family: "IBM Plex Sans"' in css
    assert 'font-family:"IBM Plex Mono"' in css or 'font-family: "IBM Plex Mono"' in css
    assert "font-display:swap" in css or "font-display: swap" in css
    assert "--font-mono" in css
    assert "--paper:#f3e6c8" in css
    assert "--panel:#fff4d6" in css
    assert "--accent-blue:var(--green)" in css
    assert "--success:var(--forest)" in css
    assert "--warning:var(--amber)" in css
    assert "--danger:var(--brick)" in css
    assert "--shadow:3px 3px 0" in css
    assert "Source Serif 4" not in css
    assert "#0969da" not in css
    assert "#f6f8fa" not in css
    assert "0 18px 48px" not in css
    assert 'id="geographic-map"' in html
    assert 'id="geographic-map-viewport"' in html
    assert 'id="map-frame"' in html
    assert re.search(r"\.map-frame\s*\{[^}]*display:none", css)


def test_academic_shell_exposes_section_navigation_and_dynamic_metadata():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for target in ("network-section", "plan-section", "evaluation-section", "classroom-section"):
        assert f'id="{target}"' in html
    for target in ("#network-section", "#plan-section", "#evaluation-section", "#classroom-section"):
        assert target in html
    assert 'class="section-nav"' in html
    assert 'id="scenario-metadata"' in html
    assert "IntersectionObserver" in javascript
    assert "aria-current" in javascript
    assert "section-nav" in css
    assert "--font-display" in css


def test_cozy_typography_uses_display_mono_and_readable_body_fonts():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert '"IBM Plex Sans"' in css
    assert '"IBM Plex Mono"' in css
    assert 'font-family:"Pixelify Sans"' in css
    assert "Source Serif 4" not in css


def test_cozy_semantic_icon_family_is_defined_and_selectively_placed():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    expected = {
        "icon-network", "icon-plan", "icon-evaluation", "icon-classroom",
        "icon-connection", "icon-generator", "icon-bus", "icon-corridor",
        "icon-help", "icon-error", "icon-success",
    }
    library_blocks = [
        block
        for block in balanced_elements(html, "svg")
        if attribute_value(opening_tag(block, "svg"), "id") == "semantic-icon-library"
    ]
    library = library_blocks[0] if library_blocks else ""
    symbol_blocks = strict_balanced_elements(library, "symbol", "semantic icon library") if library else []
    symbol_tags = [opening_tag(block, "symbol") for block in symbol_blocks]
    symbol_ids = [attribute_value(symbol_tag, "id") for symbol_tag in symbol_tags]
    definitions = set(symbol_ids)

    assert definitions == expected
    assert len(library_blocks) == 1, "semantic icon library must be unique"
    library_tag = opening_tag(library, "svg")
    assert attribute_value(library_tag, "id") == "semantic-icon-library"
    assert has_attribute(library_tag, "hidden"), library_tag
    assert attribute_value(library_tag, "aria-hidden") == "true", library_tag
    assert len(symbol_ids) == len(expected), "symbol IDs must be unique and non-anonymous"
    assert all(re.fullmatch(r"icon-[a-z]+", symbol_id or "") for symbol_id in symbol_ids)
    for icon_id in expected:
        assert sum(attribute_value(tag, "id") == icon_id for tag in symbol_tags) == 1

    for symbol_block, symbol_tag in zip(symbol_blocks, symbol_tags):
        assert attribute_value(symbol_tag, "viewBox") == "0 0 24 24", symbol_tag
        assert_symbol_geometry(symbol_block, f"symbol {attribute_value(symbol_tag, 'id')}")

    assert_resolved_icon_references(html, definitions, "page HTML")
    assert_resolved_icon_references(javascript, definitions, "JavaScript-generated markup")

    semantic_svgs = [
        block
        for block in strict_balanced_elements(html, "svg", "page HTML")
        if has_class(opening_tag(block, "svg"), "semantic-icon")
    ]
    assert semantic_svgs
    semantic_icon_references(html, "page HTML semantic icons")
    for semantic_svg in semantic_svgs:
        svg_tag = opening_tag(semantic_svg, "svg")
        assert attribute_value(svg_tag, "aria-hidden") == "true", svg_tag
        assert attribute_value(svg_tag, "viewBox") == "0 0 24 24", svg_tag
        use_blocks = strict_balanced_elements(semantic_svg, "use", "page HTML semantic icon")
        assert len(use_blocks) == 1, semantic_svg
        use_tag = opening_tag(use_blocks[0], "use")
        assert attribute_value(use_tag, "aria-hidden") == "true", use_tag
        href = attribute_value(use_tag, "href")
        assert href, f"every semantic icon <use> must use href: {use_tag}"
        assert href.startswith("#"), use_tag
        assert href[1:] in definitions, use_tag

    for action_id in ("add-connection", "add-generator", "evaluate-button", "explore-network-button"):
        assert f'id="{action_id}"' in html

    navigation_icons = {
        "network-section": "icon-network",
        "plan-section": "icon-plan",
        "evaluation-section": "icon-evaluation",
        "classroom-section": "icon-classroom",
    }
    for section_id, icon_id in navigation_icons.items():
        anchors = [
            block
            for block in balanced_elements(html, "a")
            if attribute_value(opening_tag(block, "a"), "href") == f"#{section_id}"
        ]
        assert len(anchors) == 1, f"missing unique navigation anchor for {section_id}"
        assert_exact_semantic_icon_references(
            anchors[0], [icon_id], f"navigation anchor {section_id}"
        )
        semantic_icon_reference(anchors[0], icon_id, f"navigation anchor {section_id}")

    action_icons = {
        "add-connection": "icon-connection",
        "add-generator": "icon-generator",
        "evaluate-button": "icon-evaluation",
        "explore-network-button": "icon-network",
    }
    for action_id, icon_id in action_icons.items():
        action = element_with_id(html, "button", action_id)
        assert_exact_semantic_icon_references(
            action, [icon_id], f"approved action button {action_id}"
        )
        semantic_icon_reference(action, icon_id, f"approved action button {action_id}")

    section_help_blocks = [
        block
        for block in balanced_elements(html, "details")
        if has_class(opening_tag(block, "details"), "section-help")
    ]
    assert section_help_blocks
    for block in section_help_blocks:
        summary_match = re.match(
            r"<details\b[^>]*>\s*<summary>(?P<content>.*?)</summary>",
            block,
            re.DOTALL,
        )
        assert summary_match, block
        assert re.search(r"</svg>\s*[^<]+$", summary_match.group("content"), re.DOTALL), block
        assert_exact_semantic_icon_references(block, ["icon-help"], "section help details")
        semantic_icon_reference(block, "icon-help", "section help details")

    validation_summary = element_with_id(html, "div", "validation-summary")
    semantic_icon_helper = javascript_function(javascript, "createSemanticIcon")
    validation_function = javascript_function(javascript, "renderValidationSummary")
    assert "Plan needs attention" in validation_function
    assert '$("validation-summary")' in validation_function
    assert "makeSvgElement" in semantic_icon_helper
    assert "appendChild" in semantic_icon_helper
    assert '"aria-hidden": "true"' in semantic_icon_helper
    assert 'createSemanticIcon("icon-error")' in validation_function
    assert "innerHTML" not in validation_function
    assert "validation-summary" in validation_summary

    results_panel = element_with_id(html, "section", "results-panel")
    evaluation_summary = element_with_id(html, "div", "evaluation-summary")
    results_error = element_with_id(html, "div", "results-error")
    assert "Practice evaluation" in results_panel
    evaluation_summary_function = javascript_function(javascript, "renderEvaluationSummary")
    evaluation_error_function = javascript_function(javascript, "renderEvaluationError")
    assert "Feasible" in evaluation_summary_function
    assert 'createSemanticIcon("icon-success")' in evaluation_summary_function
    assert 'createSemanticIcon("icon-error")' in evaluation_error_function
    assert "innerHTML" not in evaluation_summary_function
    assert "innerHTML" not in evaluation_error_function
    assert "evaluation-summary" in evaluation_summary
    assert "results-error" in results_error

    resource_drawer = element_with_id(html, "aside", "resource-drawer")
    open_resource_drawer = javascript_function(javascript, "openResourceDrawer")
    open_site_drawer = javascript_function(javascript, "openSiteDrawer")
    create_generator_card = javascript_function(javascript, "createGeneratorCard")
    assert_exact_semantic_icon_references(
        resource_drawer, [], "static selected-resource inspector"
    )
    for source, context, icon_ids in (
        (open_resource_drawer, "resource drawer renderer", ("icon-bus", "icon-corridor")),
        (open_site_drawer, "connection site drawer renderer", ("icon-connection",)),
        (create_generator_card, "generator card renderer", ("icon-generator",)),
    ):
        assert sorted(semantic_icon_constructor_references(source)) == sorted(icon_ids), (
            f"{context} must construct exactly semantic icons {list(icon_ids)!r}"
        )
        assert "appendChild(createSemanticIcon(" in source
    assert '.semantic-icon' in css

    # The legend explains buses and corridors only; other state icons belong in
    # their actual state contexts rather than being decorative legend entries.
    legends = [
        block
        for block in balanced_elements(html, "div")
        if has_class(opening_tag(block, "div"), "legend")
    ]
    assert legends, "missing complete map legend"
    approved_legend_references = {"#icon-bus", "#icon-corridor"}
    for legend in legends:
        assert_exact_semantic_icon_references(
            legend, ["icon-bus", "icon-corridor"], "map legend"
        )
        use_blocks = strict_balanced_elements(legend, "use", "map legend")
        assert len(re.findall(r"<use(?=\s|>)", legend)) == len(use_blocks), (
            "every legend <use> must be balanced"
        )
        assert len(use_blocks) == 2, "every legend must contain the approved bus/corridor pair"
        legend_references = []
        for use in use_blocks:
            use_tag = opening_tag(use, "use")
            href = attribute_value(use_tag, "href")
            assert href in approved_legend_references, (
                f"legend <use> must resolve to the approved bus/corridor pair: {use_tag}"
            )
            assert attribute_value(use_tag, "aria-hidden") == "true", use_tag
            legend_references.append(href)
        assert set(legend_references) == approved_legend_references

    # Utility controls remain simple in this pass.
    for control_id in ("geographic-zoom-in", "geographic-zoom-out", "geographic-reset", "close-drawer"):
        control = element_with_id(html, "button", control_id)
        assert "semantic-icon" not in control
        assert "<use" not in control


def test_navigation_is_anchor_based_and_legacy_hooks_remain_intact():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'href="#network-section"' in html
    assert 'href="#plan-section"' in html
    assert 'href="#evaluation-section"' in html
    assert 'href="#classroom-section"' in html
    for hook in (
        "ercot-map", "geographic-map", "period-selector", "resource-drawer",
        "plan-form", "connection-cards", "generator-cards", "evaluate-button",
        "results-panel", "round-panel", "round-results", "instructor-controls",
    ):
        assert f'id="{hook}"' in html
    assert html.count('<svg id="geographic-map"') == 1
    assert html.count('<svg id="ercot-map"') == 1
    assert 'id="map-frame"' in html


def test_teaching_network_identity_is_explicit_without_changing_canonical_ids():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert "ERCOT Planning Model" in html
    assert "Planning Model: public-data-informed Planning Regions and Planning Interfaces" in html
    assert "do not represent ERCOT's official electrical network" in html
    assert "ERCOT Planning Model map" in html
    assert "Synthetic teaching bus" in javascript
    assert "Teaching corridor" in javascript
    assert all(bus["bus_id"].startswith("bus-") for bus in fixture["buses"])
    assert all(corridor["corridor_id"].startswith("corridor-") for corridor in fixture["corridors"])
    assert all("voltage" not in bus and "voltage_kv" not in bus for bus in fixture["buses"])


def test_focused_network_and_validation_cleanup_contracts():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="validation-summary"' in html
    assert html.count("section-help") >= 4
    assert ".geographic-map-background{fill:#eadcbd}" in css
    assert ".geographic-gulf-water" not in css
    assert ".section-help>summary::-webkit-details-marker{display:none}" in css
    assert ".section-help>summary::before" not in css
    assert ".section-help[open]>summary::before" not in css
    assert ".choice-grid{display:grid;grid-template-columns:repeat(4" in css
    assert '.choice-card input[type="checkbox"]{width:16px;height:16px' in css
    assert "renderValidationSummary" in javascript
    assert 'document.createTextNode("Plan needs attention")' in javascript
    assert 'setAttribute("aria-invalid", "true")' in javascript
    assert "scrollIntoView" in javascript
    assert "setStatus(\"Plan needs attention. Fix the highlighted fields before evaluating.\", \"error\")" in javascript
    assert 'evaluate-button" disabled' not in html


def test_semantic_status_selectors_use_declared_status_tokens():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    expected_tokens = {
        ".notice": "var(--warning)",
        ".status-banner.is-error,.error-state": "var(--danger)",
        ".status-banner.is-success": "var(--success)",
        ".pill-success": "var(--success)",
        ".pill-danger": "var(--danger)",
        ".classroom-error-region": "var(--danger)",
        ".submission-confirmation": "var(--success)",
    }
    for selector, token in expected_tokens.items():
        assert token in css, f"{selector} should use {token}"

    for selector, fallback in {
        ".notice": "background:#fff0c9",
        ".status-banner.is-error,.error-state": "background:#f5d8d0",
        ".status-banner.is-success": "background:var(--green-soft)",
        ".pill-success": "background:var(--green-soft)",
        ".pill-danger": "background:#f5d8d0",
        ".classroom-error-region": "background:#f5d8d0",
        ".submission-confirmation": "background:var(--green-soft)",
    }.items():
        assert fallback in css, f"{selector} should include a warm-surface fallback"

    for legacy_literal in (
        "#d8b65b",
        "#fff8c5",
        "#4d2d00",
        "#ff8182",
        "#ffebe9",
        "#82071e",
        "#4ac26b",
        "#dafbe1",
        "#116329",
    ):
        assert legacy_literal not in css


def test_local_ibm_plex_assets_are_non_empty_and_referenced():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    assets = {
        "IBMPlexSans-Regular.woff2": "IBMPlexSans-Regular.woff2",
        "IBMPlexSans-SemiBold.woff2": "IBMPlexSans-SemiBold.woff2",
        "IBMPlexMono-Regular.woff2": "IBMPlexMono-Regular.woff2",
    }

    for filename, css_name in assets.items():
        asset = WEB_ROOT / "fonts" / filename
        assert asset.exists()
        assert asset.stat().st_size > 0
        assert f"/fonts/{css_name}" in css


def test_local_source_serif_assets_are_non_empty_but_not_part_of_cozy_theme():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    for filename in ("SourceSerif4-Regular.ttf", "SourceSerif4-SemiBold.ttf"):
        asset = WEB_ROOT / "fonts" / filename
        assert asset.exists()
        assert asset.stat().st_size > 0
        assert f"/fonts/{filename}" not in css


def test_classroom_round_markup_exposes_server_driven_status_and_role_gated_controls():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for hook in (
        "round-panel",
        "round-state",
        "round-team",
        "round-deadline",
        "draft-status",
        "submission-status",
        "save-draft-button",
        "submit-plan-button",
        "submit-confirmation",
        "round-results",
        "leaderboard",
        "instructor-controls",
        "instructor-transition-button",
        "instructor-evaluate-button",
        "instructor-publish-button",
        "server-diagnostics",
        "structured-error",
        "classroom-retry-button",
    ):
        assert f'id="{hook}"' in html
    assert 'id="instructor-controls"' in html and 'hidden' in html.split('id="instructor-controls"', 1)[1][:120]
    assert 'aria-live="polite"' in html
    assert ".round-panel" in css
    assert ".submission-state" not in css or ".round-panel" in css
    assert ".leaderboard" in css


def test_classroom_client_uses_phase3_endpoints_and_preserves_server_visibility():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for function_name in (
        "loadRound",
        "loadDraft",
        "saveDraft",
        "submitPlan",
        "loadSubmissionStatus",
        "loadLeaderboard",
        "renderRound",
        "renderLeaderboard",
        "renderStructuredError",
    ):
        assert f"function {function_name}" in javascript
    for endpoint in (
            'classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}`',
            'classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/draft`',
            'classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/submit`',
            'classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/submission`',
            'classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/leaderboard`',
            'classroomFetch(`/api/instructor/rounds/${encodeURIComponent(state.classroom.roundId)}/transition`',
            'classroomFetch(`/api/instructor/rounds/${encodeURIComponent(state.classroom.roundId)}/evaluate`',
    ):
        assert endpoint in javascript
    assert 'headers.set("Authorization"' in javascript
    assert '"Idempotency-Key"' in javascript
    assert "published" in javascript
    assert "visibility" in javascript
    assert "retry" in javascript.lower()
    assert "retryClassroomAction" in javascript


def test_classroom_client_does_not_implement_official_scoring_or_leak_tokens():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    compact = compact_javascript(javascript).lower()

    for forbidden in (
        "function calculateofficialrevenue",
        "function calculatefeasibility",
        "function calculatecurtailment",
        "function calculaterank",
        "official_revenue =",
        "curtailment =",
        "rank =",
        "console.log(token",
        "textcontent = token",
    ):
        assert forbidden not in compact
    assert "sessionstorage" in compact
    assert "token" in compact


def test_classroom_startup_hydrates_only_after_scenario_is_ready():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    startup = javascript.split('document.addEventListener("DOMContentLoaded"', 1)[1]

    assert "loadScenario().then((scenarioReady) => { if (scenarioReady) initializeClassroom(); })" in startup
    assert startup.index("loadScenario().then") < startup.index("loadCountyAsset")
    assert "loadScenario(); loadCountyAsset(); initializeClassroom();" not in startup


def test_classroom_retry_policy_is_limited_to_idempotent_methods():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    fetcher = javascript_function(javascript, "classroomFetch")

    assert 'const retryableMethods = new Set(["GET", "HEAD", "OPTIONS", "PUT"])' in fetcher
    assert "retryableMethods.has(method)" in fetcher
    assert "const maxAttempts = retryable ? 1 : 0" in fetcher
    assert "attempt === maxAttempts" in fetcher
    assert "POST" not in fetcher.split("const retryableMethods", 1)[1].split("]);", 1)[0]


def test_classroom_requests_attach_bearer_auth_without_rendering_or_logging_token():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    headers = javascript_function(javascript, "classroomHeaders")

    assert 'headers.set("Authorization", `Bearer ${state.classroom.token}`)' in headers
    assert 'headers.set("Content-Type"' in headers
    assert "console.log(token" not in javascript
    assert "console.warn(state.classroom.token" not in javascript
    assert "textContent = state.classroom.token" not in javascript


def test_submission_reuses_key_until_the_same_attempt_succeeds_and_refreshes_separately():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    submit = javascript_function(javascript, "submitPlan")

    assert "pendingSubmissionKey" in javascript
    assert "pendingSubmissionFingerprint" in javascript
    assert "getSubmissionAttemptKey" in javascript
    assert "Idempotency-Key" in submit
    assert "randomUUID" not in submit
    assert "loadLeaderboard" not in submit
    assert "refreshLeaderboardAfterSubmission" in javascript


def test_classroom_tracks_saved_and_submitted_snapshots_and_dirty_edits():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert "savedFingerprint" in javascript
    assert "submittedFingerprint" in javascript
    assert "dirty" in javascript
    assert "markClassroomDirty" in javascript
    assert 'id="draft-status"' in html
    assert 'id="submission-status"' in html
    assert "differ from submitted" in javascript
    assert "submit.disabled = !canEdit ||" in javascript


def test_leaderboard_uses_explicit_visibility_and_audience_contract():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    renderer = javascript_function(javascript, "renderLeaderboard")
    contract = javascript_function(javascript, "leaderboardVisibilityContract")

    assert "payload.visibility" in contract
    assert "payload.audience" in contract
    assert "leaderboardAudienceAllows" in javascript
    assert "visibility_contract" in javascript
    assert "visibilitychange" not in renderer


def test_classroom_round_refresh_ignores_stale_responses():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    round_loader = javascript_function(javascript, "loadRound")

    assert "roundRequestToken" in javascript
    assert "const requestToken = ++state.classroom.roundRequestToken" in round_loader
    assert "requestToken !== state.classroom.roundRequestToken" in round_loader


def test_save_and_submit_responses_cannot_clear_newer_local_edits():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    save = javascript_function(javascript, "saveDraft")
    submit = javascript_function(javascript, "submitPlan")

    assert "const editRevision = state.classroom.editRevision" in save
    assert "editRevision === state.classroom.editRevision" in save
    assert "const editRevision = state.classroom.editRevision" in submit
    assert "editRevision !== state.classroom.editRevision" in submit


def test_classroom_controls_unhide_only_when_authenticated_round_state_allows_them():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    controls = javascript_function(javascript, "updateClassroomControls")

    assert "save.hidden = !student" in controls
    assert "submit.hidden = !student" in controls
    assert 'const student = classroom.session?.role === "student"' in controls
    assert "canEdit" in controls
    assert 'instructor.hidden = classroom.session?.role !== "instructor"' in controls


def test_classroom_fetch_uses_bounded_non_recursive_retries():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    fetcher = javascript_function(javascript, "classroomFetch")

    assert "maxAttempts" in fetcher
    assert "for (let attempt = 0; attempt <= maxAttempts; attempt += 1)" in fetcher
    assert "return classroomFetch(path, options)" not in fetcher
    assert "POST" not in fetcher.split("retryableMethods", 1)[1].split("]);", 1)[0]


def test_retry_state_is_scoped_to_the_current_classroom_action():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "retryAction" in javascript
    assert "activeAction" in javascript
    assert "state.classroom.retryAction = null" in javascript
    assert "retry.action !== state.classroom.activeAction" in javascript
    assert "transitionRound" in javascript and "evaluateRound" in javascript


def test_submission_attempt_key_and_submitted_snapshot_survive_reload_hydration():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    submission = javascript_function(javascript, "renderSubmission")

    assert "submissionAttemptStorageKey" in javascript
    assert "sessionStorage" in javascript
    assert "submittedFingerprint" in submission
    assert "currentClassroomFingerprint()" in submission
    assert "removeItem" in javascript
    assert "stored.pendingSubmissionKey" in submission
    assert "stored.submittedFingerprint" not in submission


def test_leaderboard_visibility_fails_closed_for_unknown_or_wrong_team_audiences():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    audience = javascript_function(javascript, "leaderboardAudienceAllows")

    assert 'role !== "student"' in audience or 'role === "student"' in audience
    assert "state.classroom.session?.team_id" in audience
    assert "item.team_id" in javascript
    assert "return false" in audience
    assert "if (!visibility_contract.explicit) return false" in audience
    assert "unknown" not in audience.lower() or "unknown audience" in audience.lower()


def test_structural_plan_edits_mark_classroom_dirty_and_refresh_controls():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for function_name in ("addConnectionCard", "removeConnectionCard", "addGeneratorCard", "removeGeneratorCard"):
        assert "markClassroomDirty()" in javascript_function(javascript, function_name)
    assert "markClassroomDirty()" in javascript_function(javascript, "openResourceDrawer")


def test_instructor_actions_are_serialized_and_ignore_stale_responses():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    transition = javascript_function(javascript, "transitionRound")
    evaluate = javascript_function(javascript, "evaluateRound")

    assert "instructorActionInFlight" in javascript
    assert "instructorActionToken" in javascript
    for action in (transition, evaluate):
        assert "if (state.classroom.instructorActionInFlight) return" in action
        assert "const actionToken = ++state.classroom.instructorActionToken" in action
        assert "actionToken !== state.classroom.instructorActionToken" in action


def test_round_load_errors_are_visible_outside_hidden_round_panel():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'id="classroom-error-region"' in html
    assert 'id="classroom-global-retry-button"' in html
    assert 'id="classroom-error-message"' in html
    assert '$("classroom-error-region")' in javascript
    assert 'classroom-global-retry-button' in javascript
    assert '$("classroom-error-region").hidden = false' in javascript


def test_submission_is_marked_only_when_server_fingerprint_matches_current_plan():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    submission = javascript_function(javascript, "renderSubmission")

    assert "submission.submitted_fingerprint" in submission
    assert "currentClassroomFingerprint()" in submission
    assert "serverFingerprint === currentFingerprint" in submission
    assert "state.classroom.savedFingerprint" not in submission
    assert "submission.semantic_hash" not in submission


def test_save_responses_are_guarded_by_a_save_request_serial():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    save = javascript_function(javascript, "saveDraft")

    assert "saveRequestToken" in javascript
    assert "const requestToken = ++state.classroom.saveRequestToken" in save
    assert "requestToken !== state.classroom.saveRequestToken" in save
    assert "requestToken === state.classroom.saveRequestToken" in save


def test_submission_storage_is_scoped_to_session_identity_and_auth_failures_clear_it():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "sessionIdentity" in javascript
    assert "submissionAttemptStorageKey" in javascript
    assert "session_id" in javascript
    assert "invalidateClassroomSession" in javascript
    assert "failure.status === 401 || failure.status === 403" in javascript
    assert "clearSubmissionSnapshot" in javascript
    assert "state.classroom.token = null" in javascript


def test_auth_failures_clear_session_state_but_are_announced_accessibly():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    invalidate = javascript_function(javascript, "invalidateClassroomSession")
    assert 'sessionStorage.removeItem("ercot-classroom-session")' in invalidate
    for field in ("round = null", "leaderboard = null", "saving = false", "submitting = false", "savedFingerprint = null", "currentFingerprint = null", "dirty = false"):
        assert field in invalidate
    assert "announceClassroomAuthFailure" in javascript
    assert "Please sign in again" in javascript
    assert "renderStructuredError" in javascript


def test_classroom_controls_wait_for_complete_hydration_and_reads_are_token_guarded():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    controls = javascript_function(javascript, "updateClassroomControls")
    load_round = javascript_function(javascript, "loadRound")
    assert "hydrated" in controls
    assert "classroom.hydrated" in controls
    assert "state.classroom.hydrated = false" in load_round
    assert "state.classroom.hydrated = true" in load_round
    assert "instructorActionInFlight" in controls
    assert "button.disabled = !enabled" in controls
    for name in ("renderRound", "renderSubmission", "renderLeaderboard"):
        assert "requestToken" in javascript_function(javascript, name)
        assert "roundRequestToken" in javascript_function(javascript, name)


def test_bootstrap_session_is_strictly_validated_and_round_paths_are_encoded():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    initialize = javascript_function(javascript, "initializeClassroom")
    assert 'typeof token !== "string"' in initialize
    assert 'typeof details?.round_id !== "string"' in initialize
    assert '["student", "instructor"].includes(details?.role)' in initialize
    assert "encodeURIComponent(state.classroom.roundId)" in javascript


def test_leaderboard_visibility_and_audience_conflicts_fail_closed():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    contract = javascript_function(javascript, "leaderboardVisibilityContract")
    audience = javascript_function(javascript, "leaderboardAudienceAllows")
    assert "conflict" in contract
    assert "normalizedVisibility !== normalizedAudience" in contract
    assert "visibility_contract.conflict" in audience


def test_submission_and_refresh_are_bound_to_session_and_action_generations():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    submit = javascript_function(javascript, "submitPlan")
    refresh = javascript_function(javascript, "refreshLeaderboardAfterSubmission")
    assert "sessionGeneration" in submit
    assert "actionGeneration" in submit
    assert "sessionGeneration !== state.classroom.sessionGeneration" in submit
    assert "actionToken !== state.classroom.actionGeneration" in submit
    assert "sessionGeneration" in refresh
    assert "actionGeneration" in refresh
    assert "loadLeaderboard" in refresh
    assert "renderLeaderboard" not in refresh


def test_session_change_invalidates_old_round_state_and_embedded_credentials():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    invalidate = javascript_function(javascript, "invalidateClassroomSession")
    initialize = javascript_function(javascript, "initializeClassroom")
    assert "window.ERCOT_CLASSROOM_SESSION = null" in invalidate
    assert "sessionGeneration += 1" in invalidate
    assert "actionGeneration += 1" in invalidate
    assert "invalidateClassroomSession()" in initialize
    assert "state.classroom.sessionIdentity !== identity" in initialize
    assert '$("round-panel").hidden = true' in invalidate
    assert '$("round-results").hidden = true' in invalidate


def test_invalid_bootstrap_session_clears_existing_classroom_state_instead_of_returning():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    initialize = javascript_function(javascript, "initializeClassroom")
    assert "invalidateClassroomSession();" in initialize
    assert "if (typeof token !== \"string\"" in initialize
    assert "if (![\"student\", \"instructor\"].includes(details?.role))" in initialize


def test_session_invalidation_quarantines_form_and_no_draft_hydration_restores_defaults():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    invalidate = javascript_function(javascript, "invalidateClassroomSession")
    reset_form = javascript_function(javascript, "resetClassroomPlanForm")
    load_draft = javascript_function(javascript, "loadDraft")
    assert "resetClassroomPlanForm" in invalidate
    assert "renderConnectionCards([])" in reset_form
    assert "renderGeneratorCards([])" in reset_form
    assert "applyClassroomDefaultPlan" in load_draft
    assert "if (!draft?.payload)" in load_draft


def test_geographic_map_markup_has_accessible_structure_and_order():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'id="geographic-map-panel"' in html
    assert 'aria-labelledby="geographic-map-panel-title"' in html
    assert 'id="geographic-map-panel-title"' in html
    assert "ERCOT teaching-network geographic map" in html
    assert 'role="group" aria-label="Geographic map controls"' in html
    assert 'role="group" aria-label="Scenario map controls"' in html
    assert 'id="geographic-map"' in html
    assert 'id="geographic-map-viewport"' in html
    assert 'id="geographic-basemap-layer"' in html
    assert 'id="geographic-grid-layer"' not in html
    assert 'id="geographic-footprint-layer"' in html
    assert 'id="geographic-zones-layer"' in html
    assert 'id="geographic-corridors-layer"' in html
    assert 'id="geographic-buses-layer"' in html
    assert 'id="geographic-zoom-in"' in html
    assert 'id="geographic-zoom-out"' in html
    assert 'id="geographic-reset"' in html
    assert "How to use this map" in html
    # These targeted IDs avoid depending on the number or nesting of generic divs.
    assert html.index('id="map-tooltip"') < html.index('id="geographic-map-panel"')
    assert html.index('id="geographic-map-panel"') < html.index('id="legend-low-item"')


def test_geographic_basemap_contract_provides_fixed_texas_context_and_landmarks():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert html.index('id="geographic-basemap-layer"') < html.index('id="geographic-footprint-layer"')
    assert 'aria-label="Texas geographic landmarks"' in html
    assert "function renderGeographicBasemap" in javascript
    assert "function geographicBounds" in javascript
    assert "Texas" in javascript
    assert "Houston" in javascript
    assert "Dallas" in javascript
    assert "San Antonio" in javascript
    assert "Austin" in javascript


def test_geographic_map_uses_texas_context_layer_without_a_second_graph():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="geographic-context-layer"' in html
    assert "TEXAS_BOUNDARY.rings" in javascript
    assert "geographic-texas-fill" in javascript
    assert ".geographic-texas-fill" in css
    assert javascript.index("renderGeographicBasemap") < javascript.index("renderGeographicCounties")
    assert html.index('id="geographic-context-layer"') < html.index('id="geographic-counties-layer"')
    assert 'id="geographic-grid-layer"' not in html
    assert 'id="geographic-grid-layer"' not in javascript
    assert "within texas" in html.lower()
    assert "do not represent ercot's official electrical network" in html.lower()


def test_geographic_context_has_neutral_full_viewport_texas_backdrop():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    basemap = javascript_function(javascript, "renderGeographicBasemap")

    assert ".geographic-map-background{fill:#eadcbd}" in css
    assert 'class: "geographic-map-background"' in basemap
    assert "width: GEOGRAPHIC_VIEWPORT.width" in basemap
    assert "height: GEOGRAPHIC_VIEWPORT.height" in basemap


def test_geographic_context_uses_neutral_background_without_custom_gulf_geometry():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    basemap = javascript_function(javascript, "renderGeographicBasemap")

    assert 'class: "geographic-map-background"' in basemap
    assert "geographic-regional-water" not in basemap
    assert "geographic-gulf-water" not in css


def test_corridor_choices_wrap_long_ids_without_horizontal_overflow():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".choice-card{display:flex;align-items:center" in css
    assert "min-width:0" in css
    assert ".choice-card span{min-width:0;overflow-wrap:anywhere}" in css
    assert "@media (max-width:1100px){.choice-grid{grid-template-columns:repeat(2" in css
    assert "@media (max-width:620px){.choice-grid{grid-template-columns:1fr" in css


def test_semantic_icon_family_keeps_shared_pixel_sizes_and_native_help_semantics():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert '.semantic-icon{display:inline-block;width:20px;height:20px' in css
    assert '.semantic-icon.is-small{width:16px;height:16px' in css
    assert '.semantic-icon.is-large{width:24px;height:24px' in css
    assert '.section-help>summary::-webkit-details-marker{display:none}' in css
    assert '.section-help>summary::marker{content:""}' in css
    assert '<details class="section-help"><summary>' in html
    assert 'href="#icon-help"' in html


def test_geographic_refinement_uses_authoritative_texas_fill_and_quiet_counties():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function geographicBounds" in javascript
    assert ".geographic-texas-fill" in css
    assert ".geographic-county-boundary" in css


def test_geographic_texas_polygon_uses_corrected_panhandle_boundary_order():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    boundary = json.loads((WEB_ROOT / "texas-boundary.json").read_text(encoding="utf-8"))

    assert boundary["source"].startswith("U.S. Census Bureau 2025 Cartographic Boundary File")
    assert len(boundary["rings"][0]) >= 100
    assert "TEXAS_BOUNDARY" in javascript


def test_geographic_pointer_math_accounts_for_svg_letterboxing():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    pointer = javascript_function(javascript, "geographicPointerPosition")

    assert 'preserveAspectRatio="xMidYMid meet"' in html
    assert "getBoundingClientRect" in pointer
    assert "Math.min" in pointer
    assert "renderedWidth" in pointer and "renderedHeight" in pointer
    assert "offsetX" in pointer and "offsetY" in pointer
    assert "scale" in pointer


def test_geographic_basemap_reuses_named_texas_geometry_and_hides_decorations():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    basemap = javascript_function(javascript, "renderGeographicBasemap")

    assert "TEXAS_BOUNDARY.rings" in javascript
    assert "REGIONAL_TEXAS_POLYGON" not in javascript
    assert "REGIONAL_TEXAS_SOUTHERN_WESTERN_BORDER" not in javascript
    assert "REGIONAL_TEXAS_COAST" not in javascript
    assert "geographic-texas-outline" in basemap
    assert "TEXAS_GEOGRAPHIC_BOUNDS" not in javascript
    assert 'aria-hidden": "true"' in basemap
    assert 'preserveAspectRatio="xMidYMid meet"' in html


def test_geographic_frame_styles_are_consolidated():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert len(re.findall(r"\.geographic-map-frame\s*\{", css)) == 2
    assert css.count(".geographic-map-frame{position:relative;") == 1


def test_geographic_renderer_has_no_grid_and_subdues_corridors_until_interaction():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    renderer = javascript_function(javascript, "renderGeographicMap")

    assert "geographic-grid-layer" not in renderer
    assert "geographic-grid-line" not in css
    assert re.search(r"\.geographic-map-corridor\{[^}]*stroke-width:1\.5px[^}]*opacity:\.38", css)
    assert ".geographic-map-corridor:hover,.geographic-map-corridor:focus" in css
    assert ".geographic-map-corridor.is-selected" in css


def test_geographic_renderer_does_not_render_legacy_rectangular_footprint_layer():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    renderer = javascript_function(javascript, "renderGeographicMap")

    assert '$("geographic-footprint-layer").appendChild' not in renderer


def test_geographic_tooltip_frame_provides_a_css_containing_block():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    match = re.search(r"\.geographic-map-frame\s*\{([^}]*)\}", css)
    assert match, "missing geographic map frame rule"
    assert "position:relative" in re.sub(r"\s+", "", match.group(1))


def test_source_has_centered_schematic_and_geographic_map_styles():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".map-frame" in css
    assert ".geographic-map-panel" in css
    assert ".geographic-map-heading" in css
    assert ".geographic-map-actions" in css
    assert ".geographic-map-frame" in css
    assert "#geographic-map" in css
    assert ".map-corridor{fill:none;stroke:" in css
    assert ".map-corridor{fill:none;stroke:" in css and "stroke-width:2px" in css
    assert ".map-zone-label" in css
    assert ".map-corridor-label" in css and "font-size:11px" in css
    assert ".bus-label" in css and "font-size:12px" in css
    assert "@media (max-width:620px)" in css and ".geographic-map-actions" in css


def test_corridors_use_separate_wide_hit_paths_for_both_maps():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    render_map = javascript_function(javascript, "renderMap")
    render_geographic_map = javascript_function(javascript, "renderGeographicMap")

    assert ".map-corridor-hit" in css
    assert "stroke-width:18px" in css
    assert 'viewBox="0 0 960 760"' in html
    assert "GEOGRAPHIC_VIEWPORT = { width: 960, height: 760 }" in javascript
    assert "bottom: 720" in javascript
    for renderer, group_class in (
        (render_map, 'class: "map-corridor-group"'),
        (render_geographic_map, 'class: "geographic-map-corridor-group"'),
    ):
        assert group_class in renderer
        assert "group.append(path, hitPath)" in renderer
        assert renderer.index("const path = makeSvgElement") < renderer.index("const hitPath = makeSvgElement")
        assert 'class: "map-corridor-hit"' in renderer
        assert 'role: "button"' in renderer
        assert 'tabindex: "0"' in renderer
        assert "resourceEventHandlers(hitPath" in renderer
        assert "map-corridor" in renderer


def test_corridor_groups_restore_hover_and_focus_emphasis_for_both_maps():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".map-corridor.is-selected" in css
    assert ".geographic-map-corridor.is-selected" in css


def test_geographic_renderer_clears_stale_geographic_tooltip_before_rebuild():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    renderer = javascript_function(javascript, "renderGeographicMap")
    hide = javascript_function(javascript, "hideGeographicTooltip")

    assert '$("geographic-map-tooltip")' in hide
    assert "tooltip.hidden = true" in hide
    assert "tooltip.replaceChildren()" in hide
    assert "hideGeographicTooltip()" in renderer
    assert renderer.index("hideGeographicTooltip()") < renderer.index("applyGeographicTransform()")


def test_schematic_renderer_clears_stale_tooltip_before_rebuild():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    renderer = javascript_function(javascript, "renderMap")

    assert '$("map-tooltip")' in renderer
    assert "tooltip.hidden = true" in renderer
    assert "tooltip.replaceChildren()" in renderer
    assert renderer.index('$("map-tooltip")') < renderer.index("layers.forEach")
    assert renderer.index("tooltip.hidden = true") < renderer.index("layers.forEach")
    assert renderer.index("tooltip.replaceChildren()") < renderer.index("layers.forEach")


def test_map_first_source_has_period_layers_tooltips_and_accessible_drawer():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'aria-label="Scenario map controls"' in html
    assert 'role="group" aria-labelledby="geographic-map-title geographic-map-description"' in html
    assert 'role="tooltip"' in html
    assert 'aria-labelledby="resource-drawer-heading"' in html
    assert "function loadScenarioPeriod" in javascript
    assert "fetch(`/api/scenario?period=${period}`," in javascript
    assert "function renderMap" in javascript
    assert "function renderGeographicMap" in javascript
    assert "function setGeographicZoom" in javascript
    assert "function resetGeographicViewport" in javascript
    assert "pointerdown" in javascript
    assert "geographic-zoom-in" in javascript
    assert "geographic-reset" in javascript
    assert "function showMapTooltip" in javascript
    assert "function openResourceDrawer" in javascript
    assert "event.key === \"Enter\"" in javascript
    assert "event.key === \" \"" in javascript
    assert "map-tooltip" in javascript


def test_gate3_public_network_layer_is_separate_and_progressively_rendered():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="layer-public-transmission"' in html
    assert 'id="layer-teaching-network"' in html
    assert 'id="layer-generation"' in html
    assert 'id="geographic-public-transmission-layer"' in html
    assert 'id="geographic-public-generation-layer"' in html
    assert 'id="network-data-help"' in html
    assert 'id="legend-public-transmission"' in html
    assert 'id="legend-public-generation"' in html
    assert 'fetch("/data/ercot-public-network.json")' in javascript
    assert "function publicNetworkVisibleBounds" in javascript
    assert "function publicLineCandidates" in javascript
    assert "function publicPlantCandidates" in javascript
    assert "topology_confidence" not in javascript_function(javascript, "showPublicTooltip")
    assert "Geographic line; not an ERCOT bus-branch connection" in javascript_function(javascript, "showPublicTooltip")
    assert "state.publicMetrics.fetchMs" in javascript
    assert "state.publicMetrics.parseMs" in javascript


def test_geographic_source_contract_preserves_viewport_interactions_and_tooltip_ownership():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    tooltip = javascript_function(javascript, "positionMapTooltip")
    show_tooltip = javascript_function(javascript, "showMapTooltip")
    handlers = javascript_function(javascript, "resourceEventHandlers")
    transform = javascript_function(javascript, "geographicTransform")
    zoom = javascript_function(javascript, "setGeographicZoom")
    drag = javascript_function(javascript, "continueGeographicDrag")
    keydown = javascript_function(javascript, "handleGeographicKeydown")
    controls = javascript_function(javascript, "setupGeographicMapControls")

    assert 'resource.map === "geographic"' in show_tooltip
    assert '$("geographic-map-frame")' in show_tooltip
    assert '$("map-frame")' in tooltip
    assert 'resource.map || "schematic"' in handlers
    assert 'map: "geographic"' in javascript
    assert 'toFixed(1)' in transform and 'toFixed(3)' in transform
    assert 'Math.min(3.2, Math.max(1, nextZoom))' in zoom
    assert 'clampGeographicPan' in zoom
    assert 'applyGeographicTransform()' in drag
    assert 'renderGeographicMap()' not in drag
    assert 'lostpointercapture' in controls
    assert 'window.addEventListener("blur"' in controls
    assert 'document.addEventListener("visibilitychange"' in controls
    assert 'event?.pointerId' in javascript_function(javascript, "endGeographicDrag")
    assert 'event?.pointerId ?? state.geographicDrag.pointerId' in javascript_function(javascript, "endGeographicDrag")
    assert 'releasePointerCapture' in javascript_function(javascript, "endGeographicDrag")
    assert 'setPointerCapture' not in javascript_function(javascript, "endGeographicDrag")
    assert 'state.geographicDrag = null' in javascript_function(javascript, "endGeographicDrag")
    assert 'cancelGeographicDrag' in javascript_function(javascript, "cancelGeographicDrag")
    assert 'function ensureGeographicTooltip' in javascript
    assert 'id = "geographic-map-tooltip"' in javascript
    assert 'appendChild(tooltip)' in javascript_function(javascript, "ensureGeographicTooltip")
    assert 'ensureGeographicTooltip()' in javascript_function(javascript, "showMapTooltip")
    assert 'geographic-map-tooltip' in javascript_function(javascript, "resourceEventHandlers")
    reset = javascript_function(javascript, "resetGeographicViewport")
    assert "cancelGeographicDrag()" in reset
    assert reset.index("cancelGeographicDrag()") < reset.index("state.geographicZoom = 1")
    assert "state.geographicDrag = null" not in reset
    assert 'event.key === "ArrowLeft"' in keydown
    assert 'event.key === "ArrowRight"' in keydown
    assert 'event.key === "ArrowUp"' in keydown
    assert 'event.key === "ArrowDown"' in keydown
    assert 'event.key === "+"' in keydown
    assert 'event.key === "-"' in keydown
    assert 'map.addEventListener("keydown", handleGeographicKeydown)' in controls


def test_approved_revision_hides_schematic_and_describes_one_physical_locator():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="map-frame"' in html
    assert re.search(r"\.map-frame\s*\{[^}]*display:none", css)
    assert "inspect candidate buses" in html.lower()
    assert "Use the schematic above" not in html
    assert 'scenario.presentation?.disclaimer' not in javascript


def test_geographic_projection_preserves_equal_longitude_latitude_scale():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    projection = javascript_function(javascript, "projectGeographicPoint")

    assert "geographicBounds()" in projection
    assert "Math.min" in projection
    assert "scale" in projection
    assert "latitudeSpan" in projection
    assert "(point[1] - bounds.minLat) / latitudeSpan" in projection
    assert "(1 - normalizedLatitude) * contentHeight" in projection
    assert "longitudeCorrection" in projection
    assert "projectGeographicPoint(point)" in javascript


def test_county_asset_and_layer_are_local_accessible_and_behind_network_layers():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    counties = json.loads((WEB_ROOT / "texas-counties.json").read_text(encoding="utf-8"))

    assert counties["source"]
    assert counties["features"]
    assert {"name", "coordinates"}.issubset(counties["features"][0])
    assert 'id="geographic-counties-layer"' in html
    assert 'aria-label="Texas county boundaries"' in html
    assert html.index('id="geographic-counties-layer"') < html.index('id="geographic-corridors-layer"')
    assert html.index('id="geographic-corridors-layer"') < html.index('id="geographic-buses-layer"')
    assert "TEXAS_COUNTIES" in javascript
    assert "function renderGeographicCounties" in javascript
    assert "geographic-counties-layer" in javascript
    assert 'fetch("/texas-counties.json"' in javascript
    assert "https://" not in javascript
    assert "county-label" not in javascript


def test_geographic_context_and_fixture_coordinates_stay_in_physical_region():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
    buses = {bus["bus_id"]: bus["presentation"] for bus in scenario["buses"]}

    expected_points = {
        "bus-north-02": (-96.5, 33.1),
        "bus-rio-grande-01": (-99.5, 27.5),
        "bus-rio-grande-02": (-98.2, 26.2),
        "bus-rio-grande-03": (-100.9, 29.4),
        "bus-rio-grande-04": (-97.5, 25.9),
    }
    for bus_id, point in expected_points.items():
        assert (buses[bus_id]["longitude"], buses[bus_id]["latitude"]) == point

    for corridor in scenario["corridors"]:
        presentation = corridor["presentation"]
        path = presentation["path"]
        start = buses[presentation["from_bus_id"]]
        end = buses[presentation["to_bus_id"]]
        assert tuple(path[0]) == (start["longitude"], start["latitude"])
        assert tuple(path[-1]) == (end["longitude"], end["latitude"])

    assert 'id="geographic-context-layer"' in html
    assert "loadTexasBoundaryAsset" in javascript
    assert "geographic-texas-fill" in javascript
    assert "geographic-mexico-land" not in javascript
    assert "geographic-gulf-water" not in javascript


def test_tooltip_source_explains_endpoints_values_and_guidance_for_buses_and_corridors():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "presentation.from_bus_id" in javascript
    assert "presentation.to_bus_id" in javascript
    assert "Headroom" in javascript
    assert "Capacity" in javascript
    assert "Selected period" in javascript
    assert "tutorial_hint" in javascript
    assert "resourceHint(resource)" in javascript


def test_resource_tooltip_presentation_access_handles_missing_metadata():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    hint = javascript_function(javascript, "resourceHint")
    tooltip = javascript_function(javascript, "showMapTooltip")

    assert "objectOrEmpty(resource?.item)" in javascript
    assert "resourcePresentation(resource)" in hint
    assert "resourcePresentation(resource)" in tooltip


def test_tooltip_source_wires_focused_and_hovered_controls_to_live_tooltip():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="map-tooltip"' in html
    assert 'role="tooltip"' in html
    assert 'resource.map === "geographic" ? "geographic-map-tooltip" : "map-tooltip"' in javascript
    assert "node.addEventListener(\"focus\"" in javascript
    assert "node.addEventListener(\"mouseenter\"" in javascript
    assert "node.addEventListener(\"blur\"" in javascript
    assert "tooltip.setAttribute(\"aria-live\", \"polite\")" in javascript


def test_source_has_educational_guidance_and_visible_parameter_ranges():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert html.count('class="section-help-row') >= 3
    assert html.count('class="section-help"') >= 3
    assert html.count("What this means") < 4
    assert html.count("How to use it") < 4
    for phrase in (
        "K: 0–6",
        "μ: 0–1",
        "Profile: 0–1",
        "Capacity: finite, non-negative MW",
        "Fee: finite, non-negative $/MWh",
        "Generator cost: finite, non-negative $/MWh",
    ):
        assert phrase in html


def test_source_has_repeatable_canonical_editors_and_stale_result_reset():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for function_name in (
        "addConnectionCard",
        "duplicateConnectionCard",
        "removeConnectionCard",
        "addGeneratorCard",
        "removeGeneratorCard",
        "buildCanonicalPlan",
        "clearStaleResult",
        "renderDiagnostics",
    ):
        assert f"function {function_name}" in javascript
    for field in (
        "team_id",
        "connections",
        "generators",
        "intervention_budget_k",
        "curtailment_depth_mu",
        "flexibility_fee_per_mwh",
        "connection_id",
        "path_corridors",
        "marginal_cost_per_mwh",
    ):
        assert field in javascript
    assert "generator.connection_id" in javascript
    assert "result = null" in javascript


def test_source_repairs_generator_references_when_a_connection_is_removed():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function repairGeneratorReferences" in javascript
    assert "first remaining connection" in javascript
    assert "reassigned from removed connection" in javascript
    assert "generator.connection_id = fallbackConnectionId" in javascript
    assert "refreshGeneratorConnectionOptions()" in javascript


def test_source_covers_zero_site_zero_generator_and_duplicate_id_edge_cases():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "connections.length" in javascript
    assert "Add at least one connection site" in javascript
    assert "generators.length" in javascript
    assert "No generators submitted." in javascript
    assert "Duplicate connection IDs are not allowed." in javascript
    assert "Duplicate generator IDs are not allowed." in javascript
    assert "Generator connection must reference an existing connection." in javascript


def test_source_has_accessibility_landmarks_and_field_specific_errors():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert '<main id="workspace"' in html
    assert '<aside id="resource-drawer"' in html
    assert 'aria-describedby="' in html
    assert 'setAttribute("aria-invalid", "true")' in javascript
    assert "Duplicate connection IDs" in javascript
    assert "Generator connection must reference an existing connection." in javascript


def test_source_renders_server_site_generator_and_binding_diagnostics():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "site_diagnostics" in javascript
    assert "generator_dispatch" in javascript
    assert "binding_site_ids" in javascript
    assert "curtailed_site_ids" in javascript
    assert "team_totals" in javascript
    assert "renderDiagnostics(result)" in javascript
    assert "validateEvaluationPayload(payload)" in javascript
    assert "connection_results" in javascript
    assert "generator_dispatch_results" in javascript


def test_source_contract_without_dom_runtime_covers_duplicate_id_validation_branches():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    build_plan = javascript_function(javascript, "buildCanonicalPlan")

    assert "const seenConnections = new Set()" in build_plan
    assert "seenConnections.has(connectionId)" in build_plan
    assert 'setFieldError(idField, "Duplicate connection IDs are not allowed.")' in build_plan
    assert '$("connections-error").textContent = "Duplicate connection IDs must be unique."' in build_plan
    assert "const seenGenerators = new Set()" in build_plan
    assert "seenGenerators.has(generatorId)" in build_plan
    assert 'setFieldError(idField, "Duplicate generator IDs are not allowed.")' in build_plan
    assert '$("generators-error").textContent = "Duplicate generator IDs must be unique."' in build_plan
    assert "if (!valid)" in build_plan and '$("form-message").textContent' in build_plan and "return null" in build_plan


def test_source_contract_without_dom_runtime_covers_zero_site_and_zero_generator_branches():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    build_plan = javascript_function(javascript, "buildCanonicalPlan")
    add_generator = javascript_function(javascript, "addGeneratorCard")
    diagnostics = javascript_function(javascript, "renderDiagnostics")

    assert "if (!connections.length)" in build_plan
    assert 'Add at least one connection site; the evaluator requires a non-empty connections array.' in build_plan
    assert "valid = false" in build_plan
    assert "if (!connections.length)" in add_generator
    assert 'Add a connection site before adding a generator.' in add_generator
    assert '$("add-connection")?.focus()' in add_generator
    assert "return" in add_generator
    assert "if (!siteResults.length)" in diagnostics
    assert "No site diagnostics returned." in diagnostics
    assert "if (!generators.length)" in diagnostics
    assert "No generators submitted." in diagnostics


def test_source_contract_without_dom_runtime_covers_deterministic_generator_repair():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    repair = javascript_function(javascript, "repairGeneratorReferences")
    remove = javascript_function(javascript, "removeConnectionCard")
    refresh = javascript_function(javascript, "refreshGeneratorConnectionOptions")

    assert 'connectionDrafts().filter((connection) => connection.connection_id.trim() !== removedConnectionId)' in repair
    assert '.map((connection) => connection.connection_id.trim()).find(Boolean) || ""' in repair
    assert "generators.forEach((generator) =>" in repair
    assert "if (generator.connection_id !== removedConnectionId)" in repair
    assert "generator.connection_id = fallbackConnectionId" in repair
    assert "reassigned from removed connection" in repair
    assert "removedGeneratorCount += 1" in repair
    assert "repairGeneratorReferences(removedDraft?.connection_id || \"\", generatorDrafts())" in remove
    assert "renderGeneratorCards(repaired.generators)" in remove
    assert "if (repaired.notice) setEditorNotice(repaired.notice)" in remove
    assert "select.replaceChildren(...connectionOptions(current))" in refresh


def test_source_contract_without_dom_runtime_covers_canonical_payload_shape():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    build_plan = compact_javascript(javascript_function(javascript, "buildCanonicalPlan"))
    evaluate = javascript_function(javascript, "evaluatePlan")
    evaluate_compact = compact_javascript(evaluate)

    assert "connections.push({connection_id:connectionId,bus_id:busField.value,path_corridors:[...card.querySelectorAll(\".connection-corridor:checked\")].map((field)=>field.value),capacity_mw:capacity,profile})" in build_plan
    assert "generators.push({generator_id:generatorId,connection_id:connectionField.value,capacity_mw:capacity,marginal_cost_per_mwh:cost})" in build_plan
    assert "return{team_id:teamId,connections,generators,intervention_budget_k:budget,curtailment_depth_mu:mu,flexibility_fee_per_mwh:fee}" in build_plan
    assert 'JSON.stringify({ plan })' in evaluate
    assert "body:JSON.stringify({plan})" in evaluate_compact


def test_source_contract_without_dom_runtime_covers_diagnostic_rendering_landmarks():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    diagnostics = javascript_function(javascript, "renderDiagnostics")
    result = javascript_function(javascript, "renderResult")

    for landmark in (
        'id="results-content"',
        'id="grid-diagnostics"',
        'id="site-diagnostics"',
        'id="generator-diagnostics"',
        'id="binding-diagnostics"',
        'id="evaluation-identity"',
    ):
        assert landmark in html
    assert '$("grid-diagnostics")' in diagnostics
    assert '$("site-diagnostics")' in diagnostics
    assert "team.connection_results || team.site_results || site_diagnostics || result.connection_results" in diagnostics
    assert 'card.className = "diagnostic-card"' in diagnostics
    assert "site.connection_id" in diagnostics and "site.bus_id" in diagnostics and "siteScore.total" in diagnostics
    assert '$("generator-diagnostics")' in diagnostics
    assert "team.generator_dispatch_results || result.generator_dispatch" in diagnostics
    assert "generator.generator_id" in diagnostics and "generator.connection_id" in diagnostics and "generator.total_mwh" in diagnostics
    assert "diagnostics.binding_site_ids" in diagnostics
    assert "diagnostics.curtailed_site_ids" in diagnostics
    assert "team_totals" in diagnostics
    assert '$("results-content").hidden = false' in result
    assert "renderDiagnostics(result)" in result


def test_source_contract_rejects_innerhtml_and_builds_api_text_with_safe_dom_nodes():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    tooltip = javascript_function(javascript, "showMapTooltip")
    diagnostics = javascript_function(javascript, "renderDiagnostics")

    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "tooltip.replaceChildren()" in tooltip
    assert 'appendTextElement(tooltip, "strong"' in tooltip
    assert 'appendTextElement(tooltip, "span"' in tooltip
    assert "appendTextElement(card, \"strong\"" in diagnostics
    assert "appendTextElement(card, \"p\"" in diagnostics
    assert 'placeholder.textContent = "Select a Planning Region' in javascript


def test_source_contract_guards_evaluation_and_scenario_responses_against_late_requests():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    evaluate = javascript_function(javascript, "evaluatePlan")
    period = javascript_function(javascript, "loadScenarioPeriod")
    scenario = javascript_function(javascript, "loadScenario")

    assert "evaluationRequestToken" in javascript
    assert "scenarioRequestToken" in javascript
    assert "new AbortController()" in evaluate
    assert "new AbortController()" in period
    assert "new AbortController()" in scenario
    assert "signal: controller.signal" in evaluate
    assert "signal: controller.signal" in period
    assert "signal: controller.signal" in scenario
    assert "requestToken !== state.evaluationRequestToken" in evaluate
    assert "requestToken !== state.scenarioRequestToken" in period
    assert "requestToken !== state.scenarioRequestToken" in scenario
    assert "AbortError" in evaluate and "AbortError" in period and "AbortError" in scenario
    assert "state.planRevision" in evaluate
    assert "planRevision !== state.planRevision" in evaluate


def test_source_contract_uses_evaluator_flagged_state_after_evaluation():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    render_map = javascript_function(javascript, "renderMap")
    legend = javascript_function(javascript, "renderLegend")

    assert "state.result ?" in render_map
    assert "headroomClass(bus)" in render_map
    assert "is-clear" in render_map
    assert "binding.has(normalizeBindingId(bus.bus_id))" in render_map
    assert "binding.has(normalizeBindingId(corridor.corridor_id))" in render_map
    assert 'legend-low-item").hidden = evaluated' in legend
    assert 'legend-clear-item").hidden = !evaluated' in legend
    assert "Evaluator binding / violation" in legend


def test_source_contract_validates_diagnostic_shapes_before_rendering_and_requires_boolean_feasible():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    validation = javascript_function(javascript, "validateEvaluationPayload")
    diagnostics = javascript_function(javascript, "renderDiagnostics")
    result = javascript_function(javascript, "renderResult")

    assert "function validateDiagnosticItems" in javascript
    assert "typeof diagnostics.feasible !== \"boolean\"" in validation
    assert "binding_site_ids" in validation
    assert "curtailed_site_ids" in validation
    assert "connection_results" in validation
    assert "site_diagnostics" in validation
    assert "generator_dispatch_results" in validation
    assert "dispatch_mw" in validation
    assert "total_mwh" in validation
    assert "diagnostics.feasible === true" in diagnostics
    assert "diagnostics.feasible === true" in result
    assert "Boolean(diagnostics.feasible" not in javascript


def test_source_contract_keeps_map_resource_ids_separate_from_connection_site_ids():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    binding = javascript_function(javascript, "bindingResourceIds")

    assert "binding_resources" in binding
    assert "diagnostics.binding_resources" in binding
    assert "binding_site_ids" not in binding
    assert "curtailed_site_ids" not in binding
    assert "mapResourceId" in javascript
    assert "filter(Boolean)" in binding
    assert "^(?:bus|corridor):" in javascript


def test_source_contract_clamps_pointer_and_keyboard_tooltips_to_map_frame():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    positioning = javascript_function(javascript, "positionMapTooltip")
    handlers = javascript_function(javascript, "resourceEventHandlers")

    assert 'id="map-frame"' in html
    assert "tooltip.offsetWidth" in positioning
    assert "tooltip.offsetHeight" in positioning
    assert "getBoundingClientRect()" in positioning
    assert "frame.width - tooltipWidth" in positioning
    assert "frame.height - tooltipHeight" in positioning
    assert "Math.min" in positioning and "Math.max" in positioning
    assert "resource.node" in positioning or "resource.node" in handlers
    assert "node.addEventListener(\"focus\"" in handlers
    assert "showMapTooltip(resource)" in handlers
    hide = javascript_function(javascript, "hideMapTooltip")
    assert 'document.activeElement?.getAttribute("aria-describedby") === tooltipId' in hide
    assert '"map-tooltip"' in hide
    assert "return" in hide


def test_map_source_normalizes_evaluator_resource_ids_for_post_evaluation_highlights():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function normalizeBindingId" in javascript
    assert "normalizeBindingId(value)" in javascript
    assert "diagnostics.binding_resources" in javascript
    assert "binding.has(normalizeBindingId(corridor.corridor_id))" in javascript
    assert "binding.has(normalizeBindingId(bus.bus_id))" in javascript


def test_map_source_has_deterministic_ercot_and_us_locator_fallbacks():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "DEFAULT_ERCOT_FOOTPRINT" in javascript
    assert "DEFAULT_US_LOCATOR" in javascript
    assert "const footprint =" in javascript
    assert "const locatorForRender" in javascript
    assert "renderLocator($(\"map-locator-layer\"), locatorForRender)" in javascript


def test_map_source_invalidates_stale_results_and_validates_server_response():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function invalidateEvaluation" in javascript
    assert "function handlePlanInputChange" in javascript
    assert "function validateEvaluationPayload" in javascript
    assert "validateEvaluationPayload(payload)" in javascript
    assert '$("plan-form").addEventListener("input", handlePlanInputChange)' in javascript
    assert '$("plan-form").addEventListener("change", handlePlanInputChange)' in javascript


def test_validation_cleanup_clears_invalid_state_from_all_repeatable_cards():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    cleanup = javascript_function(javascript, "clearFormErrors")

    assert 'document.querySelectorAll(".repeatable-card.is-invalid")' in cleanup
    assert '"#connection-cards"' not in cleanup
    assert '"#generator-cards"' not in cleanup


def test_evaluation_button_remains_available_for_ordinary_client_validation_errors():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    invalidate = javascript_function(javascript, "invalidateEvaluation")
    evaluate = javascript_function(javascript, "evaluatePlan")
    populate = javascript_function(javascript, "populateScenario")
    load = javascript_function(javascript, "loadScenario")

    assert '$("evaluate-button").disabled = !state.scenario' in invalidate
    assert '$("evaluate-button").disabled = false' in populate
    assert 'const plan = buildCanonicalPlan();' in evaluate
    assert evaluate.index('const plan = buildCanonicalPlan();') < evaluate.index('button.disabled = true;')
    assert '$("evaluate-button").disabled = true' in load


def test_form_source_rejects_blank_numeric_values_with_field_specific_errors():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "rawValue.trim() === \"\"" in javascript
    assert "setFieldError(field, `${label} is required.`)" in javascript
    assert 'readNumericField(capacityField, "Generator capacity"' in javascript
    assert 'readNumericField(costField, "Generator marginal cost"' in javascript


def test_legend_source_switches_to_evaluator_diagnostics_after_evaluation():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function renderLegend" in javascript
    assert "legend-low-item" in javascript
    assert "legend-high-item" in javascript
    assert "legend-clear-item" in javascript
    assert "renderLegend()" in javascript


def test_source_clears_result_state_when_evaluation_fails():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    error_renderer = javascript.split("function renderEvaluationError", 1)[1].split("async function evaluatePlan", 1)[0]

    assert "state.result = null" in error_renderer
    assert "renderMap()" in error_renderer
    assert "renderLegend()" in error_renderer


def test_source_validates_scenario_shape_and_bounds_horizon_before_form_creation():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "const MAX_TIME_HORIZON" in javascript
    assert "function validateScenarioPayload" in javascript
    assert "validateScenarioPayload(scenario)" in javascript
    assert "time_horizon must be an integer within" in javascript


def test_source_requires_all_rendered_score_components_without_zero_defaults():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "const requiredScoreFields" in javascript
    assert "requiredScoreFields.find" in javascript
    assert "score.energy_cost" in javascript
    assert "-finiteNumber(score.energy_cost)" not in javascript


def test_source_matches_server_plan_ranges():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "max: 1" in javascript
    assert "max: state.scenario.time_horizon" in javascript
    assert "max: 1" in javascript
    assert "Profile period" in javascript
    assert 'readNumericField($("curtailment-depth"), "Curtailment depth μ", { min: 0, max: 1 })' in javascript


def test_source_enforces_nonnegative_fees_in_javascript_validation():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'readNumericField($("flexibility-fee"), "Flexibility fee", { min: 0 })' in javascript
    assert 'readNumericField(costField, "Generator marginal cost"' in javascript


def test_source_rejects_negative_scenario_numeric_data():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "const isNonNegativeNumberArray" in javascript
    assert "isNonNegativeNumberArray(bus.headroom_mw_by_time)" in javascript
    assert "isNonNegativeNumberArray(corridor.capacity_mw_by_time)" in javascript
    assert "isNonNegativeNumberArray(prices.energy_price_per_mwh)" in javascript
    assert "isNonNegativeNumberArray(prices.it_value_per_mwh)" in javascript
    assert "isNonNegativeNumberArray(payload.rules.base_load_mw_by_time)" in javascript


def test_workflow_integration_contracts_connect_network_plan_and_evaluation():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="plan-summary"' in html
    assert 'id="plan-summary-sites"' in html
    assert 'id="evaluation-summary"' in html
    assert 'id="explore-network-button"' in html
    assert "function addConnectionAtBus" in javascript
    assert 'button.textContent = `Add connection at ${id}`' in javascript
    assert "function updatePlanSummary" in javascript
    assert "function updateConnectionCardSummaries" in javascript
    assert "function focusResource" in javascript
    assert "Binding / flagged" in javascript
    assert "evaluation-summary" in javascript
    assert "data-resource-id" in javascript
    assert "Phase 2" not in html


def test_workflow_parameter_and_diagnostic_copy_remain_explicit():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "K ∈ {0,…,T}" in html
    assert "μ ∈ [0,1]" in html
    assert "resource-link" in javascript
    assert "No flagged resources" in javascript


def test_minimalist_network_layout_contract_preserves_drawer_and_map_ids():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="geographic-map-frame"' in html
    assert 'id="resource-drawer"' in html
    assert "font-size:16px" in css
    assert "grid-template-columns:1fr" in css
    assert "height:clamp(560px,52vw,700px)" in css
    assert ".map-panel>.resource-drawer{grid-column:1" in css
    assert "project-mark-glyph" not in html


def test_plan_and_evaluation_hierarchy_contract_preserves_existing_surfaces():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="plan-summary"' in html
    assert 'id="evaluation-summary"' in html
    assert 'id="raw-results"' in html
    assert ".plan-panel .fieldset-block" in css
    assert ".plan-summary{display:flex" in css
    assert ".result-hero" in css
    assert ".raw-details" in css


def test_cozy_pixel_scientific_visual_system_contract():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "--font-display" in css
    assert "--paper:#f3e6c8" in css or "--paper: #f3e6c8" in css
    assert "--green:#5f8d4e" in css
    assert "--danger:var(--brick)" in css
    assert "--shadow:3px 3px 0" in css or "--shadow: 3px 3px 0" in css
    assert ".pixel-display" in css
    assert ".pixel-control" in css


def test_focused_cozy_art_direction_contract_uses_stepped_frames_and_result_board():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert '--font-display:"Pixelify Sans"' in css
    assert ".panel::after" in css
    assert "clip-path:polygon" in css
    assert ".panel-title-plate" in css
    assert ".header-status-strip" in css
    assert ".section-nav a[aria-current=\"true\"]::before" in css
    assert ".map-engineering-grid" in css
    assert ".result-board" in css
    assert 'id="result-board"' in html
    assert 'id="header-status-strip"' in html



def test_source_requires_evaluation_arrays_to_match_scenario_horizon():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "const isFiniteNumberArrayOfLength" in javascript
    assert "isFiniteNumberArrayOfLength(recourse.curtailed_mw, horizon)" in javascript
    assert "isFiniteNumberArrayOfLength(recourse.residual_unserved_mw, horizon)" in javascript
    assert "isFiniteNumberArrayOfLength(diagnostics.network_available_capacity_mw, horizon)" in javascript
    assert "isFiniteNumberArrayOfLength(diagnostics.balance_error_mw, horizon)" in javascript
    assert "intervention_times" in javascript


def test_geographic_map_uses_local_authoritative_boundary_and_corrected_projection():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    boundary = WEB_ROOT / "texas-boundary.json"

    assert boundary.exists()
    assert '"source":"U.S. Census Bureau 2025 Cartographic Boundary File, 1:500,000 state boundary"' in boundary.read_text(encoding="utf-8")
    assert "REGIONAL_TEXAS_POLYGON" not in javascript
    assert "REGIONAL_TEXAS_SOUTHERN_WESTERN_BORDER" not in javascript
    assert "REGIONAL_TEXAS_COAST" not in javascript
    assert "Math.cos" in javascript
    assert "geographic-highway-line" not in javascript
    assert "TEXAS_BOUNDARY.rings" in javascript


def test_server_serves_local_authoritative_boundary_asset(running_server):
    response, body = request(running_server, "/texas-boundary.json")

    assert response.status == 200
    assert response.getheader("Content-Type").startswith("application/json")
    assert b'"source":"U.S. Census Bureau 2025 Cartographic Boundary File' in body


def test_geographic_recovery_is_texas_focused_and_reports_boundary_failure():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "function geographicBounds" in javascript
    assert "TEXAS_BOUNDARY.error" in javascript
    assert "geographic-map-status" in html
    assert "neighboring states" not in html.lower()
    assert "northern mexico" not in html.lower()
    assert "geographic-regional-land" not in javascript
    assert ".geographic-regional-land" not in css
    assert ".geographic-gulf-water" not in css
    assert ".geographic-highway-line" not in css


def test_geographic_controls_keep_reset_width_independent_from_zoom_squares():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'class="secondary-button map-control-square"' in html
    assert 'class="secondary-button map-control-reset"' in html
    assert ".map-control-square" in css
    assert ".map-control-reset" in css
    assert "width:42px" not in css.split(".geographic-map-actions", 1)[1].split(".map-legend", 1)[0]


@pytest.mark.parametrize(
    ("path", "content_type", "expected_fragment"),
    [
        ("/", "text/html", "ERCOT Practice Interface"),
        ("/styles.css", "text/css", ".app-shell"),
        ("/app.js", "application/javascript", "loadScenario"),
        ("/texas-counties.json", "application/json", '"features"'),
        ("/texas-boundary.json", "application/json", '"rings"'),
        ("/data/ercot-public-network.json", "application/json", '"branches"'),
    ],
)
def test_server_serves_allowed_web_assets(running_server, path, content_type, expected_fragment):
    response, body = request(running_server, path)

    assert response.status == 200
    assert response.getheader("Content-Type").startswith(content_type)
    assert int(response.getheader("Content-Length")) == len(body)
    assert expected_fragment.encode("utf-8") in body


@pytest.mark.parametrize(
    "path",
    [
        "/fonts/IBMPlexSans-Regular.woff2",
        "/fonts/IBMPlexSans-SemiBold.woff2",
        "/fonts/IBMPlexMono-Regular.woff2",
        "/fonts/SourceSerif4-Regular.ttf",
        "/fonts/SourceSerif4-SemiBold.ttf",
    ],
)
def test_server_serves_local_font_assets(running_server, path):
    response, body = request(running_server, path)

    assert response.status == 200
    expected_type = "font/ttf" if path.endswith(".ttf") else "font/woff2"
    assert response.getheader("Content-Type").startswith(expected_type)
    assert int(response.getheader("Content-Length")) == len(body)
    assert body


@pytest.mark.parametrize(
    "path",
    [
        "/unknown.js",
        "/../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "/web/../pyproject.toml",
    ],
)
def test_server_rejects_unknown_and_traversal_assets(running_server, path):
    response, body = request(running_server, path)

    assert response.status == 404
    assert response.getheader("Content-Type").startswith("application/json")
    assert b"[project]" not in body
    assert b"internal server" not in body.lower()


def test_static_routes_ignore_query_strings(running_server):
    response, body = request(running_server, "/styles.css?cache=1")

    assert response.status == 200
    assert b".app-shell" in body


def test_results_shell_has_read_only_summary_map_inspector_and_states():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'id="results-view"' in html
    assert 'data-results-mode="readonly"' in html
    for element_id in (
        "results-round-name",
        "results-team-name",
        "results-feasibility",
        "results-service-fraction",
        "results-score",
        "results-map-mount",
        "results-team-inspector",
        "results-aggregate-summary",
        "results-loading-state",
        "results-unavailable-state",
        "results-malformed-state",
    ):
        assert f'id="{element_id}"' in html

    assert 'src="/results.js"' in html
    assert 'id="results-view"' in html and 'hidden' in html.split('id="results-view"', 1)[1][:120]
    results_block = html.split('id="results-view"', 1)[1].split("</main>", 1)[0]
    for forbidden in ("plan-form", "evaluate-button", "submit-plan-button", "instructor-controls"):
        assert forbidden not in results_block


def test_results_loader_fetches_only_sanitized_static_artifacts_and_exposes_contract():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8") if (WEB_ROOT / "results.js").exists() else ""

    for function_name in (
        "loadResultsPackage",
        "validateBrowserPackage",
        "renderResultsSummary",
        "renderTeamReport",
        "renderAggregateSummary",
        "renderResultsState",
    ):
        assert f"function {function_name}" in javascript

    for artifact in (
        "round_metadata.json",
        "public_network.json",
        "team_report.json",
        "aggregate_grid_summary.json",
    ):
        assert f"/data/results/{artifact}" in javascript

    assert "results.v1" in javascript
    assert "schema_version" in javascript
    assert "Promise.all" in javascript
    assert "fetch(" in javascript
    assert 'fetch("/texas-boundary.json"' in javascript
    assert 'fetch("/texas-counties.json"' in javascript
    assert "renderResultsState(pkg.round.status === \"unavailable\" ? \"unavailable\" : \"ready\")" in javascript


def test_results_mode_hides_practice_shell_and_isolates_practice_bootstrap():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    results_javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")

    assert 'document.querySelector(selector)' in results_javascript
    assert '".site-header"' in results_javascript
    assert '".section-nav"' in results_javascript
    assert "function isResultsViewActive()" in app_javascript
    startup = app_javascript.split('document.addEventListener("DOMContentLoaded"', 1)[1]
    assert "if (isResultsViewActive()) return;" in startup
    assert 'id="results-view"' in html


def test_results_error_states_hide_score_map_and_aggregate_surfaces():
    results_javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")

    for element_id in (
        "results-summary",
        "results-map-panel",
        "results-team-inspector",
        "results-aggregate-summary",
    ):
        assert element_id in results_javascript
    assert "state === \"ready\"" in results_javascript
    assert "node.hidden = !contentVisible" in results_javascript


def run_results_state_in_node(state):
    """Execute result-state rendering against a minimal DOM-like fixture."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for executable results-state tests")

    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    script = f"""
const vm = require("vm");
const source = {json.dumps(javascript)};
const ids = [
  "results-loading-state", "results-unavailable-state", "results-malformed-state",
  "results-summary", "results-map-panel", "results-team-inspector", "results-aggregate-summary"
];
const nodes = Object.fromEntries(ids.map((id) => [id, {{ hidden: false, textContent: "" }}]));
global.window = {{ location: {{ pathname: "/", search: "" }}, addEventListener() {{}} }};
global.document = {{ getElementById(id) {{ return nodes[id] || null; }} }};
vm.runInThisContext(source, {{ filename: "results.js" }});
window.renderResultsState({json.dumps(state)}, "test message");
console.log(JSON.stringify(Object.fromEntries(ids.map((id) => [id, nodes[id].hidden]))));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip())


@pytest.mark.parametrize("state", ["unavailable", "malformed"])
def test_results_state_hides_content_for_error_states(state):
    hidden = run_results_state_in_node(state)

    assert hidden["results-loading-state"] is True
    assert hidden[f"results-{state}-state"] is False
    for element_id in (
        "results-summary",
        "results-map-panel",
        "results-team-inspector",
        "results-aggregate-summary",
    ):
        assert hidden[element_id] is True


def run_results_loader_in_node(responses):
    """Execute the browser loader with deterministic fetch responses."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for executable results-loader tests")

    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    script = f"""
const fs = require("fs");
const vm = require("vm");
const source = {json.dumps(javascript)};
const responses = {json.dumps(responses)};
global.window = {{ location: {{ pathname: "/" }}, addEventListener() {{}} }};
global.document = {{ getElementById() {{ return null; }} }};
global.fetch = async (url) => {{
  const response = responses[url];
  if (!response) throw new Error("missing test response");
  return {{
    status: response.status,
    ok: response.status >= 200 && response.status < 300,
    async json() {{
      if (response.invalid_json) throw new Error("invalid JSON");
      return response.body;
    }}
  }};
}};
vm.runInThisContext(source, {{ filename: "results.js" }});
window.loadResultsPackage()
  .then((value) => console.log(JSON.stringify({{ ok: true, round_status: value.round.status }})))
  .catch((error) => console.log(JSON.stringify({{ ok: false, state: error.state || null, message: error.message }})));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip())


def complete_results_responses():
    return {
        "/data/results/round_metadata.json": {
            "status": 200,
            "body": {"schema_version": "results.v1", "round_id": "r1", "round_name": "Round 1", "team_id": "team-a", "horizon_label": "H1", "status": "published"},
        },
        "/data/results/public_network.json": {
            "status": 200,
            "body": {"schema_version": "results.v1", "buses": [{"bus_id": "b1"}], "branches": []},
        },
        "/data/results/team_report.json": {
            "status": 200,
            "body": {"schema_version": "results.v1", "team_id": "team-a", "feasibility": "feasible", "service_fraction": 1, "score": 10, "score_breakdown": {}, "sites": [{"bus_id": "b1"}], "generators": [], "storage": []},
        },
        "/data/results/aggregate_grid_summary.json": {
            "status": 200,
            "body": {"schema_version": "results.v1", "privacy_policy": "private", "metrics": {}, "stress_periods": []},
        },
    }


def test_results_loader_uses_fixture_defaults_only_when_all_artifacts_are_missing():
    responses = {url: {"status": 404} for url in (
        "/data/results/round_metadata.json",
        "/data/results/public_network.json",
        "/data/results/team_report.json",
        "/data/results/aggregate_grid_summary.json",
    )}

    result = run_results_loader_in_node(responses)

    assert result == {"ok": True, "round_status": "unavailable"}


def test_results_loader_rejects_partially_missing_artifact_package_as_malformed():
    responses = complete_results_responses()
    responses["/data/results/team_report.json"] = {"status": 404}

    result = run_results_loader_in_node(responses)

    assert result["ok"] is False
    assert result["state"] == "malformed"


@pytest.mark.parametrize("mutation", [
    lambda responses: responses["/data/results/team_report.json"].update({"invalid_json": True}),
    lambda responses: responses["/data/results/team_report.json"]["body"].pop("sites"),
    lambda responses: responses["/data/results/public_network.json"]["body"].update({"buses": {}}),
    lambda responses: responses["/data/results/round_metadata.json"]["body"].update({"schema_version": "results.v0"}),
])
def test_results_loader_classifies_malformed_artifacts_as_malformed(mutation):
    responses = complete_results_responses()
    mutation(responses)

    result = run_results_loader_in_node(responses)

    assert result["ok"] is False
    assert result["state"] == "malformed"


def test_results_styles_define_read_only_map_and_state_surfaces():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for selector in (
        ".results-view",
        ".results-map-mount",
        ".results-summary",
        ".results-team-inspector",
        ".results-state",
    ):
        assert selector in css


def test_results_map_mount_has_adapter_and_culling_contract():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    assert "adaptResultsNetwork" in javascript
    assert "renderResultsMap" in javascript
    assert "resultsMapGeometryCulling" in javascript
    assert "resultsMapLabelCulling" in javascript
    assert "results-public-branch" in javascript
    assert ".results-public-branch" in css
    assert ".results-team-resource" in css
    assert ".results-map-viewport" in css
