# Phase 2 Practice Interface Guide

## Scope and authority

Phase 2 is a local browser practice tool for one team and one loaded scenario. It is a thin HTTP and static-asset layer around the Phase 1 evaluator for instructor demonstrations, classroom exercises, and local development. It is not a production service, official ERCOT interface, official grading service, or operational dispatch tool.

The browser validates and serializes input, manages selection/loading/pending/result/error state, and formats returned diagnostics. It does not reimplement allocation, recourse, scoring, optimization, or feasibility logic; the server remains authoritative. The server is the source of truth.

## Scenario model and map

The production default is [`data/teaching/ercot_connection_scenario_v2.json`](../data/teaching/ercot_connection_scenario_v2.json) joined with [`data/processed/ercot_planning_model_v1.json`](../data/processed/ercot_planning_model_v1.json). It has six periods, 12 Planning Regions, 20 Planning Interfaces, instructional prices and IT values, and tutorial hints. Public transmission and generation geography provide context; the Planning Model is a reduced instructional abstraction and is not ERCOT's official electrical network model.

The legacy fixture [`data/fixtures/ercot_small.json`](../data/fixtures/ercot_small.json) remains available for explicit regression/debugging and legacy request-shape tests. It is not the production default.
For legacy regression context, that fixture contains 32 schematic buses, 48 representative corridors, and 8 teaching zones with varied/overlapping resource profiles. The production map retains the same period selector, hover and keyboard-focus interactions, click/tap persistent detail drawer, connection editor, generator editor, and tutorial structure while presenting Planning Regions and Planning Interfaces.

The map is a schematic teaching abstraction and is not operational: it does not show actual substations, a complete ERCOT topology, live geography, external map tiles, or official operating data. Presentation geometry is validated for shape but remains separate from evaluator semantics.

The map-first workflow includes:

- a period selector that requests `GET /api/scenario?period=N` and updates the selected-period bus headroom/corridor capacity snapshot;
- hover and keyboard-focus tooltips for buses and corridors;
- click/tap selection that opens a persistent accessible detail drawer for the selected bus, corridor, or connection site;
- zone labels, legend, ERCOT footprint, US locator inset, and responsive SVG layers;
- “What this means” and “How to use it” tutorial panels;
- repeatable connection/site and generator editors with duplicate/remove controls;
- range labels and field guidance for `K`, `μ`, profile values, connection capacity, flexibility fee, generator capacity, and marginal cost.
- a compact academic header with in-page Network, Plan, Evaluation, and Classroom anchors; the active section is highlighted while sections remain visible in the document flow.
- a wide geographic map presentation with a secondary selected-resource drawer, followed by dense plan configuration and a strict feasibility-first evaluation hierarchy.

The visual system uses local IBM Plex Sans and IBM Plex Mono assets for interface and technical values, plus locally bundled Source Serif 4 regular and semibold assets for academic headings.

## Start the server

From the project directory, use Python 3.11+:

```bash
PYTHONPATH=src python -m ercot_game.practice_server --host 127.0.0.1 --port 8000
```

If installed, the equivalent command is:

```bash
ercot-game-practice --host 127.0.0.1 --port 8000
```

The parser defaults are the production Teaching Scenario V2, host `localhost`, and port `8000`; in plain terms the defaults are host localhost and port 8000. `--scenario`, `--host`, and `--port` override them. To explicitly run the legacy fixture for regression/debugging, use `PYTHONPATH=src python -m ercot_game.practice_server --scenario data/fixtures/ercot_small.json --host 127.0.0.1 --port 8000`. Open <http://127.0.0.1:8000/> after the server is listening. A local health check is `curl http://127.0.0.1:8000/api/health`.

## Canonical editor and legacy request shapes

The editor builds exactly one canonical plan object with non-empty `connections[]` and zero or more `generators[]`:

```json
{
  "team_id": "practice-team",
  "connections": [
    {
      "connection_id": "site-central",
      "bus_id": "bus-central",
      "path_corridors": ["corridor-west-central"],
      "capacity_mw": 10.0,
      "profile": [0.8, 0.9, 1.0, 0.9, 0.7, 0.6]
    }
  ],
  "generators": [
    {
      "generator_id": "gen-central-01",
      "connection_id": "site-central",
      "capacity_mw": 4.0,
      "marginal_cost_per_mwh": 80.0
    }
  ],
  "intervention_budget_k": 1,
  "curtailment_depth_mu": 0.2,
  "flexibility_fee_per_mwh": 1.0
}
```

The connection editor exposes `connection_id`, `bus_id`, `path_corridors`, `capacity_mw`, and one profile value per period. The generator editor exposes `generator_id`, `connection_id`, `capacity_mw`, and `marginal_cost_per_mwh`. Generator connection references must reference an existing connection_id and must point to an existing connection card; duplicate connection/generator IDs and empty cards receive field-specific errors. Removing a site repairs or removes affected generator references, and any site/generator/team edit clears stale results. An empty `generators[]` array produces zero generator dispatch.

The API also accepts the complete legacy single-site shape with `bus_id`, `path_corridors`, `capacity_mw`, `profile`, and nullable nested `generator`, including a JSON value such as `"generator": null`. The server normalizes it to `connection-legacy` and, when needed, `generator-legacy`; canonical and legacy values cannot conflict. Use canonical arrays for multiple sites or generators. `marginal_cost_per_mwh` must be finite and non-negative: the current evaluator/API rejects negative values, and the browser uses the same non-negative range. The UI checks finite, non-negative capacity and marginal cost; server validation always decides the result.

## Browser workflow and ranges

1. The initial client request is `/api/scenario?period=0`; the page displays the scenario identity, six-period horizon, rules, prices, zones, tutorial text, and map.
2. Use the period selector, hover/focus tooltips, or click/tap drawer to inspect buses and corridors. Add, duplicate, or remove connection cards; select buses and corridors; and enter a six-value profile.
3. Add generator cards only after a connection exists. Set a generator ID, connection site, finite non-negative capacity, and finite non-negative marginal cost.
4. Set team-level `K` as a whole number within the scenario horizon, `μ` in `[0, 1]`, non-negative capacities and fees, and profile values in `[0, 1]`. The server repeats these checks and also validates references, IDs, finiteness, and horizon length.
5. Submit “Run practice evaluation.” The browser checks form completeness, sends one JSON object to `/api/evaluate`, shows pending/result/error state, and renders only a schema-validated server response.
6. Read feasibility, total score, score components, connection/site diagnostics, generator dispatch, binding/curtailed resources, evaluator version, and input hash. Use “Show raw server response” for teaching or debugging.

## Static routes and architecture

The read-only results viewer is a separate static presentation of an
instructor-published evaluation round. It loads only sanitized,
evaluator-authoritative artifacts; it does not accept submissions, recompute
dispatch, or expose raw batch-evaluation files or other teams' plans. The
results package consists of one HTML shell, one JavaScript loader, and four
JSON artifacts. These assets are served with `GET` only and are intended for
small, prebuilt publication artifacts rather than uploads. The server's
request-body limit remains 1 MiB for API requests; static results assets have
no upload endpoint and are not generated by the browser.

| Method | Path | Source | Content type |
| --- | --- | --- | --- |
| GET | / | `web/index.html` | `text/html; charset=utf-8` |
| GET | /results | `web/results.html` (dedicated read-only shell) | `text/html; charset=utf-8` |
| GET | /styles.css | `web/styles.css` | `text/css; charset=utf-8` |
| GET | /app.js | `web/app.js` | `application/javascript; charset=utf-8` |
| GET | /results.js | `web/results.js` | `application/javascript; charset=utf-8` |
| GET | /texas-counties.json | `web/texas-counties.json` | `application/json; charset=utf-8` |
| GET | /texas-boundary.json | `web/texas-boundary.json` | `application/json; charset=utf-8` |
| GET | /data/ercot-public-network.json | `web/data/ercot-public-network.json` | `application/json; charset=utf-8` |
| GET | /data/results/round_metadata.json | `web/data/results/round_metadata.json` | `application/json; charset=utf-8` |
| GET | /data/results/public_network.json | `web/data/results/public_network.json` | `application/json; charset=utf-8` |
| GET | /data/results/team_report.json | `web/data/results/team_report.json` | `application/json; charset=utf-8` |
| GET | /data/results/aggregate_grid_summary.json | `web/data/results/aggregate_grid_summary.json` | `application/json; charset=utf-8` |
| GET | /fonts/IBMPlexSans-Regular.woff2 | `web/fonts/IBMPlexSans-Regular.woff2` | `font/woff2` |
| GET | /fonts/IBMPlexSans-SemiBold.woff2 | `web/fonts/IBMPlexSans-SemiBold.woff2` | `font/woff2` |
| GET | /fonts/IBMPlexMono-Regular.woff2 | `web/fonts/IBMPlexMono-Regular.woff2` | `font/woff2` |
| GET | /fonts/SourceSerif4-Regular.ttf | `web/fonts/SourceSerif4-Regular.ttf` | `font/ttf` |
| GET | /fonts/SourceSerif4-SemiBold.ttf | `web/fonts/SourceSerif4-SemiBold.ttf` | `font/ttf` |

Source Serif 4 assets are served from `/fonts/SourceSerif4-Regular.ttf` and `/fonts/SourceSerif4-SemiBold.ttf`; the CSS retains a serif fallback stack for environments that cannot load the local files.

`web/app.js` fetches scenario data, sends canonical plans, renders returned presentation metadata, and formats diagnostics. It contains no second evaluator and uses no frontend framework, database, external tile service, or new runtime dependency.

The public network artifact is an optional, read-only geographic context layer. It is loaded independently from the scenario and evaluator; if it is unavailable, the teaching map and practice evaluation remain usable. Public transmission geometry and EIA plant markers are not teaching buses, evaluator corridors, or inferred electrical connectivity.

## API routes and query syntax

### `GET /api/health`

Returns `200` JSON:

```json
{"status":"ok","evaluator_version":"0.3.0"}
```

### `GET /api/scenario`

Returns `200` JSON containing `scenario_id`, `evaluator_version`, `time_horizon`, canonical `buses` and `corridors`, `zones`, `prices`, `rules`, `metadata`, `presentation`, `map`, and tutorial hints. `GET /api/scenario?period=N` selects the zero-based period `N` and adds `selected_period` values for buses and corridors; for example, `/api/scenario?period=2` selects the third period. The strict period query syntax is exactly one recognized `period` key with an integer in range; repeated, unknown, blank, non-integer, or out-of-range parameters return `400` with `invalid_period`.

### `POST /api/evaluate`

Accepts `{"plan": {...}}` where the plan is canonical or complete legacy form. Canonical and legacy examples are shown above. A successful response is `200` and contains `evaluator_version`, `scenario_id`, `input_hash`, ordered `team_results`, top-level `connection_results`, `generator_dispatch`, `site_diagnostics`, `team_totals`, and `aggregate_diagnostics`.

The response diagnostics are JSON-safe and deterministic for the same loaded scenario and normalized plan. `site_diagnostics` is the identity/basic site-info view (`team_id`, `connection_id`, `bus_id`, and basic nested diagnostics). `connection_results` carries each site's allocation, recourse, score breakdown, and detailed diagnostics; recourse carries served, curtailed, residual-unserved, and unserved values, while team results carry aggregate allocation, recourse, scores, and diagnostics. `generator_dispatch` identifies each generator and connection, its dispatch series, and total MWh. `aggregate_diagnostics` carries resource, binding/curtailment, and unserved summaries. The detailed ownership and balance equation are in the [Phase 1 evaluator handoff](phase-1-evaluator.md#output-and-diagnostics).

| Status | Error code | Meaning |
| --- | --- | --- |
| `200` | — | Successful health, scenario, static-asset, or evaluation response. |
| `400` | `malformed_json`, `missing_plan`, `invalid_period` | Malformed JSON, missing `plan`, or invalid scenario period query. |
| `413` | `request_too_large` | Request body exceeds 1 MiB. |
| `422` | `invalid_plan`, `evaluation_input` | Plan cannot be converted, or strict evaluator validation rejects it; the error includes `evaluator_version` when available. |
| `404` | `not_found` | Route is not an API or static route. |
| `500` | `internal_error` | Unexpected failure; the response includes a generated `request_id`, not a traceback. |

Error bodies use JSON, for example:

```json
{"error":{"code":"invalid_plan","message":"plan payload is malformed"}}
```

The server parses requests without mutating the loaded scenario and closes each response connection. The loaded fixture is not persisted or changed by an evaluation.

## Practice-only boundary

Practice mode remains local and illustrative: it does not submit plans to ERCOT or Electrify and is not a market settlement, dispatch, interconnection approval, or Gymnasium/RL environment. The deployed classroom mode adds authenticated sessions, persisted round state, deadlines, multi-team ordering/ranking, and instructor controls through the Phase 3 service; those features are separate from the local practice evaluator described here.

## Testing and troubleshooting

Run the focused documentation check and full suite:

```bash
pytest tests/test_documentation.py -q
pytest -q
```

Useful checks are:

```bash
pytest tests/test_practice_serialization.py tests/test_practice_server.py tests/test_web_assets.py -q
PYTHONPATH=src python -m ercot_game.practice_server --help
curl http://127.0.0.1:8000/api/health
```

For socket permission errors, use an explicit loopback address and unused high port:

```bash
PYTHONPATH=src python -m ercot_game.practice_server --scenario data/fixtures/ercot_small.json --host 127.0.0.1 --port 8765
```

If binding is denied by the host sandbox, run the process where local loopback sockets are permitted; there is no application-level switch that overrides that policy. If the page shows a structured error, inspect its code and compare IDs, six-period profiles, finite/non-negative capacities and fees, `K`, and bounded `μ` with the server contract.
