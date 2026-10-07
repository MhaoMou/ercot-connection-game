from pathlib import Path
import json
import shutil
import subprocess

from test_web_assets import javascript_function


WEB_ROOT = Path(__file__).parents[1] / "web"
DOC = Path(__file__).parents[1] / "docs/ERCOT_MAP_PERFORMANCE.md"


def test_resource_selection_uses_incremental_dom_updates_without_full_map_render():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    drawer = javascript_function(javascript, "openResourceDrawer")
    close_handler = javascript_function(javascript, "bindEvents")

    assert "updateResourceSelectionState()" in drawer
    assert "renderMap()" not in drawer
    assert 'placeholder.textContent = "Select a Planning Region' in close_handler
    assert "updateResourceSelectionState()" in close_handler


def test_selection_state_has_persistent_lookup_maps_for_both_map_views():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert "resourceElementMaps.schematic" in javascript
    assert "resourceElementMaps.geographic" in javascript
    assert "updateResourceSelectionState" in javascript
    assert "aria-pressed" in javascript_function(javascript, "updateResourceElementState")


def test_selection_metrics_track_render_counters_and_candidate_costs():
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    for name in (
        "selectionMs",
        "planningRenderMs",
        "publicRenderMs",
        "publicCandidateMs",
        "countyRenderMs",
        "publicRenderCount",
        "countyRenderCount",
    ):
        assert name in javascript


def test_map_performance_document_records_selection_invariant():
    document = DOC.read_text(encoding="utf-8")
    assert "Planning Region and Planning Interface selection" in document
    assert "publicRenderCount" in document
    assert "countyRenderCount" in document
    assert "Initial public-network loading" in document


def test_results_map_adapter_preserves_public_privacy_and_focus_invariants():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")

    assert "function adaptResultsNetwork" in javascript
    assert "function renderResultsMap" in javascript
    assert "function setResultsMapView" in javascript
    assert "results-public-branch" in javascript
    assert 'aria-hidden": "true"' in javascript
    assert "tabIndex = 0" in javascript
    assert "team_report.sites" in javascript
    assert "team_report.generators" in javascript
    assert "team_report.storage" in javascript
    assert "resultsMapView" in javascript
    assert "resultsMapLabelCulling" in javascript
    assert "resultsMapGeometryCulling" in javascript


def test_results_map_uses_existing_map_interaction_controls_and_keyboard_contract():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for control_id in (
        "results-map-zoom-in",
        "results-map-zoom-out",
        "results-map-reset",
    ):
        assert control_id in javascript
    assert "ArrowLeft" in javascript
    assert "ArrowRight" in javascript
    assert "ArrowUp" in javascript
    assert "ArrowDown" in javascript
    assert "results-map-viewport" in javascript
    assert ".results-map-controls" in css
    assert ".results-map-viewport" in css


def test_results_map_uses_geographic_context_and_suppresses_raw_bus_labels():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    html = (WEB_ROOT / "results.html").read_text(encoding="utf-8")

    assert "loadResultsGeography" in javascript
    assert "results-geography-layer" in html
    assert "results-county-layer" in html
    assert "results-public-label" not in javascript


def test_results_map_adapter_is_executable_and_does_not_copy_unknown_team_fields():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for executable results-map adapter tests")
    script = f"""
const vm = require('vm');
const source = {json.dumps(javascript)};
global.window = {{ location: {{ pathname: '/not-results', search: '' }} }};
global.document = {{ addEventListener() {{}}, getElementById() {{ return null; }} }};
vm.runInThisContext(source, {{ filename: 'results.js' }});
const payload = {{
  network: {{ buses: [
    {{ bus_id: 'b1', lat: 30, lon: -97 }},
    {{ bus_id: 'b2', lat: 31, lon: -96 }}
  ], branches: [{{ branch_id: 'br1', from_bus: 'b1', to_bus: 'b2' }}] }},
  team_report: {{
    sites: [{{ site_id: 's1', bus_id: 'b1', load_mw: 10 }}],
    generators: [{{ generator_id: 'g1', bus_id: 'b2', capacity_mw: 4 }}],
    storage: [],
    notes: {{ other_team: {{ bus_id: 'b2' }} }}
  }}
}};
const adapted = window.adaptResultsNetwork(payload.network, payload.team_report);
if (adapted.branches.length !== 1 || adapted.buses.length !== 2) throw new Error('network adapter lost public records');
if (adapted.teamResources.length !== 2) throw new Error('team resource adapter lost selected-team records');
if (JSON.stringify(adapted).includes('other_team')) throw new Error('adapter leaked unknown team data');
console.log(JSON.stringify(adapted));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["branches"][0]["focusable"] is False
    assert {resource["kind"] for resource in payload["teamResources"]} == {"site", "generator"}


def test_results_map_renders_sampled_non_focusable_public_bus_layer_and_stress_overlay():
    javascript = (WEB_ROOT / "results.js").read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for executable results-map renderer tests")
    script = f"""
const vm = require('vm');
const source = {json.dumps(javascript)};
class Node {{
  constructor(name) {{ this.name = name; this.attributes = {{}}; this.children = []; this.dataset = {{}}; }}
  setAttribute(key, value) {{ this.attributes[key] = String(value); }}
  getAttribute(key) {{ return this.attributes[key]; }}
  append(...nodes) {{ this.children.push(...nodes); }}
  appendChild(node) {{ this.children.push(node); return node; }}
  replaceChildren(...nodes) {{ this.children = nodes; }}
  addEventListener() {{}}
  removeAttribute(key) {{ delete this.attributes[key]; }}
}}
const svg = new Node('svg');
const mount = new Node('div');
const nodes = {{ 'results-map': svg, 'results-map-mount': mount }};
global.window = {{ location: {{ pathname: '/not-results', search: '' }} }};
global.document = {{
  addEventListener() {{}},
  getElementById(id) {{ return nodes[id] || null; }},
  createElementNS(_namespace, name) {{ return new Node(name); }},
  createElement(name) {{ return new Node(name); }},
  querySelector() {{ return null; }}
}};
vm.runInThisContext(source, {{ filename: 'results.js' }});
const buses = Array.from({{length: 20}}, (_, index) => ({{ bus_id: 'b' + index, lat: 30 + index * 0.05, lon: -97 + index * 0.05 }}));
window.renderResultsMap({{
  network: {{ buses, branches: [{{ branch_id: 'br1', from_bus: 'b0', to_bus: 'b1' }}] }},
  team_report: {{ sites: [{{ site_id: 's1', bus_id: 'b0', load_mw: 10 }}], generators: [], storage: [] }},
  aggregate: {{ region_utilization: [{{ bus_id: 'b1', region_id: 'region-1', utilization: 0.8 }}], stress_periods: [{{ period: 12 }}] }}
}});
function find(node, id) {{ if (node.attributes.id === id) return node; for (const child of node.children) {{ const match = find(child, id); if (match) return match; }} return null; }}
function countClass(node, className) {{ return node.children.reduce((count, child) => count + (String(child.attributes.class || '').split(' ').includes(className) ? 1 : 0) + countClass(child, className), 0); }}
const busLayer = find(svg, 'results-public-bus-layer');
const stressLayer = find(svg, 'results-aggregate-stress-layer');
const teamLayer = find(svg, 'results-team-resource-layer');
if (!busLayer || busLayer.attributes['aria-hidden'] !== 'true') throw new Error('missing hidden public bus layer');
if (countClass(busLayer, 'results-public-bus') !== 2) throw new Error('overview bus sampling is not active');
if (countClass(busLayer, 'results-team-resource') !== 0) throw new Error('team resources leaked into public bus layer');
if (!stressLayer || countClass(stressLayer, 'results-stress-overlay') !== 1) throw new Error('stress overlay was not rendered');
if (stressLayer.attributes['aria-hidden'] !== 'true') throw new Error('stress overlay must be decorative');
if (countClass(teamLayer, 'results-team-resource') !== 1) throw new Error('selected team resource was not rendered');
window.setResultsMapView({{ zoom: 6 }});
const zoomedBusLayer = find(svg, 'results-public-bus-layer');
if (countClass(zoomedBusLayer, 'results-public-bus') <= 2 || countClass(zoomedBusLayer, 'results-public-bus') > 20) throw new Error('zoomed bus layer did not expand within viewport');
console.log('ok');
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ok"


def test_results_map_styles_define_non_focusable_bus_and_stress_layers():
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    assert ".results-public-bus" in css
    assert "pointer-events:none" in css
    assert ".results-stress-overlay" in css
