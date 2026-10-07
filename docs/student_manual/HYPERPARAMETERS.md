# Hyperparameters and configuration

**Status:** Current repository configuration; instructor review required before student release.

This file is the compact reference for the numerical and behavioral choices used
by the Zenodo-based dispatch game. Each setting is labeled as one of:

- **ZENODO DATASET** — copied from, or directly determined by, the Zenodo U.S. Test System.
- **ONLINE-SOURCE CALIBRATED** — anchored to a public market, engineering, or cost reference and then rounded or mapped into the game.
- **INSTRUCTOR-CHOSEN** — selected for learning objectives, reproducibility, computational tractability, or the student interface.

These labels describe the source of a game setting. They do not mean that any
value is an official ERCOT operating parameter.

## Model hierarchy

    Zenodo U.S. Test System
      buses, branches, generators, costs, and source demand
                         |
                         v
    Instructor game configuration
      half-year calendar, teaching profiles, ownership, scoring
                         |
                         v
    Student CSV submissions
                         |
                         v
    One-hour linear DCOPF evaluation and score

The game uses the Zenodo network directly as the dispatch network. It does not
use the earlier toy webpage network or the retired six-period submission
convention.

## Network and dataset configuration

| Setting | Current value | Source category | Meaning |
|---|---:|---|---|
| Dataset | Zenodo U.S. Test System, [record 4538590](https://doi.org/10.5281/zenodo.4538590) | **ZENODO DATASET** | Source of the dispatch network and catalog |
| Buses | 2,000 | **ZENODO DATASET** | Direct bus identifiers are used in student CSV files |
| Branches | 3,206 | **ZENODO DATASET** | Source branch topology and electrical parameters |
| Substations | 1,250 | **ZENODO DATASET** | Source artifact metadata |
| Zones | 8 | **ZENODO DATASET** | Source zone structure used by prepared demand |
| Existing generators | 598 | **ZENODO DATASET** | Active units come from the generator catalog |
| Demand | Bus-level prepared demand in MW | **ZENODO DATASET** | Fixed inelastic demand input |
| Branch limits | Status, reactance, and thermal limit | **ZENODO DATASET** | Active branch dispatch limits |
| Generator limits | p_min_mw, p_max_mw, and status | **ZENODO DATASET** | Existing-unit operating bounds |
| Existing marginal cost | marginal_cost_c1_per_mwh | **ZENODO DATASET** | Operating cost for a selected catalog generator |
| Dispatch model | Linear DCOPF solved with HiGHS | **INSTRUCTOR-CHOSEN** | Transparent and repeatable teaching model |
| Per-unit base | 100 MVA | **INSTRUCTOR-CHOSEN** | Numerical scaling convention in the dispatch adapter |

The prepared 2016 source artifact contains 8,784 hourly rows. Repository
2017/2018 demand extensions are derived from official ERCOT zonal-load data;
they are experimental extensions, not additional Zenodo-specified operational
years.

## Time horizon and teaching profiles

| Setting | Current value | Source category | Meaning |
|---|---:|---|---|
| Time step | 1 hour | **INSTRUCTOR-CHOSEN** | Each row represents one operating hour |
| 2016 January--June | 4,368 hours | **INSTRUCTOR-CHOSEN** | Leap-year first half |
| 2016 July--December | 4,416 hours | **INSTRUCTOR-CHOSEN** | Leap-year second half |
| 2017/2018 January--June | 4,344 hours | **INSTRUCTOR-CHOSEN** | Non-leap-year first half |
| 2017/2018 July--December | 4,416 hours | **INSTRUCTOR-CHOSEN** | Non-leap-year second half |
| Energy price profile | [68.02, 39.16, 19.99, 18.42, 53.14, 46.49] $/MWh | **ONLINE-SOURCE CALIBRATED** | Compact profile repeated hourly |
| Price anchor hour-ending values | 1, 6, 11, 13, 20, 23 | **ONLINE-SOURCE CALIBRATED** | Overnight, midday, and evening observations |
| IT-service value profile | [118, 121, 127, 135, 129, 115] $/MWh | **INSTRUCTOR-CHOSEN** | Opportunity value of computational service |
| Profile repetition | Repeat both six-value vectors through the selected half-year | **INSTRUCTOR-CHOSEN** | Deterministic time variation |

The price anchors use the [ERCOT DAM Settlement Point Prices
display](https://www.ercot.com/content/cdr/html/dam_spp.html). The repeated
vectors are instructional profiles, not complete historical ERCOT prices or
claims about a universal data-center value.

## Economic and scoring parameters

For a valid team, the score is:

    score = IT-service value
          - energy purchase cost
          - generator operating cost
          - generator capital cost
          - connection-site cost
          - storage capital cost
          - storage operating cost

Hourly quantities are multiplied by the one-hour time step.

| Parameter | Current value | Source category | Applied as |
|---|---:|---|---|
| IT-service value | Six-value profile above, $/MWh | **INSTRUCTOR-CHOSEN** | Value of served data-center load |
| Energy purchase price | Six-value profile above, $/MWh | **ONLINE-SOURCE CALIBRATED** | Cost of net grid energy purchased |
| Existing-generator operating cost | Dataset marginal_cost_c1_per_mwh | **ZENODO DATASET** | Cost of dispatching a selected existing generator |
| Student generator capital cost | $85,000/MW | **ONLINE-SOURCE CALIBRATED** | One-time cost per submitted generator MW |
| Connection-site cost | $50,000/site | **INSTRUCTOR-CHOSEN** | One-time instructional site-cost proxy |
| Storage power capital cost | $200,000/MW | **ONLINE-SOURCE CALIBRATED** | One-time cost for storage power capacity |
| Storage energy capital cost | $300,000/MWh | **ONLINE-SOURCE CALIBRATED** | One-time cost for storage energy capacity |
| Storage operating cost | $8/MWh discharged | **ONLINE-SOURCE CALIBRATED** | Variable operating cost |
| Infeasible score | 0 | **INSTRUCTOR-CHOSEN** | Score when no feasible projected/fallback dispatch exists |
| Curtailed energy | Not used | **INSTRUCTOR-CHOSEN** | No curtailment or integer recourse in this release |

The generator-capital coefficient is an instructional rounded value anchored to
EIA construction costs and a capital-recovery calculation. The storage split
is close to published utility-scale four-hour battery benchmarks
(approximately $1,400/kW total). Fixed storage O&M is not charged separately.

The legacy schema field default_generator_cost_per_mwh = 100 remains only for
backwards-compatible parsing. It is not the production operating cost for a
valid selected generator; valid generator IDs inherit costs from the Zenodo
catalog.

## Student assets and ownership rules

| Rule | Current value | Source category | Operational meaning |
|---|---|---|---|
| Student bus IDs | Must exist in the Zenodo bus catalog | **ZENODO DATASET** | A CSV cannot invent a bus |
| Student generator IDs | Must exist in the Zenodo generator catalog | **ZENODO DATASET** | Location and operating cost come from the catalog |
| Student generator capacity | Submitted in MW; nonnegative and attached to a submitted site | **INSTRUCTOR-CHOSEN** | Evaluator adds a team-owned candidate unit |
| Student storage power | Positive MW when specified | **INSTRUCTOR-CHOSEN** | Maximum charge/discharge power |
| Student storage energy | Positive MWh when specified | **INSTRUCTOR-CHOSEN** | Energy capacity |
| Generator ownership | Private to the submitting team | **INSTRUCTOR-CHOSEN** | Cannot serve another team |
| Storage ownership | Private to the submitting team | **INSTRUCTOR-CHOSEN** | Cannot serve another team |
| Team load | Fixed and inelastic | **INSTRUCTOR-CHOSEN** | No load shedding or load curtailment |
| Candidate generation | Capped by team local net load at its bus | **INSTRUCTOR-CHOSEN** | Prevents team-owned export to another team |
| Multiple sites/assets | Allowed | **INSTRUCTOR-CHOSEN** | Multiple sites, generators, and storage assets are supported |

The exact CSV schema and pre-submission checker are documented in the student
manual and in scripts/check_submission.py.

## Storage operating constraints

Storage is ideal: charging and discharging have 100% efficiency. Students
submit capacities; the evaluator constructs a deterministic continuous
peak-shaving schedule.

For asset j, with power P, energy B, state e, charging c, and discharging d:

    0 <= c[t] <= P
    0 <= d[t] <= P
    e[t+1] = e[t] + (c[t] - d[t]) * 1 hour
    0 <= e[t] <= B
    e[0] = 0.5 * B
    e[T] >= 0.5 * B
    d[t] <= e[t] / 1 hour

The schedule does not intentionally charge and discharge the same asset in the
same hour. Discharge reduces only its owner's net load and cannot export to
another team. Storage operating cost is charged on discharged MWh.

## Feasibility, projection, and batch evaluation

| Setting | Current value | Source category | Meaning |
|---|---:|---|---|
| Dispatch feasibility | Fixed-load DCOPF satisfies generator, balance, and branch limits | **INSTRUCTOR-CHOSEN** | No load shedding or curtailment variables |
| Joint infeasibility response | Fair continuous projection | **INSTRUCTOR-CHOSEN** | Valid teams share one common service fraction |
| Projection fraction | Largest feasible alpha in [0,1] | **INSTRUCTOR-CHOSEN** | Equal proportional service level |
| Projection tolerance | 1e-6 | **INSTRUCTOR-CHOSEN** | Bisection stopping tolerance |
| Minimum positive service fraction | 1e-6 | **INSTRUCTOR-CHOSEN** | Explicit positive-service endpoint |
| Requested projection iterations | Default 10 | **INSTRUCTOR-CHOSEN** | CLI lower bound |
| Effective minimum iterations | 20 | **INSTRUCTOR-CHOSEN** | Required to resolve the 1e-6 tolerance |
| Malformed-file handling | Reject that file; continue valid files | **INSTRUCTOR-CHOSEN** | Isolates independent teams |
| Dispatch-failure fallback | Deterministic leave-one-team-out / individual evaluation where applicable | **INSTRUCTOR-CHOSEN** | Recoverable evaluation path |
| Result ordering | Deterministic | **INSTRUCTOR-CHOSEN** | Repeated inputs give stable output ordering |

Projection is instructor-side policy, not a student-controlled parameter. A
projected score uses projected load while retaining submitted asset costs, and
the batch output identifies the projection scope.

## Instructor-only execution settings

| Setting | Current value | Source category | Notes |
|---|---:|---|---|
| Batch worker count | CLI default 1; larger values such as 8 allowed | **INSTRUCTOR-CHOSEN** | Runtime only; should not change scores |
| Solver | HiGHS through the DCOPF adapter | **INSTRUCTOR-CHOSEN** | Record solver/version for reproducibility |
| Active source generators | status == 1 | **ZENODO DATASET** | Inactive units excluded |
| Active source branches | status == 1 and nonzero reactance | **ZENODO DATASET** | Inactive/invalid branches excluded |
| Renewable hard availability cap | Not imposed currently | **INSTRUCTOR-CHOSEN** | Nameplate p_max is used; profiles remain available for future scenarios |
| CSV identity | One team and one submission per file | **INSTRUCTOR-CHOSEN** | Batch collector is authoritative |
| Storage period continuity | Required for storage-enabled evaluation | **INSTRUCTOR-CHOSEN** | Prevents ambiguous state transitions |

## What students can tune

Students choose plan variables: sites, hourly load, catalog generator
selections and capacities, and storage capacities. They do not choose prices,
IT values, network limits, generator marginal costs, projection tolerance, or
scoring coefficients.

## Review status and limitations

- Both active half-year rule files currently have status
  instructor_review_required.
- Compact price and IT-value vectors are repeated teaching profiles.
- The fully specified Zenodo source artifact is the canonical network source;
  2017/2018 extensions are experimental derived inputs.
- Renewable profiles are present but are not hard hourly generation caps in the
  current no-curtailment evaluator.
- Fixed storage O&M of approximately $40/kW-year is a reference benchmark only;
  the $8/MWh variable proxy is the charged operating cost.

## References

1. [Zenodo U.S. Test System, record 4538590](https://doi.org/10.5281/zenodo.4538590).
2. [ERCOT Day-Ahead Market Settlement Point Prices](https://www.ercot.com/content/cdr/html/dam_spp.html).
3. [EIA generator construction-cost data](https://www.eia.gov/electricity/generatorcosts/).
4. [EIA battery-storage capital-cost assumptions](https://www.eia.gov/analysis/studies/powerplants/capitalcost/pdf/capcost_assumption.pdf).
5. [NREL 2021 utility-scale battery-storage ATB](https://atb.nrel.gov/electricity/2021/utility-scale_battery_storage).
6. [NREL 2024 utility-scale battery-storage ATB](https://atb.nrel.gov/electricity/2024/2023/utility-scale_battery_storage).
7. [LBNL generator interconnection-cost report](https://emp.lbl.gov/publications/generator-interconnection-costs-0).
8. [ERCOT historical load archive](https://www.ercot.com/gridinfo/load/load_hist).

