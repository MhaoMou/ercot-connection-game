# Hyperparameters and configuration

**Audience:** students and instructors using the active ACTIVSg2000 teaching game.

This is the compact provenance table for the active implementation. The Python
evaluator, the selected scenario block, and its scoring-rules JSON are
authoritative for a released run. The values below describe the checked-in
contract; an instructor must announce any separately versioned round override.

Origin categories:

- **DATASET-SPECIFIED** - copied from, or directly determined by, the public
  ACTIVSg2000 source package.
- **DERIVED** - computed by the evaluator from the selected network, joint
  dispatch, or classroom state.
- **SOURCE-CALIBRATED** - informed by the cited engineering, construction, or
  cloud-pricing reference and then mapped into the game.
- **INSTRUCTOR-CHOSEN** - selected for the learning objective, reproducibility,
  computational tractability, or student interface.

These labels describe the game configuration. None of the values is an official
ERCOT tariff, forecast, or operating requirement.

## Active model boundary

The active pipeline is:

```text
ACTIVSg2000 network and catalogs
    -> representative-day package (5 days x 24 hourly periods)
    -> canonical seven-column site CSV
    -> joint DCOPF and grid-operated storage
    -> utilitarian site allocation when required
    -> score and privacy-safe classroom outputs
```

The canonical CSV is one row per site. The evaluator expands each constant site
capacity over the 120 hourly periods of the representative package. Students do
not submit time-series profiles, generator IDs, storage IDs, prices, dispatch schedules, or storage
state of charge.

## Network and horizon parameters

| Parameter | Value | Units | Origin | Rationale / reference |
|---|---:|---|---|---|
| Network | ACTIVSg2000 | synthetic Texas 2,000-bus model | DATASET-SPECIFIED | Public source model; see [ACTIVSg2000](https://github.com/caseformat/ACTIVSg2000). |
| Buses | 2,000 | buses | DATASET-SPECIFIED | Student `bus_id` values must come from the selected block. |
| Branches | 3,206 | branches | DATASET-SPECIFIED | Fixed topology used by the dispatch adapter. |
| Generator records | 544 | records | DATASET-SPECIFIED | Active status, PMIN, PMAX, and marginal-cost fields come from the catalog. |
| Time step | 1 | hour | INSTRUCTOR-CHOSEN | One hourly period of a representative day; 24 periods per day. |
| Representative days | 5 | days | INSTRUCTOR-CHOSEN | 2028-01-03 (weight 83.77), 2028-05-10 (99.73), 2028-07-12 (82.77), 2028-09-10 (97.73), and the peak day 2028-09-15 (weight exactly 1); weights sum to 365. The year label is only the ACTIVSg2000 source year. |
| Horizon | 120 | hourly periods | INSTRUCTOR-CHOSEN | 5 days x 24 hours; the system peak is period 109 (zero-based). |
| Planning horizon | 10 | years | INSTRUCTOR-CHOSEN | The weighted representative days stand for each of the next ten years. |
| Scenario package | `data/processed/activsg2000_representative_v1/` | path | INSTRUCTOR-CHOSEN | Built with instructor tools (not distributed); scoring rules `data/teaching/dispatch_scoring_rules_representative_v1.json`; release config `data/teaching/game_release_representative_v1.json`. |
| Practice demo | `data/teaching/ieee14_demo_representative/` | path | INSTRUCTOR-CHOSEN | IEEE 14-bus practice package with rules `data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json`. |
| Existing-generator availability | Static status, PMIN, PMAX | MW and status | DATASET-SPECIFIED | ACTIVSg2000 has no technology labels or hourly availability fields; no synthetic renewable derating is applied. |
| Dispatch solver | HiGHS through the DCOPF adapter | solver | INSTRUCTOR-CHOSEN | Transparent, repeatable linear dispatch; storage-bearing horizons use the prepared storage-aware path. |

There are no calendar years in the game. The package must have a passed
validation manifest before production use; all 120 representative periods pass
single-period DCOPF validation.

## Classroom schedule and state boundaries

The game has three weekly matches and six submissions, all on the same
representative package:

| Week | Submissions | Energy cost | Treatment |
|---|---|---|---|
| Week 1 | `week-1-submission-1`, `week-1-submission-2` | none | Practice week: feedback only; neither submission counts. |
| Week 2 | `week-2-submission-1`, `week-2-submission-2` | none | Scored; both submissions count. |
| Week 3 | `week-3-submission-1`, `week-3-submission-2` | LMP, both submissions | Scored; both submissions count. |

Within a week, Submission 1 is the first-stage plan. For Submission 2 the base
load is the representative base plus the hourly net grid withdrawal of every
Submission 1 site of every team (site load served minus its private generation
and battery net discharge). Submission 1 sites are fixed base load: they are
not re-evaluated, re-scored, re-projected, or re-dispatched, and keep their
Submission 1 ten-year value. The Submission 2 CSV lists only new sites; a
`site_id` may not repeat one of the same team's Submission 1 `site_id`s, so
capital is charged once, in the submission where a site is built. The
instructor releases Submission 2 data as per-bus load totals only, never
teams' plans. The instructor runs Submission 2 with
`ercot-game-batch run --submission-number 2 --base-load-from <Submission 1 output dir>`
(required on the representative package). Each week resets to the
representative base; the previous week's sites do not carry over.

The final ranking is the sum of four scores: Week 2 Submission 1 + Week 2
Submission 2 + Week 3 Submission 1 + Week 3 Submission 2. Week 1 still produces
feedback artifacts but does not count.

## Canonical student CSV

The active header is exactly:

```text
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
```

Every data row is one site, so a multi-site submission looks like:

```text
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
team-blue,site-north,1001,40,20,10,40
team-blue,site-south,1002,15,0,0,0
```

The checker is [`scripts/check_submission.py`](../scripts/check_submission.py):

```bash
PYTHONPATH=src python scripts/check_submission.py \
  --file team-blue.csv \
  --artifact-dir data/processed/activsg2000_representative_v1
```

Use `--artifact-dir` when the checker should validate `bus_id` against the
released package catalog; the checker always applies the release's G <= C
generator cap and the 1,000 MW team cap. The evaluator remains authoritative.

| CSV field | Units | Origin | Rule |
|---|---|---|---|
| `team_id` | identifier | INSTRUCTOR-CHOSEN | One file contains one team. |
| `site_id` | identifier | INSTRUCTOR-CHOSEN | Unique within the file; defines the site identity used for asset IDs. |
| `bus_id` | catalog identifier | DATASET-SPECIFIED | Must exist in the selected block's `bus.csv`. |
| `connection_capacity_mw` | MW | INSTRUCTOR-CHOSEN | Finite and nonnegative constant site capacity; the file's sites add up to at most 1,000 MW. |
| `generator_capacity_mw` | MW | INSTRUCTOR-CHOSEN | Finite, nonnegative, and no greater than `connection_capacity_mw`. |
| `storage_power_mw` | MW | INSTRUCTOR-CHOSEN | Charge/discharge power capacity; zero only with zero energy capacity. |
| `storage_energy_mwh` | MWh | INSTRUCTOR-CHOSEN | Must equal `4 * storage_power_mw` when storage is present. |

The evaluator assigns deterministic private generator and storage asset IDs from
the team/site identity. Those IDs are not student inputs and are not public
generator-catalog IDs. Historical/legacy fixtures may contain the retired
hourly schema and submitted asset labels, but they are compatibility inputs
only and must not be copied into an active submission.

## Active economic parameters

| Parameter | Value | Units | Origin | Rationale / reference |
|---|---:|---|---|---|
| IT-service value | 1,000 | USD/MWh served load | INSTRUCTOR-CHOSEN | Round instructional net margin of served computational load, between colocation rent (about $270/MWh of IT load) and GPU-cloud revenue (about $1,700/MWh). |
| Discount rate | 7 | percent per year | INSTRUCTOR-CHOSEN | Ten-year annuity factor A = sum over y = 1..10 of 1.07^-y = 7.0236 (`present_value_annuity_factor`). |
| Period weight | `period_weight_hours[t]` = 1 h x day weight x A | hours | DERIVED | Sums to 61,526.57 h over the 120 periods, so a fully served MW earns about $61.5M of IT value. Applies to IT value, energy purchases, and generator operating cost. |
| Energy purchase cost, Weeks 1-2 | 0 | USD | INSTRUCTOR-CHOSEN | No grid-energy charge in either submission (`--week 1|2` or `--energy-cost off`). |
| Energy purchase cost, Week 3 | Joint-dispatch LMP times grid purchase (MW) times `period_weight_hours` | USD | DERIVED | Both Week 3 submissions (`--week 3` or `--energy-cost on`). The LMP is selected from the joint dispatch at the team's bus; it is not a student-chosen independent price. |
| Team-generator marginal curve | 25% at 80, 50% at 150, 25% at 250 | USD/MWh and capacity share | SOURCE-CALIBRATED, INSTRUCTOR-CHOSEN | Convex curve for generic colocated natural-gas reciprocating/simple-cycle generation with diesel-standby/scarcity premium; exact curve remains instructional. See [EIA 2026 LCOE page](https://www.eia.gov/outlooks/aeo/electricity_generation/), [EIA AEO2025 technology-cost report](https://www.eia.gov/analysis/studies/powerplants/capitalcost/pdf/capital_cost_AEO2025.pdf), and [California Energy Commission data-center overview](https://www.energy.ca.gov/programs-and-topics/topics/data-centers). |
| Team-generator capital | 2,000,000 | USD/MW | SOURCE-CALIBRATED, INSTRUCTOR-CHOSEN | Installed on-site gas engines and aeroderivative turbines cost about $1,700–2,000/kW ([Rabobank 2026](https://www.rabobank.com/knowledge/d011524694-the-sprint-data-centers-are-building-a-parallel-energy-system-in-the-us)); EIA-based figures in a Texas PUC filing give about $1,430/kW (aeroderivative) and $2,240/kW (internal-combustion engines). Charged once, undiscounted, in the submission where the site is built. |
| Connection-site cost | 25,000,000 | USD/MW | SOURCE-CALIBRATED, INSTRUCTOR-CHOSEN | AI-data-center facility-capital proxy, not a universal interconnection tariff. JLL reports $10.7M/MW shell/core and up to $25M/MW AI fit-out; Morgan Stanley reports approximately $21–31M/MW including GPUs/servers. See [JLL outlook](https://www.jll.com/en-us/insights/market-outlook/global-data-centers) and [Morgan Stanley data-center research](https://www.morganstanley.com/content/dam/msdotcom/en/assets/pdfs/Research_Bridging-Data-Center-Gap.pdf). |
| Storage power capital | 400,000 | USD/MW | SOURCE-CALIBRATED, INSTRUCTOR-CHOSEN | Rounded component of the 2028 moderate four-hour storage projection; charged once, undiscounted. See [NREL 2023 storage projections](https://www.nrel.gov/docs/fy23osti/85332.pdf) and [NREL 2024 utility-scale storage ATB](https://atb.nrel.gov/electricity/2024/2023/utility-scale_battery_storage). |
| Storage energy capital | 250,000 | USD/MWh | SOURCE-CALIBRATED, INSTRUCTOR-CHOSEN | Rounded component of the same 2028 moderate four-hour projection. |
| Four-hour storage equivalent | 1,400,000 | USD/MW | DERIVED | `400,000 * P + 250,000 * (4P)` for power `P`; storage operating cost is zero. |
| Storage operating cost | 0 | USD/MWh | INSTRUCTOR-CHOSEN | The grid operator schedules storage without a variable storage-cost term. |
| Generator cap | 1.0 | fraction of connection capacity | INSTRUCTOR-CHOSEN | `max_generator_to_connection_ratio`; G <= C, so a site may carry its whole load on its own generator and run off the grid. There is no run-hour limit: a team generator may run in every hour (a rules file that sets `generator_daily_energy_hours` is rejected). Co-located private generators of different teams share the bus's private generation in proportion to their capacity (a deterministic tie-break applied after the solve, capped by each generator's capacity and its team's own load; bus totals, LMPs and the objective are unchanged). |
| Team connection cap | 1,000 | MW of total connection capacity per team per submission | INSTRUCTOR-CHOSEN | `max_team_connection_capacity_mw`; keeps scores bounded (an off-grid MW is always served) and comparable with the reference plan. A file above the cap is rejected. |
| Off-grid net value | about 24.8 | million USD per MW | DERIVED | 61.53M IT value - 25M site - 2M generator capital - 9.69M fuel (full output every hour at an average 157.5 USD/MWh on the curve, times 61,526.57 weighted hours). A MW served from the grid nets about 36.5M before energy cost. |
| Reference plan B | 49.67 | billion USD | DERIVED | Final score (sum of the four graded submissions) of one team alone running 1,000 MW off the grid (G = C): W2S1 24.84B + W2S2 0 + W3S1 24.84B + W3S2 0. Computed analytically from the rules; see `data/teaching/reference_plan/`. |
| Break-even served share | about 41% | fraction of connection capacity | DERIVED | `25e6 / (1000 x 8760 x A)` = 0.406: average served share at which IT value recovers the site cost, without energy cost. |
| Invalid/infeasible fallback score | 0 | USD | INSTRUCTOR-CHOSEN | Deterministic grading value when no usable projected/fallback dispatch exists. |

The score is:

```text
IT-service value
- energy purchase cost (Week 3 only)
- team-generator operating cost
- generator capital cost
- connection-site cost
- storage capital cost
```

IT-service value, energy purchase cost, and team-generator operating cost are
energy terms: each sums a per-period MW quantity times its USD/MWh rate times
`period_weight_hours[t]`, giving a ten-year present value. Capital terms are
charged once per newly built asset, on its allocated capacity (alpha C, alpha
G, alpha P, alpha B; alpha = 1 unless the allocation below is needed), and are
not discounted.

Existing public generators retain their dataset marginal costs. Team-owned
generators and storage are separate private assets and cannot serve another
team.

## Storage and dispatch rules

Students submit storage capacities only. The grid operator, not the student,
chooses charging and discharging in the centralized dispatch. For each asset:

```text
dt = 1 hour (one game period)
-storage_power_mw <= p[t] <= storage_power_mw     (p > 0 discharges, p < 0 charges)
SOC[t] = SOC[t-1] - dt * p[t]
0 <= SOC[t] <= storage_energy_mwh
dt * p[t] <= SOC[t-1]                               (discharge cannot exceed stored energy)
SOC at the start of every day = 0.5 * storage_energy_mwh
SOC at the end of every day   = 0.5 * storage_energy_mwh   (exact)
```

The storage boundary mode is `daily_exact_cycle`: a day is 24 consecutive
hourly periods, every representative day starts half full and must end exactly half full,
and no stored energy carries between days or between submissions. The
transition uses 100% efficiency. The prepared HiGHS model represents each
storage asset with this one signed net-power variable per period, so the
dispatch is a linear program with no binary operating-mode variable. With ideal
efficiency and no storage operating cost, simultaneous charge and discharge has
no value, so this is equivalent to a two-variable charge/discharge form. Discharge can reduce only the owning team's load. It cannot be
exported to another team. A separate continuous peak-shaving path exists only
for explicitly marked no-artifact compatibility tests; it is not the active
classroom dispatch.

## Site allocation and execution parameters

Allocation is evaluator policy, not a student control. When the joint request
is infeasible, every site s (of any team) gets a fraction alpha_s in [0, 1]
that scales its connection, generator and storage capacities together. Stage 1
maximizes the total served capacity sum_s alpha_s C_s subject to the joint
DCOPF in all 120 periods (storage cycling daily, each team's generator and
storage serving only its own load). Stage 2 breaks ties by minimizing
sum_s C_s (1 - alpha_s)^2 at the stage-1 total; the objective is strictly
convex, so the allocation is unique. There is no minimum allocation, and
capital is charged on the allocated capacities. The fractions are computed by
cutting planes: a small master over alpha (LP in stage 1, QP in stage 2) and
one load-shedding LP per representative day whose reduced costs give a cut;
the final fractions are dispatched with one exact LP per day.

| Parameter | Value | Units | Origin | Rationale / reference |
|---|---:|---|---|---|
| Allocation rule | maximize total served capacity, one fraction per site | policy | INSTRUCTOR-CHOSEN | Utilitarian: favors sites that need the least network per MW served (generators, batteries, buses with small shift factors on the bottleneck). ERCOT publishes no formula for splitting capacity among studied loads ([ERCOT batch process](https://www.ercot.com/files/docs/2026/06/18/Trending-Topics-ERCOT-s-New-Batch-Connection-Process-for-Large-Electricity-Users-v2.pdf)). |
| Tie-break | minimize sum C (1 - alpha)^2 at the stage-1 total | policy | INSTRUCTOR-CHOSEN | Unique allocation, independent of the solver; identical sites at one bus get the same fraction. |
| Minimum allocation | none | fraction of request | INSTRUCTOR-CHOSEN | A small fraction is still served and pays only for itself. |
| Shed tolerance | 1e-4 | MWh per day | INSTRUCTOR-CHOSEN | A day fits when its load-shedding LP sheds at most this much. |
| Allocation margin | 1e-4 | fraction of alpha | INSTRUCTOR-CHOSEN | Every cut site (alpha < 1) is scaled by 1 - 1e-4 so the dispatch, and a Submission 2 base load built from it, stays strictly inside the binding limits; a site within 1e-5 of full service is served in full. If the final dispatch still fails, all fractions are scaled by 1 - 1e-3, then 1 - 1e-2. |
| Projection objective label | `utilitarian_max_served_capacity` | objective | INSTRUCTOR-CHOSEN | Recorded in the audit with `site_fraction_by_team` and `cap_policy` (`max_total_capacity_mw`, `total_capacity_mw`, `requested_capacity_mw`, `iterations`, `cuts`). |
| CLI `--projection-iterations` | accepted, unused | iterations | INSTRUCTOR-CHOSEN | Kept for command compatibility; the cutting-plane method stops when no day sheds load. |
| Malformed submission | Reject file; continue valid teams | policy | INSTRUCTOR-CHOSEN | Failure isolation prevents one file from erasing other teams' results. |

The result records each site's fraction, each team's service fraction
(allocated over requested capacity) and projected load, and the projection
scope. It does not use first-come-first-serve ordering. If no allocation exists
(the base network itself cannot be dispatched), deterministic leave-one-team-out
and individual fallback attempts are recorded where possible.

## Persistent assets and privacy-safe outputs

The round coordinator carries the Submission 1 sites' hourly net grid
withdrawal into the Submission 2 base load within a week (Submission 2 is
charged only for its new sites) and resets to the representative base at each
new week. The state file is written only after a usable dispatch and valid
final SOC have been obtained.

The raw instructor output contains the full audit record, submitted plans,
dispatch details, and diagnostics. The classroom writer separately produces a
shared `classroom-safe-v1` summary with aggregate counts, aggregate periods,
and aggregate projection metadata. Each team receives an isolated hashed-
directory `classroom-private-v1` summary for its own score and diagnostics.
Do not publish raw CSVs, exact competitor sites, asset capacities, or full
cross-team dispatch JSON.

## Validation and benchmark limitations

- The representative package (`activsg2000_representative_v1`) records
  `validation_status: passed` for all 120 periods. The hourly source package
  (`activsg2000_scenarios_v1`) is only the instructor builder's local input; it is not
  distributed and not used by the game.
- The student preview (`ercot-game-preview`, default `--preview-stride 1` on
  the representative release) leaves storage idle. A plan above the hosting
  capacity of some hour is scaled by the evaluator's site allocation (the JSON
  reports each team's `service_fraction`) instead of failing; a Submission 2
  preview needs `--base-load-from <Submission 1 output dir>` as the evaluator
  does. It can help students iterate, but instructor evaluation uses the full
  package and release config.
- Hosting capacity on the full package (`ercot-game-hosting-capacity`) is
  2,000 buses x 120 periods = 240,000 LPs, about 19 minutes with Gurobi
  (32 workers) on a server.

## References

1. [ACTIVSg2000 source model](https://github.com/caseformat/ACTIVSg2000).
2. [EIA generator construction costs](https://www.eia.gov/electricity/generatorcosts/).
3. [EIA natural-gas heat-rate comparison](https://www.eia.gov/todayinenergy/detail.php?id=52158).
4. [EIA battery-storage cost assumptions](https://www.eia.gov/analysis/studies/powerplants/capitalcost/pdf/capcost_assumption.pdf).
5. [NREL 2021 utility-scale battery-storage ATB](https://atb.nrel.gov/electricity/2021/utility-scale_battery_storage).
6. [NREL 2024 utility-scale battery-storage ATB](https://atb.nrel.gov/electricity/2024/2023/utility-scale_battery_storage).
7. [JLL 2026 Global Data Center Outlook](https://www.jll.com/content/dam/jllcom/en/global/documents/reports/research-reports/26-research-global-data-center-outlook.pdf).
8. [AWS EC2 pricing](https://aws.amazon.com/ec2/pricing/), [Azure VM pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/), and [Google Cloud Compute pricing](https://cloud.google.com/products/compute/pricing).
9. [Fairness algorithm for emergency demand response](https://doi.org/10.1016/j.ijepes.2021.107871).
