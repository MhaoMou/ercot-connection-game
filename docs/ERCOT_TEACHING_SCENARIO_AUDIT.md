# Gate 5.5 Teaching Scenario V2 Calibration Audit

Scenario: `ercot-planning-teaching-v2` · version `2.0.0` · planning model `ercot-public-derived-planning@1.0.0`.

## Parameter distributions

| Parameter | Count | Min | Max | Median | Quantiles | Max/min |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Connection headroom (MW) | 72 | 38.21 | 77.78 | 62.12 | p5=44.29, p25=56.29, p50=62.17, p75=67.82, p95=73.58 | 2.04x |
| Planning-interface limit (MW) | 120 | 14.36 | 53.03 | 34.90 | p5=16.32, p25=26.98, p50=35.15, p75=42.85, p95=49.66 | 3.69x |
| Energy price ($/MWh) | 6 | 40.00 | 58.00 | 47.00 | p5=40.00, p25=42.00, p50=45.00, p75=51.00, p95=58.00 | 1.45x |
| IT value ($/MWh) | 6 | 115.00 | 135.00 | 124.00 | p5=115.00, p25=118.00, p50=121.00, p75=129.00, p95=135.00 | 1.17x |

The headroom and interface distributions are intentionally heterogeneous. The smallest interface limits are concentrated in a few documented bottlenecks; no operational rating is implied.

## Standardized 40 MW region comparison

| Region | Feasible | Score | Binding resource |
| --- | --- | ---: | --- |
| PANHANDLE | yes | 18400.00 | — |
| HIGH_PLAINS | yes | 18400.00 | — |
| PERMIAN | yes | 18400.00 | — |
| NORTHWEST | no | 17338.37 | bus:NORTHWEST |
| NORTH | yes | 18400.00 | — |
| NORTH_CENTRAL | yes | 18400.00 | — |
| EAST | yes | 18400.00 | — |
| WEST_CENTRAL | yes | 18400.00 | — |
| CENTRAL_HIGHLANDS | yes | 18400.00 | — |
| HOUSTON_GULF | yes | 18400.00 | — |
| SOUTH_TEXAS | yes | 18400.00 | — |
| RIO_GRANDE | yes | 18400.00 | — |

With no selected planning interface, feasible regions have the same economics because the evaluator intentionally applies common scenario prices/value. Differentiation appears when headroom binds or a project selects shared interfaces; this is a deliberate teaching trade-off rather than a dominant-region artifact.

## Project-size sensitivity

| Project size (MW) | Feasible regions / 12 | Min score | Max score |
| ---: | ---: | ---: | ---: |
| 10 | 12 | 4600.00 | 4600.00 |
| 20 | 12 | 9200.00 | 9200.00 |
| 30 | 12 | 13800.00 | 13800.00 |
| 40 | 11 | 17338.37 | 18400.00 |
| 50 | 9 | -4030.72 | 23000.00 |
| 60 | 4 | -34030.72 | 27600.00 |
| 80 | 0 | -94030.72 | 9036.99 |

The exercise transitions from all regions feasible at small sizes to progressively fewer feasible regions as headroom is exceeded. The transition is gradual rather than a single trivial cutoff.

## Planning-interface relevance

| Interface | Endpoint A | Endpoint B | Binding sizes tested | Classification |
| --- | --- | --- | ---: | --- |
| CENTRAL_HIGHLANDS__HOUSTON_GULF | CENTRAL_HIGHLANDS | HOUSTON_GULF | 30, 40, 50, 60, 80 | frequently relevant |
| CENTRAL_HIGHLANDS__NORTH_CENTRAL | CENTRAL_HIGHLANDS | NORTH_CENTRAL | 40, 50, 60, 80 | occasionally relevant |
| CENTRAL_HIGHLANDS__SOUTH_TEXAS | CENTRAL_HIGHLANDS | SOUTH_TEXAS | 50, 60, 80 | occasionally relevant |
| CENTRAL_HIGHLANDS__WEST_CENTRAL | CENTRAL_HIGHLANDS | WEST_CENTRAL | 40, 50, 60, 80 | occasionally relevant |
| EAST__HOUSTON_GULF | EAST | HOUSTON_GULF | 40, 50, 60, 80 | occasionally relevant |
| EAST__NORTH | EAST | NORTH | 40, 50, 60, 80 | occasionally relevant |
| EAST__NORTH_CENTRAL | EAST | NORTH_CENTRAL | 40, 50, 60, 80 | occasionally relevant |
| HIGH_PLAINS__PANHANDLE | HIGH_PLAINS | PANHANDLE | 40, 50, 60, 80 | occasionally relevant |
| HIGH_PLAINS__PERMIAN | HIGH_PLAINS | PERMIAN | 20, 30, 40, 50, 60, 80 | frequently relevant |
| HIGH_PLAINS__WEST_CENTRAL | HIGH_PLAINS | WEST_CENTRAL | 30, 40, 50, 60, 80 | frequently relevant |
| HOUSTON_GULF__NORTH_CENTRAL | HOUSTON_GULF | NORTH_CENTRAL | 20, 30, 40, 50, 60, 80 | frequently relevant |
| HOUSTON_GULF__SOUTH_TEXAS | HOUSTON_GULF | SOUTH_TEXAS | 40, 50, 60, 80 | occasionally relevant |
| NORTHWEST__PERMIAN | NORTHWEST | PERMIAN | 20, 30, 40, 50, 60, 80 | frequently relevant |
| NORTH_CENTRAL__WEST_CENTRAL | NORTH_CENTRAL | WEST_CENTRAL | 30, 40, 50, 60, 80 | frequently relevant |
| NORTH__NORTH_CENTRAL | NORTH | NORTH_CENTRAL | 50, 60, 80 | occasionally relevant |
| NORTH__PANHANDLE | NORTH | PANHANDLE | 30, 40, 50, 60, 80 | frequently relevant |
| NORTH__WEST_CENTRAL | NORTH | WEST_CENTRAL | 50, 60, 80 | occasionally relevant |
| PANHANDLE__WEST_CENTRAL | PANHANDLE | WEST_CENTRAL | 30, 40, 50, 60, 80 | frequently relevant |
| PERMIAN__WEST_CENTRAL | PERMIAN | WEST_CENTRAL | 40, 50, 60, 80 | occasionally relevant |
| RIO_GRANDE__SOUTH_TEXAS | RIO_GRANDE | SOUTH_TEXAS | 30, 40, 50, 60, 80 | frequently relevant |

## Representative behavioral plans

| Plan | Feasible | Score | Binding resources |
| --- | --- | ---: | --- |
| A — straightforward feasible | yes | 9200.00 | — |
| B — alternative feasible | yes | 9200.00 | — |
| C — region-headroom constrained | no | -4030.72 | bus:NORTHWEST |
| D — planning-interface constrained | no | -65133.21 | corridor:HIGH_PLAINS__PERMIAN |
| E — multiple project/generator | yes | 9200.00 | — |
| F — deliberately infeasible | no | -94030.72 | bus:NORTHWEST |
| G — near-boundary feasible | yes | 27600.00 | — |
| H — same project, different region | yes | 18400.00 | — |

## Score-component scale

| Component | Standard 20 MW magnitude |
| --- | ---: |
| it_value | 14900.00 |
| energy_cost | 5700.00 |
| generator_cost | 0.00 |
| flexibility_fee | 0.00 |
| curtailment_cost | 0.00 |
| unserved_penalty | 0.00 |
| total | 9200.00 |

No score component is accidentally orders of magnitude larger than the others in the standard feasible plan. The unserved penalty remains intentionally severe for infeasible service.

## Period sensitivity

Period multipliers: `[0.92, 1.0, 1.05, 0.88, 0.96, 1.02]`. Prices vary from $40–$58/MWh and IT value varies from $115–$135/MWh. The period conditions are not identical, and the lowest headroom occurs in Period 4 while the highest value occurs in Period 4.

## Calibration decision

No Teaching Scenario V2 calibration changes were required in this audit. The scenario has varied region headroom, a mix of interface relevance, gradual project-size transitions, period variation, and specific binding-resource diagnostics. Planning Model V1 and evaluator mathematics remain unchanged.
