# Phase 2 Local Practice Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a dependency-free local browser practice app that displays the ERCOT-derived scenario on a map, accepts one structured team plan, calls the Phase 1 evaluator, and renders score and grid diagnostics.

**Architecture:** Add a small `ThreadingHTTPServer` API layer around the existing evaluator and serve static HTML/CSS/JavaScript assets from the same process. Keep presentation metadata separate from evaluator semantics in the canonical hash. The browser receives scenario/map JSON, posts one `TeamPlan` payload, and receives a JSON-safe evaluation result or structured validation error.

**Tech Stack:** Python 3.11+ standard library (`http.server`, `threading`, `json`, `urllib`), static HTML/CSS/JavaScript, `pytest`; no frontend framework, database, external map tiles, or new runtime dependency.

---

## Scope boundary

This plan implements only a local single-team practice tool. It does not add authentication, persistent storage, official deadlines, multi-team rankings, Electrify execution, real-time data, or Gymnasium wrappers. The Phase 1 evaluator remains authoritative and must continue to pass unchanged.

## File map

- Create: `src/ercot_game/practice_server.py` — local HTTP server, routing, request parsing, and evaluator calls.
- Create: `src/ercot_game/practice_serialization.py` — JSON-safe scenario, plan, result, and error response serialization.
- Create: `web/index.html` — practice page structure.
- Create: `web/styles.css` — layout, status colors, responsive styling, map legend.
- Create: `web/app.js` — browser state, API calls, form serialization, SVG map rendering, and result rendering.
- Modify: `src/ercot_game/models.py` — optional presentation-only fields for buses/corridors, if needed by the fixture serializer.
- Modify: `src/ercot_game/io.py` — serialize presentation metadata while excluding it from semantic input hashing.
- Modify: `src/ercot_game/validate.py` — validate presentation metadata without changing score semantics.
- Modify: `data/fixtures/ercot_small.json` — add ERCOT map geometry and bus/corridor presentation metadata.
- Modify: `pyproject.toml` — add an `ercot-game-practice` console entry point.
- Create: `tests/test_practice_serialization.py` — JSON-safe response and error tests.
- Create: `tests/test_practice_server.py` — HTTP API tests using an ephemeral local port.
- Create: `tests/test_web_assets.py` — static asset and required UI-element smoke tests.
- Create: `tests/test_documentation.py` — documentation contract, path, link, and command checks.
- Modify: `README.md` — local practice-server commands and endpoint documentation.
- Modify: `docs/phase-1-evaluator.md` — Phase 2 practice-server handoff note.
- Create: `docs/phase-2-practice-interface.md` — operator guide for the local browser interface.
- Create: `docs/phase-2-handoff.md` — Phase 3 roadmap and research handoff.

## API contract

### `GET /api/health`

Return HTTP 200:

```json
{
  "status": "ok",
  "evaluator_version": "0.3.0"
}
```

### `GET /api/scenario`

Return HTTP 200 with:

```json
{
  "scenario_id": "ercot-small-week-01",
  "evaluator_version": "0.3.0",
  "time_horizon": 6,
  "buses": [],
  "corridors": [],
  "prices": [],
  "rules": {},
  "map": {"footprint": [], "locator": {}, "bus_coordinates": {}, "corridor_paths": {}}
}
```

Presentation metadata such as latitude, longitude, zones, footprint, and SVG geometry must not alter evaluator input hashes or scores. The server should expose it in the API response, while the evaluator's semantic hash excludes those fields.

### `POST /api/evaluate`

Accept JSON:

```json
{
  "plan": {
    "team_id": "practice-team",
    "bus_id": "bus-west-constrained",
    "path_corridors": ["corridor-west"],
    "capacity_mw": 10.0,
    "profile": [0.8, 0.9, 1.0, 0.9, 0.7, 0.6],
    "generator": null,
    "intervention_budget_k": 1,
    "curtailment_depth_mu": 0.2,
    "flexibility_fee_per_mwh": 1.0
  }
}
```

Return HTTP 200 with JSON-safe evaluation output on success. Return HTTP 400 for malformed JSON or missing `plan`, HTTP 422 for validation/evaluator input errors, and HTTP 500 for unexpected failures without exposing tracebacks.

## Task 1: Add presentation-only map metadata

**Files:**
- Modify: `src/ercot_game/models.py`
- Modify: `src/ercot_game/io.py`
- Modify: `src/ercot_game/validate.py`
- Modify: `data/fixtures/ercot_small.json`
- Create: `tests/test_presentation_metadata.py`

- [x] **Step 1: Write failing metadata tests**

Assert that fixture buses and corridors expose presentation metadata, that it round-trips through scenario serialization, and that changing only map metadata leaves the evaluator's semantic input hash unchanged.

- [x] **Step 2: Run focused tests and verify failure**

Run:

```bash
pytest tests/test_presentation_metadata.py -q
```

Expected: FAIL because presentation fields and semantic-hash filtering do not exist.

- [x] **Step 3: Implement presentation fields and semantic filtering**

Add optional, JSON-serializable presentation mappings to `Bus` and `Corridor`. Store a schematic ERCOT footprint, a US locator inset, bus coordinates/zones, and corridor paths in the fixture. Ensure canonical evaluator hashing strips presentation-only fields before hashing. Validate coordinate/path shapes and finite numeric values, but do not let presentation data enter score calculations.

- [x] **Step 4: Run tests and the Phase 1 suite**

Run:

```bash
pytest tests/test_presentation_metadata.py -q
pytest -q
```

Expected: focused tests pass and all existing Phase 1 tests remain green.

## Task 2: Implement JSON-safe practice serialization

**Files:**
- Create: `src/ercot_game/practice_serialization.py`
- Create: `tests/test_practice_serialization.py`

- [x] **Step 1: Write failing serialization tests**

Test scenario response construction, successful result serialization, typed validation-error responses, and removal of internal traceback details. Assert that serialized JSON contains `evaluator_version`, `input_hash`, score components, allocation, recourse, and diagnostics.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_practice_serialization.py -q
```

Expected: FAIL because the practice serialization module does not exist.

- [x] **Step 3: Implement pure serialization helpers**

Define:

```python
def scenario_response(scenario: Scenario) -> dict: ...
def evaluation_response(result: EvaluationResult) -> dict: ...
def error_response(code: str, message: str, *, evaluator_version: str | None = None) -> dict: ...
```

Return only JSON-compatible values: lists instead of tuples, primitive values, and nested dictionaries. Keep error payloads stable and avoid serializing exception tracebacks.

- [x] **Step 4: Run focused tests and commit-equivalent checkpoint**

Run:

```bash
pytest tests/test_practice_serialization.py -q
```

Expected: PASS.

## Task 3: Implement the local HTTP practice server

**Files:**
- Create: `src/ercot_game/practice_server.py`
- Create: `tests/test_practice_server.py`
- Modify: `pyproject.toml`

- [x] **Step 1: Write failing HTTP API tests**

Start the server on an ephemeral port in a fixture and test:

```text
GET /api/health -> 200 JSON status
GET /api/scenario -> 200 JSON with 6 periods and map metadata
POST /api/evaluate valid plan -> 200 with score and diagnostics
POST malformed JSON -> 400 structured error
POST missing plan -> 400 structured error
POST invalid plan -> 422 deterministic validation messages
POST evaluator input error -> 422 with evaluator version
GET unknown path -> 404
```

Assert that repeated requests do not mutate the loaded scenario and that response JSON is deterministic.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_practice_server.py -q
```

Expected: FAIL because the server module and routes do not exist.

- [x] **Step 3: Implement the server and entry point**

Use `ThreadingHTTPServer` with a handler factory that receives an immutable loaded scenario and default configuration. Implement explicit `GET`/`POST` routing, `Content-Type: application/json`, `Content-Length`, request-body limits, and structured error responses. Never mutate the shared scenario. Add:

```toml
[project.scripts]
ercot-game-practice = "ercot_game.practice_server:main"
```

The `main()` function should accept `--scenario`, `--host`, and `--port`, defaulting to the Phase 1 fixture and localhost with an ephemeral port when `--port 0` is supplied.

- [x] **Step 4: Run API tests and the Phase 1 suite**

Run:

```bash
pytest tests/test_practice_server.py -q
pytest -q
```

Expected: PASS with no Phase 1 regressions.

## Task 4: Build the ERCOT practice page and map

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/app.js`
- Create: `tests/test_web_assets.py`
- Modify: `src/ercot_game/practice_server.py`

- [x] **Step 1: Write static-asset smoke tests**

Assert the page contains the practice title, scenario panel, plan fields, map container, evaluate button, results panel, and practice-only disclaimer. Assert the server serves CSS and JavaScript with the correct content types.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_web_assets.py -q
```

Expected: FAIL because the web assets do not exist.

- [x] **Step 3: Implement the UI**

Build a responsive single-page interface with:

- scenario/rules panel;
- SVG schematic ERCOT map with footprint, locator inset, bus nodes, corridor paths, legend, and click-to-select behavior;
- plan editor synchronized with map selection;
- practice evaluation button with pending state and duplicate-submit prevention;
- results panel for feasibility, score components, allocation, curtailment, unserved energy, generator dispatch, binding resources, evaluator version, and input hash;
- structured error display that preserves valid form values.

The browser should use `fetch('/api/scenario')` and `fetch('/api/evaluate', {method: 'POST', ...})`. It must not reimplement scoring or feasibility logic. Map coloring must use returned API diagnostics, not local assumptions.

- [x] **Step 4: Run asset/API tests and manual smoke check**

Run:

```bash
pytest tests/test_web_assets.py tests/test_practice_server.py -q
PYTHONPATH=src python -m ercot_game.practice_server --scenario data/fixtures/ercot_small.json --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`, select a bus, submit the example plan, and verify that the score and map state update. Stop the local server after the smoke check.

## Task 5: Document and hand off Phase 2

**Files:**
- Modify: `README.md`
- Modify: `docs/phase-1-evaluator.md`
- Create: `docs/phase-2-practice-interface.md`
- Create: `docs/phase-2-handoff.md`
- Create: `tests/test_documentation.py`

- [x] **Step 1: Add documentation tests or checks**

Verify that the documented commands match `main()` arguments and that the endpoint names in the docs match the server routes.

- [x] **Step 2: Document usage and boundaries**

Document:

- starting the local practice server;
- API endpoints and status codes;
- the ERCOT schematic-map abstraction;
- practice-only semantics;
- no persistence/authentication/official grading;
- migration points for Phase 3;
- exact verification commands.

- [x] **Step 3: Run final Phase 2 verification**

Run:

```bash
pytest -q
PYTHONPATH=src python -m ercot_game.practice_server --help
```

Verified: documentation checks and the full non-socket pytest suite pass; the practice server help output exposes --scenario, --host, and --port. Socket-backed tests require permission to bind a local socket in the execution environment.

## Plan self-review

- Spec coverage: the plan covers the local HTTP architecture, API contract, ERCOT-focused map, plan editor, results panel, state/privacy rules, error handling, tests, and Phase 3 boundaries. It explicitly prevents presentation metadata from changing evaluator hashes or scores.
- Placeholder scan: no `TODO`, `TBD`, or unspecified implementation steps remain.
- Type consistency: `scenario_response`, `evaluation_response`, `error_response`, `practice_server.main`, and the endpoint contracts are defined before their consumers.
- Scope: the plan does not add persistence, authentication, multi-team ranking, Electrify execution, or Gymnasium functionality.
