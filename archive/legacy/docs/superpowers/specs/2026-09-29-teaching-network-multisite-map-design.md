# Teaching-Scale ERCOT Network and Multi-Site Plan Design

## Status

Approved design for the next revision of the local practice interface and evaluator. Implementation has not started.

## Goal

Upgrade the Phase 2 prototype from a three-bus smoke-test fixture and single-site form into an educationally useful, map-first planning exercise. Students should be able to inspect a larger ERCOT-derived teaching network, understand the meaning of buses and corridors directly from the map, and submit a team plan containing multiple connection sites and multiple site-attached generators.

The system remains an instructional abstraction. It is not an official ERCOT model, dispatch tool, interconnection study, market settlement system, or grading service.

## Scope

### In scope

- A teaching-scale ERCOT abstraction with approximately 24–36 buses grouped into recognizable ERCOT regions/zones and approximately 40–60 corridors.
- Map-first presentation with no separate Scenario Brief panel.
- ERCOT-focused SVG map with a U.S. locator inset.
- Hover and keyboard-focus tooltips for buses and corridors.
- Click/tap selection with a persistent detail drawer for the selected bus, corridor, or connection site.
- Period selector for inspecting time-varying headroom and corridor capacity.
- Team plans containing multiple connection sites.
- Multiple generators, each attached to a connection site.
- Site-level, generator-level, and team-level diagnostics while preserving team-level scoring.
- Short tutorial content and parameter guidance embedded in each panel.
- Backward-compatible conversion of the existing single-site/single-generator plan shape where practical.

### Out of scope

- Full operational ERCOT transmission data or official geographic/substation fidelity.
- Multi-team persistence, authentication, leaderboard, weekly deadlines, or first-come-first-served adjudication.
- Production deployment.
- Gymnasium/RL integration; the revised plan schema should only make that future work easier.

## Plan model

The canonical plan shape becomes:

```json
{
  "team_id": "team-01",
  "connections": [
    {
      "connection_id": "site-west",
      "bus_id": "bus-west-01",
      "path_corridors": ["corridor-west-central-01"],
      "capacity_mw": 10,
      "profile": [1.0, 1.0, 0.8, 0.8, 1.0, 1.0]
    }
  ],
  "generators": [
    {
      "generator_id": "gen-west-1",
      "connection_id": "site-west",
      "capacity_mw": 5,
      "marginal_cost_per_mwh": 80
    }
  ],
  "intervention_budget_k": 0,
  "curtailment_depth_mu": 0,
  "flexibility_fee_per_mwh": 0
}
```

Each connection has its own bus, selected path, capacity, and time profile. Each generator must reference an existing connection. A team may submit zero or more generators, subject to explicit scenario and UI limits. Team-level flexibility and curtailment parameters apply to the aggregate team plan.

The evaluator must preserve deterministic ordering and validation. Shared corridor limits apply across all sites in a team plan. Site-level allocations and generator dispatch are computed first; team-level revenue and penalties are then aggregated from those results. Diagnostics must identify the affected site, generator, bus, or corridor wherever possible.

The existing one-site fields may be accepted as a compatibility shorthand and normalized internally into `connections[0]` and `generators[0]`. New responses should expose canonical arrays and retain enough legacy information for existing Phase 1 consumers during migration.

## Teaching network and map

The default classroom fixture should contain approximately 24–36 buses and 40–60 corridors distributed across major ERCOT teaching zones. The geometry is schematic and educational, but should preserve relative east/west/north/south relationships and intentionally include a mixture of unconstrained and constrained resources.

The map is the primary scenario-information surface. The separate Scenario Brief panel is removed. The map displays:

- buses with zone labels and headroom state;
- corridors with capacity/congestion state;
- a U.S. locator inset marking the ERCOT region;
- a period selector controlling time-varying values;
- a legend for headroom, flagged/binding resources, and selected resources.

Hovering or keyboard-focusing a bus shows a compact tooltip with ID, zone, headroom, and selected-period guidance. Hovering or focusing a corridor shows ID, endpoints, capacity, and selected-period information. Clicking or tapping opens a persistent detail drawer and can add a bus or corridor to the active connection site. Touch devices use tap in place of hover. All important information must remain accessible through focusable controls and text alternatives.

## Interface layout

- Header: local practice label and explicit educational-use disclaimer.
- Map workspace: large ERCOT schematic, period selector, legend, tooltip layer, and detail drawer.
- Connection-site editor: repeatable cards for adding, editing, duplicating, and removing sites. Each card includes bus, capacity, profile, and corridor selection.
- Generator editor: repeatable cards for adding, editing, and removing generators. Each generator selects a connection site and specifies capacity and marginal cost.
- Team-level controls: team ID, intervention budget `K`, curtailment depth `μ`, and flexibility fee.
- Results panel: feasibility, revenue/score, score components, site allocations, generator dispatch, curtailment, binding resources, and diagnostics.

Each major panel includes a short “What this means” explanation and a short “How to use it” instruction. Numeric controls display valid ranges or examples. At minimum: `K` is a nonnegative integer bounded by the scenario horizon; `μ` and profile multipliers lie in `[0, 1]`; capacities and fees are finite and nonnegative in the browser interface. The server remains authoritative and may reject any malformed or out-of-range request.

## Data flow and compatibility

1. The server loads the teaching-scale scenario and returns network, map, and time-series metadata.
2. The browser renders the map from presentation metadata and uses the selected period for tooltips.
3. The browser builds a canonical multi-site plan and sends it to `/api/evaluate`.
4. The server normalizes compatibility input, validates the canonical plan, evaluates allocation/recourse/scoring, and returns JSON-safe site/generator/team diagnostics.
5. The browser renders only the returned result; it does not implement a second scoring or optimization algorithm.

Presentation metadata must remain excluded from semantic scenario hashes. Map changes alone must not change evaluator identity or score.

## Verification criteria

- Fixture contains the agreed teaching-scale bus and corridor counts, valid map geometry, and time-series data.
- Single-site/single-generator plans continue to evaluate through compatibility normalization.
- Multi-site plans validate, evaluate deterministically, and expose site-level diagnostics.
- Multiple generators dispatch deterministically and remain attached to valid connection sites.
- Shared corridor limits are respected across sites.
- Map tooltips, focus states, tap/click drawers, period switching, and legends reflect the selected scenario period.
- Empty, duplicate, invalid-reference, negative, non-finite, and over-limit inputs receive clear errors.
- Full evaluator, API, UI-source, and documentation test suites pass.
- The interface clearly labels the network and scores as instructional abstractions.

## Future handoff

After this revision is stable, Phase 3 can add persistent multi-team rounds, explicit ordering and curtailment policy, instructor controls, leaderboard semantics, and a Gymnasium wrapper over the canonical plan/action space.
