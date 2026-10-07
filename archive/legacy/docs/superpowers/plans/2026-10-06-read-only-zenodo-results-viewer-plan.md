# Read-Only Zenodo Results Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `/results` viewer that visualizes sanitized round results over the Zenodo-derived Texas network while preserving the existing practice workflow.

**Architecture:** Add a small Python artifact/schema layer and a deterministic packaging script. Serve the package as static JSON, then add a results-only browser mode that reuses the existing geographic map interactions but hides submission/classroom UI. The browser receives only the selected team report and privacy-preserving aggregate summaries.

**Tech Stack:** Python 3.11+, standard-library JSON/path utilities, existing `pytest` suite, dependency-free HTML/CSS/JavaScript, existing SVG map engine.

---

## Files and responsibilities

- Create: `src/ercot_game/results_artifacts.py` — validate the results-package schema and enforce the browser privacy boundary.
- Create: `scripts/build_results_package.py` — convert an evaluation/audit artifact plus the prepared public network into sanitized web JSON files.
- Create: `web/data/results/round_metadata.json` — checked-in small fixture metadata for browser and test use.
- Create: `web/data/results/public_network.json` — checked-in small public-network fixture for tests and local demo; full artifacts remain generated from Zenodo inputs.
- Create: `web/data/results/team_report.json` — checked-in demo team report containing only one team’s data.
- Create: `web/data/results/aggregate_grid_summary.json` — checked-in anonymized aggregate demo statistics.
- Modify: `src/ercot_game/practice_server.py` — serve `/results`, result JavaScript, and result JSON paths through the existing local server.
- Modify: `web/index.html` — add a results-only shell and retain the existing practice shell for the default route.
- Create: `web/results.js` — load the sanitized package and render score, diagnostics, plots, and selected-team layers without changing evaluator logic.
- Modify: `web/app.js` — expose narrowly scoped map rendering/selection helpers or guard practice initialization when results mode is active; do not duplicate evaluator behavior.
- Modify: `web/styles.css` — style the compact results shell and reuse existing map/control styles.
- Create: `tests/test_results_artifacts.py` — schema, privacy, and package-generation tests.
- Modify: `tests/test_practice_server.py` — static results route/content tests.
- Modify: `tests/test_web_assets.py` — results-shell, script-reference, and no-broken-reference checks.
- Modify: `docs/ERCOT_INSTRUCTOR_RELEASE_NOTE.md` — explain artifact generation and privacy rules.

### Task 1: Define and validate sanitized result artifacts

**Files:**
- Create: `src/ercot_game/results_artifacts.py`
- Create: `tests/test_results_artifacts.py`

- [ ] **Step 1: Write failing schema tests.** Test that a valid package requires `schema_version`, `round`, `network`, `team_report`, and `aggregate`; that missing required fields raise a domain-specific `ResultsArtifactError`; and that team report data cannot contain a second team identifier or raw submission payload.

```python
def test_results_package_rejects_missing_team_report():
    with pytest.raises(ResultsArtifactError, match="team_report"):
        validate_results_package({"schema_version": "results.v1", "round": {}, "network": {}, "aggregate": {}})


def test_results_package_rejects_other_team_identifiers():
    payload = valid_package()
    payload["team_report"]["raw_submissions"] = {"team-beta": {"load": [1]}}
    with pytest.raises(ResultsArtifactError, match="raw_submissions"):
        validate_results_package(payload)
```

- [ ] **Step 2: Run the focused tests and verify they fail because the validator is absent.**

Run: `pytest tests/test_results_artifacts.py -q`

Expected: collection or import failure naming `ercot_game.results_artifacts`.

- [ ] **Step 3: Implement the minimal validator and privacy sanitizer.** Define:

```python
class ResultsArtifactError(ValueError):
    pass


def validate_results_package(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate and return a JSON-safe sanitized results package."""


def sanitize_results_package(payload: Mapping[str, object]) -> dict[str, object]:
    """Keep only public network, selected-team report, and safe aggregates."""
```

Require finite numeric values, nonempty IDs, valid network endpoints, and a
declared `privacy_policy`. Reject keys such as `raw_submissions`, `all_teams`,
`joint_csv`, and unredacted audit bundles from the browser package.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run: `pytest tests/test_results_artifacts.py -q`

Expected: all schema/privacy tests pass.

- [ ] **Step 5: Record the changed files and verify the module imports from the project root.**

Run: `python -c "from ercot_game.results_artifacts import ResultsArtifactError, validate_results_package; print('results artifact module ready')"`

Expected: the command prints `results artifact module ready`.

### Task 2: Build the Zenodo-to-web results package

**Files:**
- Create: `scripts/build_results_package.py`
- Create: `web/data/results/round_metadata.json`
- Create: `web/data/results/public_network.json`
- Create: `web/data/results/team_report.json`
- Create: `web/data/results/aggregate_grid_summary.json`
- Modify: `tests/test_results_artifacts.py`

- [ ] **Step 1: Write failing package-generation tests.** Use a tiny network/evaluation fixture and assert that the script emits four JSON files, maps buses and branches to geographic display records, retains only the selected team’s plan, and bins/suppresses aggregate statistics below the privacy threshold.

```python
def test_build_results_package_writes_four_sanitized_files(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    output = build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "results",
        team_id="team-alpha",
    )
    assert sorted(path.name for path in output) == [
        "aggregate_grid_summary.json", "public_network.json",
        "round_metadata.json", "team_report.json",
    ]
```

- [ ] **Step 2: Run the focused test and verify the missing builder causes failure.**

Run: `pytest tests/test_results_artifacts.py::test_build_results_package_writes_four_sanitized_files -q`

Expected: failure because `build_results_package` is not implemented.

- [ ] **Step 3: Implement the package builder.** Accept explicit paths for the Zenodo prepared artifact, evaluation artifact, selected team, and output directory. Emit stable sorted JSON. Use public bus coordinates and branch geometry from the prepared artifact; never fabricate coordinates. Include only display-safe fields such as `bus_id`, `lon`, `lat`, `branch_id`, endpoints, voltage class, and safe capacity summaries. Include the selected team’s own sites/resources and score details. Aggregate system metrics must be rounded and suppressed when fewer than three contributing teams are represented.

- [ ] **Step 4: Generate the small checked-in fixture package and validate it through the same builder/validator.** The fixture must use clearly synthetic test IDs and must not be mistaken for a production Zenodo artifact.

- [ ] **Step 5: Run the focused tests and inspect the emitted JSON for prohibited keys.**

Run: `pytest tests/test_results_artifacts.py -q`

Expected: all package, privacy, and geometry tests pass.

### Task 3: Add static results routes without changing evaluation APIs

**Files:**
- Modify: `src/ercot_game/practice_server.py`
- Modify: `tests/test_practice_server.py`

- [ ] **Step 1: Write failing HTTP tests** for `GET /results`, `GET /results.js`, and the four `/data/results/*.json` paths. Assert the correct content types, no authentication requirement, and a 404 for unknown result assets.

- [ ] **Step 2: Run the tests and verify they fail with route-not-found responses.**

Run: `pytest tests/test_practice_server.py -k results -q`

Expected: failures for the new paths only.

- [ ] **Step 3: Add static mappings** to `_STATIC_ASSETS` and route `/results` to the existing HTML shell with a `data-view="results"` marker or equivalent. Keep `/` unchanged and do not add browser-side evaluation endpoints.

- [ ] **Step 4: Run the HTTP tests and the existing practice-server tests.**

Run: `pytest tests/test_practice_server.py -q`

Expected: the new result-route tests and all existing server tests pass.

### Task 4: Build the read-only results shell and loader

**Files:**
- Modify: `web/index.html`
- Create: `web/results.js`
- Modify: `web/styles.css`
- Modify: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing web-asset tests** requiring a results shell, references to `results.js`, all four result artifacts, a visible missing-results state, and no result-mode submission/evaluation button.

- [ ] **Step 2: Run the tests and verify they fail because the shell and loader are absent.**

Run: `pytest tests/test_web_assets.py -k results -q`

Expected: failures naming the missing results markup/script.

- [ ] **Step 3: Add a results-only semantic shell** with:
  - round/team metadata and status summary;
  - feasibility/service-fraction/score fields;
  - existing geographic map container and controls;
  - selected-team resource inspector;
  - aggregate grid summary and compact chart containers;
  - explicit loading, unavailable, and malformed-package states.

Keep visible text as the accessibility source of meaning. Do not copy the plan editor or expose other-team fields.

- [ ] **Step 4: Implement `results.js`** with `loadResultsPackage()`, `validateBrowserPackage()`, `renderResultsSummary()`, `renderTeamReport()`, `renderAggregateSummary()`, and `renderResultsState()`. Fetch only the four static JSON files, reject schema/version mismatches, and render the selected team’s data. Reuse `app.js` map helpers through a small explicit adapter rather than duplicating coordinate math.

- [ ] **Step 5: Add result-mode styling** that keeps the map dominant, removes old planning-editor panels from the results view, keeps controls keyboard accessible, and preserves the established cozy scientific visual language.

- [ ] **Step 6: Run the web tests and inspect the page at `/results`.**

Run: `pytest tests/test_web_assets.py -k results -q`

Expected: all result-shell contract tests pass.

### Task 5: Connect the Zenodo network to the existing geographic map

**Files:**
- Modify: `web/app.js`
- Modify: `web/results.js`
- Modify: `web/styles.css`
- Modify: `tests/test_map_interaction_performance.py`
- Modify: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing integration-contract tests** requiring public Zenodo buses/branches to be rendered from the results package, selected-team resources to be distinct from public geometry, and labels to be culled at overview zoom.

- [ ] **Step 2: Run the focused tests and verify they fail before the adapter exists.**

Run: `pytest tests/test_map_interaction_performance.py tests/test_web_assets.py -k 'results or network' -q`

- [ ] **Step 3: Add a narrow map adapter** that converts `public_network.json` records to the existing map resource shape. Keep public branches non-focusable, keep only selected-team resources focusable, and preserve zoom/pan/reset/keyboard selection behavior.

- [ ] **Step 4: Implement detail-level rules.** At overview zoom render branches and only major/selected labels; at higher zoom render more branches and bus labels. Measure DOM node counts and render timings rather than assuming the 2,000-bus network is acceptable.

- [ ] **Step 5: Add selected-team overlays and anonymized stress styling.** Selected-team sites are individually identifiable only to the current report. Aggregate congestion is rendered by coarse region/interface bins without team attribution.

- [ ] **Step 6: Run the focused map tests and inspect representative zoom levels manually.**

Run: `pytest tests/test_map_interaction_performance.py tests/test_web_assets.py -q`

Expected: existing selection-performance invariants remain intact and new result-mode tests pass.

### Task 6: Documentation, regression audit, and release verification

**Files:**
- Modify: `docs/ERCOT_INSTRUCTOR_RELEASE_NOTE.md`
- Modify: `docs/ERCOT_MAP_PERFORMANCE.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Document the artifact-generation command, schema version, privacy policy, and `/results` route.** State clearly that the browser is visualization-only and that the evaluator remains authoritative.

- [ ] **Step 2: Add documentation tests** requiring the Zenodo source, selected-team-only report, aggregate suppression policy, and no raw-submission browser contract.

- [ ] **Step 3: Run the full relevant regression suite.**

Run: `pytest tests/test_results_artifacts.py tests/test_practice_server.py tests/test_web_assets.py tests/test_map_interaction_performance.py tests/test_documentation.py -q`

Expected: zero failures.

- [ ] **Step 4: Perform a browser smoke test** at `/` and `/results`: scenario practice still loads, `/results` shows the fixture, map zoom/pan/reset works, selected-team resources update the inspector, and missing/malformed artifacts show readable errors.

- [ ] **Step 5: Run the complete test suite and report any unverified browser behavior.**

Run: `pytest -q`

Expected: no unexplained regressions. Do not claim full browser verification unless it was actually performed.
