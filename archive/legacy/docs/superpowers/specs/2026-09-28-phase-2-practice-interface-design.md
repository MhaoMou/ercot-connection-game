# Phase 2 Local Practice Interface Design

## Purpose

Phase 2 adds a local browser-based practice interface on top of the Phase 1 deterministic evaluator. A student should be able to inspect the current ERCOT-derived scenario, choose a connection plan, run a practice evaluation, and understand the resulting allocation, curtailment, score, and diagnostics.

This is a single-team practice tool. It is not yet the official multi-team course service and must not add authentication, a database, official deadlines, persistent grades, or Electrify integration.

## Design goals

1. Make the spatial consequences of a connection decision immediately understandable.
2. Keep the evaluator as the sole source of scoring truth.
3. Keep the browser independent from evaluator internals through a JSON API boundary.
4. Make the UI useful for iterative local experimentation.
5. Preserve a clean migration path to the Phase 3 multi-team service.

## Architecture

Use a dependency-light local browser app:

```text
browser
  -> GET /api/scenario
  -> render ERCOT map and plan editor
  -> POST /api/evaluate
  -> Phase 1 evaluator
  -> JSON result
  -> render score and diagnostics
```

The server should use Python's standard-library `ThreadingHTTPServer`. The browser assets should be static HTML, CSS, and JavaScript. The Phase 1 evaluator remains a normal Python module and is called only by the API layer.

The initial API consists of:

- `GET /` — serve the practice interface.
- `GET /api/health` — return server and evaluator status.
- `GET /api/scenario` — return the scenario, map geometry, rules, and evaluator version.
- `POST /api/evaluate` — accept one structured plan, evaluate it, and return the result or structured validation errors.

The browser may perform light input checks for usability, but all authoritative validation must happen in the Python API before invoking the evaluator.

## ERCOT map visualization

The primary grid visualization is an ERCOT-focused map. A small United States locator inset may be included for orientation, but the full-US map is secondary because all game decisions and constraints are inside ERCOT.

The main map displays:

- the ERCOT footprint;
- candidate buses as selectable nodes;
- transmission corridors as lines;
- bus headroom using color intensity;
- constrained or overloaded resources using orange/red states;
- the selected student connection as a prominent marker;
- optional zone or city labels.

The map uses fixture-provided coordinates and corridor geometry. If the fixture locations are abstract, the UI must label the view as a “schematic ERCOT network view” and avoid implying that nodes are actual substations. A geographic-looking ERCOT outline is acceptable as long as the abstraction is clear.

The Phase 2 fixture should extend the Phase 1 bus and corridor records with optional presentation metadata:

```json
{
  "bus_id": "bus-west-constrained",
  "latitude": 31.2,
  "longitude": -101.5,
  "zone": "West"
}
```

After evaluation, the map should recolor the selected bus and affected corridors using the returned allocation and diagnostic data.

## User workflow

### Scenario panel

Show the scenario ID, evaluator version, time horizon, published prices, configured resource limits, rules, and a short explanation of the flexible-connection parameters.

### Plan editor

Provide controls for:

- team ID;
- bus selection, synchronized with map clicks;
- requested capacity in MW;
- load profile selection or profile values;
- optional generator type, capacity, and marginal cost;
- intervention budget `K`;
- curtailment depth `mu`;
- flexibility fee.

The form should serialize to the exact Phase 1 `TeamPlan` JSON shape. It should not expose evaluator-specific implementation details.

### Evaluation action

The primary action is “Run practice evaluation.” The button should show a pending state, disable duplicate submissions while the request is active, and present structured errors without clearing valid form values.

### Results panel

Display:

- feasible or infeasible status;
- total score;
- score component breakdown;
- allocated capacity and binding resources;
- curtailment amount and intervention timestamps;
- residual unserved energy;
- generator dispatch;
- evaluator version and input hash;
- concise diagnostic messages.

The result should be understandable without reading logs. Raw JSON may be available behind an expandable diagnostics view for debugging.

## State and privacy

Phase 2 is stateless between server restarts. The server loads one configured scenario and evaluates the plan included in each request. It does not store plans or scores in a database and does not expose other teams' actions.

The server may retain the last result in browser memory for display, but it must not treat that result as an official score. The UI should label all results “Practice evaluation.”

## Error handling

- Malformed JSON returns HTTP 400 with a structured error object.
- Invalid plans return HTTP 422 with deterministic validation messages.
- Evaluator input errors return HTTP 422 and include the evaluator version.
- Unexpected evaluator failures return HTTP 500 with a request-safe message and a server-side diagnostic identifier; internal tracebacks must not be shown in the browser.
- The server must never mutate the loaded scenario between requests.

## Testing and verification

The implementation should include:

- unit tests for request parsing and response serialization;
- API tests for health, scenario retrieval, valid evaluation, malformed JSON, invalid plans, and evaluator errors;
- static asset or smoke tests for the practice page;
- a browser-facing smoke path that selects a bus, submits a plan, and renders a score;
- regression tests confirming the Phase 1 full suite remains green.

The API response should be deterministic for the same scenario, evaluator version, and plan. Map presentation metadata must not change score or input hash unless it is explicitly part of the scenario semantics.

## Phase 3 extension points

The following boundaries are intentional:

- replace the local HTTP server with an authenticated service;
- replace the in-memory scenario with a database-backed season state;
- add official submission deadlines and batch evaluation;
- add multi-team ranking and shared-bus competition views;
- dispatch heavy evaluation jobs to Electrify;
- preserve the same evaluator and JSON result schema.

## Explicit non-goals

Phase 2 does not implement:

- authentication or student accounts;
- official scoring or grade export;
- persistent storage;
- multi-team competition;
- real-time market data;
- Electrify execution;
- Gymnasium wrappers;
- production-grade geographic accuracy.
