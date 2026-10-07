# Team-Owned Local Generation and Storage Design

**Date:** 2026-10-04  
**Status:** Design specification for review  
**Scope:** CSV/DCOPF dispatch path for the data-center competition

## 1. Objective

Represent each student group as a data-center operator that serves its own
computational workload. A group may build a local generator and/or storage at a
connection site. These assets belong exclusively to that group and cannot serve
another group or export power to the network.

The evaluator must optimize each team's local asset operation together with the
shared-grid DCOPF, while preserving the existing no-curtailment rule.

## 2. Core ownership model

For team `m`, site `i`, and operational period `t`:

```text
grid_mit + generation_mit + discharge_mit
    = load_mit + charge_mit
```

`grid_mit` is the team's nonnegative purchase from the shared network. Local
generation and storage reduce that team's grid withdrawal only. They do not
create a common pool that the DCOPF may allocate to other teams.

Exports are not allowed in version 1:

```text
grid_mit >= 0
```

The shared DCOPF receives the aggregate residual grid demand by source bus:

```text
network_demand_it = sum_m grid_mit
```

The network still determines whether the aggregate residual demand is feasible
under generator, branch, and interface constraints.

## 3. Student-submitted asset decisions

Each connection site submits:

- requested load profile `load_mw` by representative period;
- generator capacity `G_mw`, with `0 <= G_mw <= peak requested load_mw`;
- storage energy capacity `B_mwh`, with `0 <= B_mwh <= peak requested load_mw * storage_duration_hours`.

The first implementation should expose both a site-level generator and storage
identifier/capacity. If multiple assets per site are required later, they can be
represented by repeated asset identifiers under a versioned schema extension.

Storage capacity `B` is energy capacity in MWh, not charge/discharge power. The
initial release uses one-hour operating periods, so charge and discharge energy
can be represented numerically as MWh per period. A later schema version may
add an explicit power limit if needed.

## 4. Storage operation

Let `S_mit` be stored energy at the end of period `t`, and let `C_mit` and
`D_mit` be charging and discharging energy during period `t`.

Ideal storage is assumed:

```text
S_mit = S_mi,t-1 + C_mit - D_mit
0 <= S_mit <= B_mi
D_mit <= S_mi,t-1
```

Boundary conditions are:

```text
S_mi,0 = 0.5 * B_mi
S_mi,T >= 0.5 * B_mi
```

The initial half-full condition prevents a team from receiving free initial
energy. The terminal half-full condition prevents teams from emptying storage
solely at the end of the horizon.

Charging and discharging efficiencies are both one. No curtailment or load
shedding is permitted. A simultaneous charge/discharge cycle has no physical or
economic benefit under these assumptions and must not change feasibility or
score.

## 5. Time interpretation

The final course evaluator uses the actual hourly 2028 data rather than six
representative time slots. A submission covers one explicitly selected
half-year block:

- January–June 2028: `4,368` hourly periods;
- July–December 2028: `4,416` hourly periods.

The evaluator uses the actual timestamped hours in the selected block. There is
no artificial `1,460`-hour scoring multiplier in the final half-year evaluator.
Scores are accumulated over the actual hourly periods, and storage state is
advanced one hour at a time.

The prior six-period/`1,460`-hour representation remains available only for
fast sensitivity analysis and early development tests. It must not be used to
interpret final student submissions or storage operation.

## 6. Cost and score treatment

For each team, the score includes:

```text
computational-service value
- purchased electricity cost
- generator operating cost
- storage operating/degradation cost
- generator capital cost
- storage capital cost
- site cost
```

Grid purchases and computational-service value are accumulated over the actual
hourly half-year horizon. Physical asset dispatch and storage state transitions
also remain on one-hour periods.

Generator capital cost is charged on submitted capacity `G`. Storage capital
cost is charged on submitted energy capacity `B`. The storage capital-cost
coefficient must be added to the versioned scoring rules before storage is
enabled in the student schema.

Generator operating cost is charged only for the team's own generator output.
Storage operating cost, if enabled, is charged only for that team's charge or
discharge activity. Electricity used to charge storage is also a team grid
purchase and is charged normally.

## 7. CSV schema direction

The existing long-form CSV remains the base contract. Version 2 should replace
the currently reserved storage fields with explicit local-asset fields:

```csv
team_id,submission_id,period,site_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_energy_mwh
```

The parser must validate:

- one team and submission ID per file;
- known planning-region site IDs;
- timestamps/periods in the selected half-year block;
- nonnegative finite load, generator capacity, and storage capacity;
- generator/storage capacities consistent across all rows for an asset;
- generator capacity no greater than the site's peak requested load;
- storage capacity consistent with the published site-duration limit;
- no duplicate `(period, site, generator, storage)` records.

The schema version and rules version must be retained in evaluation outputs.

## 8. Dispatch architecture

The production DCOPF path should be extended in two stages:

### Stage A: local asset optimization

For each team and period, create local variables for grid purchase, generator
output, storage charging, storage discharging, and state of charge. Enforce the
local balance and asset bounds.

### Stage B: shared network dispatch

Aggregate each team's optimized residual grid demand at its mapped source bus
and solve the shared DCOPF. The implementation may use one joint linear model
containing both local asset variables and network variables, provided ownership
constraints remain explicit and auditable.

If any period is infeasible, the complete submitted batch is infeasible under the
existing competition rule and every team receives the configured infeasible
score. No partial service, curtailment, or first-come-first-served allocation is
introduced.

## 9. Required tests

Add focused tests for:

1. generator output cannot serve another team's load;
2. storage discharge cannot exceed state of charge available at the start of a
   period;
3. storage state remains within `[0, B]`;
4. initial state is `0.5B`;
5. final state is at least `0.5B`;
6. storage charging is reflected in grid purchases;
7. generator capacity and storage capacity are local to each site/team;
8. no-export behavior;
9. January–June and July–December horizons use exactly 4,368 and 4,416 hours,
   respectively;
10. storage transitions use one-hour increments with no annual scoring weight;
11. feasible and infeasible joint batches remain deterministic;
12. legacy storage-containing rows fail clearly under schema version 1 and are
    accepted only under the new versioned schema;
13. score decomposition includes generator and storage capital/operating costs.

## 10. Explicit non-goals

This change does not add:

- curtailment or load shedding;
- storage round-trip inefficiency;
- energy export;
- cross-team asset sharing;
- binary commitment variables;
- new network reduction or evaluator mathematics;
- automatic changes to the currently provisional scoring coefficients.

## 11. Implementation acceptance criteria

The design is implemented when:

- a team-owned generator can reduce only its owner's grid purchase;
- a team-owned battery can shift that team's purchase between periods;
- the state-of-charge and terminal-reserve constraints are enforced;
- the selected 2028 half-year horizon is represented explicitly;
- the CSV contract, leaderboard, and JSON audit record preserve the asset and
  rules versions;
- existing non-storage dispatch tests continue to pass;
- new ownership and storage tests pass;
- the pilot fixtures can be evaluated with deterministic scores.
