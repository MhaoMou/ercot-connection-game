from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
JAVASCRIPT = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def test_landing_screen_explains_public_to_instructional_model():
    assert "PUBLIC NETWORK" in HTML
    assert "PLANNING MODEL" in HTML
    assert "TEACHING SCENARIO" in HTML
    assert "public-data-informed instructional planning model" in HTML.lower()


def test_planning_mode_tooltips_use_region_and_interface_terms():
    assert 'planningMode ? "Planning Region" : "Synthetic teaching bus"' in JAVASCRIPT
    assert 'planningMode ? "Planning Interface" : "Teaching corridor"' in JAVASCRIPT
    assert "scenario condition, not a public physical rating" in JAVASCRIPT


def test_planning_map_uses_concise_anchor_labels_without_duplicate_zone_labels():
    assert "humanizePlanningRegionId" in JAVASCRIPT
    assert "Object.entries(zonePositions).filter(() => !planningMode)" in JAVASCRIPT
    assert "planningMode ? humanizePlanningRegionId" in JAVASCRIPT


def test_production_assets_use_relative_paths_only():
    for source in (HTML, JAVASCRIPT):
        assert "/Users/" not in source
        assert "file://" not in source
