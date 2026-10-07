# Phase 1 Evaluator Handoff

## Purpose and authority

Phase 1 is the authoritative offline evaluator for a weekly batch. It is deterministic enough for audit and regression testing, understandable in a classroom, and reusable as the backend of the Phase 2 practice interface. It validates the complete batch, computes shared-resource allocation, applies generator and flexible-curtailment recourse, calculates a score decomposition, and emits a JSON audit artifact.

The fixture evaluator version is `0.3.0`. A result is reproducible from the scenario, evaluator version, scoring configuration, complete plans, and evaluator code. Presentation-only map changes do not change semantic input hashes. The server remains authoritative: browser checks and serialization are convenience layers, not a second evaluator.

## Canonical TeamPlan

The canonical JSON shape is:

```json
{
  "team_id": "team-a",
  "connections": [
    {
      "connection_id": "connection-a",
      "bus_id": "bus-central",
      "path_corridors": ["corridor-west-central"],
      "capacity_mw": 10.0,
      "profile": [0.8, 0.9, 1.0, 0.9, 0.7, 0.6]
    }
  ],
  "generators": [
    {
      "generator_id": "generator-a",
      "connection_id": "connection-a",
      "capacity_mw": 4.0,
      "marginal_cost_per_mwh": 80.0
    }
  ],
  "intervention_budget_k": 1,
  "curtailment_depth_mu": 0.2,
  "flexibility_fee_per_mwh": 1.0
}
```

`connections[]` is non-empty. Each connection has `connection_id`, `bus_id`, `path_corridors`, `capacity_mw`, and `profile`. `generators[]` may be empty; each generator has `generator_id`, `connection_id`, `capacity_mw`, and `marginal_cost_per_mwh`. Every `generators[].connection_id` must reference an existing connection ID in the same team plan. Generators are site-attached rather than free-floating, and dispatch is capped by generator capacity, requested load, and that site's network shortfall.

The team-level controls are `intervention_budget_k` (`K`), `curtailment_depth_mu` (`μ`), and `flexibility_fee_per_mwh`. Strict validation rejects empty connections, duplicate IDs, unknown buses/corridors, unknown generator connection references, mismatched profile lengths, non-finite values, negative capacities/fees, profiles outside `[0, 1]`, `K` outside the horizon, and `μ` outside `[0, 1]`. `marginal_cost_per_mwh` must be finite and non-negative; the current evaluator/API rejects negative values, and the browser uses the same non-negative range.

## Legacy normalization and migration

For migration, a complete legacy plan may use `bus_id`, `path_corridors`, `capacity_mw`, `profile`, and nullable nested `generator` instead of the arrays. The server normalizes it to one connection, represented as one canonical connection with `connection_id: "connection-legacy"`. A present generator becomes one canonical generator attached to that connection; a missing generator ID receives `generator_id: "generator-legacy"`. The team-level controls are unchanged.

Canonical and legacy forms can coexist only when their one-site values agree exactly. A partial legacy set or conflicting canonical/legacy values is rejected. Normalization occurs before validation and semantic hashing, so equivalent canonical and legacy single-site submissions evaluate with the same authoritative meaning. Clients should migrate to canonical arrays for multi-site and multi-generator plans.

## Scenario and fixture

The default fixture path is [`data/fixtures/ercot_small.json`](../data/fixtures/ercot_small.json). It contains 32 schematic buses, 48 representative corridors, six periods, and 8 teaching zones. Every semantic time series has the same six-period horizon. Coordinates, corridor paths, zone labels, the ERCOT footprint, the US locator inset, legend, and tutorial hints are presentation metadata. The network is a teaching abstraction, not official ERCOT topology, an operational model, a market forecast, or an interconnection study.

## Evaluation pipeline

1. Load inputs, resolve configuration, and validate the complete batch. Errors are collected in deterministic sorted order.
2. Normalize legacy plans and canonically order teams, connection IDs, generators, buses, and corridors where ordering affects semantics.
3. Compute each connection's requested load as `capacity_mw * profile[t]`.
4. Aggregate bus requests per bus to calculate bus capacity ratios, then consume shared corridor capacity sequentially in deterministic `(connection_id, team_id)` order.
5. Dispatch each site's generators by `(marginal_cost_per_mwh, generator_id)` within capacity and shortfall limits.
6. Apply bounded flexible curtailment using `K` and `μ`, then calculate score components and balance diagnostics.
7. Emit the evaluator version, semantic input hash, ordered connection/generator results, team totals, and aggregate diagnostics.

The balance invariant is:

```text
requested = served + curtailed + residual_unserved
```

Generator supply is included in served; it is not a separate balance term. Grid supply is recorded separately as `grid_supply_mw`, so a result can distinguish grid supply from generator supply without changing the balance equation.

The algorithm is deterministic and transparent, but intentionally simpler than an optimization-based recourse solver.

## Allocation and scoring

For resource `r` and period `t`, let `A(r,t)` be available capacity and `Q(r,t)` the sum of requests. Bus requests are aggregated per bus; the bus capacity ratio is `1` when `Q` is zero and otherwise `min(1, A/Q)`. Shared corridor capacity is consumed sequentially in deterministic `(connection_id, team_id)` order after bus allocation, and each site's remaining corridor capacity is reduced before the next site is processed. Canonical multi-site plans use this sequential rule; legacy proportional behavior only where applicable remains a compatibility boundary rather than the canonical multi-site corridor rule. Diagnostics record binding and curtailed site IDs.

For each team, the score is:

```text
IT value of served MWh
- grid energy cost
- generator cost
- flexibility fee
- curtailment cost
- residual unserved-energy penalty
```

The result reports `it_value`, `energy_cost`, `generator_cost`, `flexibility_fee`, `curtailment_cost`, `unserved_penalty`, and `total`, plus per-site and per-generator breakdowns.

## Output and diagnostics

The evaluator result contains `scenario_id`, `input_hash`, ordered `team_results`, and `aggregate_diagnostics`. The Phase 2 JSON-safe response also exposes `evaluator_version`, top-level `connection_results`, `generator_dispatch`, `site_diagnostics`, and `team_totals` for a browser or instructor to inspect.

Each team result retains aggregate allocation, recourse, score breakdown, and feasibility diagnostics. site_diagnostics is the identity/basic site-info view: it indexes `team_id`, `connection_id`, `bus_id`, and basic nested diagnostics without duplicating allocation or score fields. connection_results carries allocation, recourse, score_breakdown, and diagnostics for each site; its recourse contains served, curtailed, residual-unserved, and unserved-energy values, while its diagnostics contain binding/resource, grid-supply, and balance information. team results carry aggregate allocation, recourse, scores, and diagnostics; `team_totals` carries team feasibility and total score. `generator_dispatch` identifies `generator_id` and its `connection_id`, dispatch series, and total MWh. aggregate_diagnostics carries resource, binding/curtailment, and unserved summaries together with evaluator version, configuration, scenario metadata, and team count.

## Commands and verification

This checkout is not installed, so `PYTHONPATH=src` is required:

```bash
PYTHONPATH=src python -m ercot_game.cli validate --scenario data/fixtures/ercot_small.json --submissions examples/week_01_submissions.json
PYTHONPATH=src python -m ercot_game.cli evaluate --scenario data/fixtures/ercot_small.json --submissions examples/week_01_submissions.json --output work/week_01_results.json
pytest tests/test_documentation.py -q
pytest -q
```

`validate` returns exit code 0 and prints `valid`; malformed input returns exit code 2 and deterministic error lines. `evaluate` creates its output parent directory and writes stable sorted-key JSON.

## Boundary and limitations

Phase 1 uses linear capacity limits, representative periods, simplified generator dispatch and curtailment, and no AC power flow, voltage, losses, contingencies, unit commitment, security-constrained dispatch, stochastic uncertainty, database, authentication, deadline service, persistent round state, or remote execution. Phase 2 adds only a local single-team practice surface. Multi-team ordering policy, persistence, instructor operations, official grading, and Gymnasium/RL support are future work in the [Phase 2 handoff](phase-2-handoff.md), not current capabilities.
