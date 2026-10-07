# ERCOT Connection-Planning Game: Concrete Plan

**Status:** Working specification distilled from the advisor whiteboard discussion.

## 1. Game definition

Students form `M` groups representing data-center operators. Each group submits
a plan for where and how much load to connect to a Texas teaching slice of a
synthetic U.S. grid model. A group may also locate generation. Python validates
each CSV, checks interconnection feasibility, computes score and diagnostics,
and ranks groups.

The application must keep three layers distinct:

1. **Public static data:** buses/locations, transmission geometry or planning
   interfaces, adjacency, existing generators, and existing loads.
2. **Teaching model:** candidate sites, capacities, operating assumptions,
   interconnection rules, and scenario values.
3. **Student strategy:** the submitted CSV.

The teaching model is not ERCOT's official operational network model.

## Dataset basis: Zenodo 4538590

The dispatch backbone will be the [U.S. Test System with High Spatial and
Temporal Resolution for Renewable Integration Studies](https://zenodo.org/records/4538590),
described by [Xu et al. (2020)](https://bescdn.breakthroughenergy.org/publications/US_Test_System_with_High_Spatial_and_Temporal_Resolution.pdf).
It is a synthetic, public-data-informed U.S. grid model, not an official ERCOT
model. Public descriptions report approximately 82,000 buses, 104,000+
branches, and 13,000+ generators, with Eastern, Western, and Texas
interconnections and voltage levels from distribution through 765 kV. It also
provides time-varying load and renewable-resource profiles for production-cost
and dispatch studies.

Zenodo record version `0.4.2` contains one `USATestSystem.zip` archive of
968,865,144 bytes with MD5 checksum
`7008d13ac52bc4fa56dfa2eb005f04a8`; the record is licensed CC BY 4.0. The
archive should not be loaded into the browser or copied into student
submissions. Keep it in the instructor/deployment pipeline and generate a
versioned 2,000-bus Texas dispatch artifact plus a smaller student-visible
candidate-site layer.

The prepared source topology should retain `bus.csv`, `branch.csv`, `sub.csv`,
`bus2sub.csv`, `dcline.csv`, and `zone.csv`, together with checksums and the
filtering script/configuration used to create the teaching slice. Before
implementation, inspect the archive directly and record the exact internal
paths; the file inventory above is the expected preparation target, not a
substitute for verifying the archive.

The archive inspection is recorded in
`data/intermediate/source_manifest_zenodo_4538590.json`. The exact base-grid
inventory is 82,071 buses, 104,192 branches, 41,083 substations, 82,071
bus-to-substation mappings, and 14,050 plant records. Filtering
`interconnect == Texas` yields exactly 2,000 buses, 3,206 branches, 1,250
substations, 598 plant records, and 1,125 buses with positive base load. This
confirms that the selected archive contains the intended approximately
2,000-bus Texas candidate and avoids prematurely substituting the separate
ACTIVSg2000 dataset.

Design consequence: students submit connection and investment decisions; the
Python evaluator computes generator dispatch and network flows for each period.
Load is fixed after submission: the evaluator does not curtail or shed student
load.

### Texas-subset provenance gate

The intended game model is the exactly 2,000-bus Texas interconnect contained
in Zenodo 4538590. This is a Texas slice of a larger synthetic U.S. archive;
it is not ERCOT's official electrical network and is not the separate
ACTIVSg2000 artifact. The filtering rule and exact counts are frozen in the
source manifest. The next gate is therefore boundary and unit validation,
not choosing between the two sources.

### Extraction result and dispatch-data follow-up

The first extraction run is complete at
`data/processed/texas_dispatch_source_v1/`. The core Texas tables pass
referential-integrity validation with 2,000 buses, 3,206 branches, 1,250
substations, 598 plant records, 598 matching generator-cost records, 8 zones,
and 2 Texas-linked cross-interconnect DC lines. The DC lines are retained as
explicit boundary assets rather than being silently folded into the AC branch
table.

The archive contains 8,784 hourly rows in each inspected profile table. The
76 columns in `demand.csv` are zonal profiles; the eight Texas zone IDs are
`301`–`308`. The source metadata states that zone demand is disaggregated to
buses proportional to each bus's base `Pd`, so the dispatch preparation will
apply those shares to the eight retained Texas demand profiles. The renewable
profiles are plant-ID keyed; the extracted artifact retains 22 Texas hydro, 36
Texas solar, and 117 Texas wind plant profiles. Profile semantics are now
resolved, and the bus-level demand expansion and unit/dispatch-limit checks
are complete. `demand_bus.csv` contains 8,784 hourly rows across all 2,000
Texas buses and conserves each zonal total within numerical tolerance.
`generator_limits.csv` and `branch_limits.csv` provide explicit normalized
units for the next dispatch implementation. The 202 MB bus-demand file is an
instructor/deployment artifact and should not be bundled into the browser or
student submissions.

The dispatch formulation is now fixed for the first implementation: a
single-period linear DC optimal power flow (DCOPF) solved with HiGHS through
the Python `highspy` package. The source MATPOWER base is `100 MVA`, so
per-unit branch susceptance is converted to MW/radian before enforcing branch
limits. The two Texas receiving-end DC ties are represented as fixed boundary
injections using the source `Pt` values: `190 MW` and `550 MW` at their Texas
endpoint buses. This is an explicit boundary convention for the teaching
dispatch, not a claim that the reduced model reproduces the full
interconnection scheduling process.

The 8,784-hour source sequence remains available to the evaluator. A
multi-period run should call the single-period DCOPF once per period, applying
renewable availability and any submitted data-center load/storage decisions at
that period. The course may later configure a shorter pilot horizon without
changing the solver formulation.

## 2. Proposed schedule

The photos appear to describe a four-week pilot:

| Stage | Activity | Output |
|---|---|---|
| Week 1 | Release data/rules and student preparation | Package, rules, examples, validator |
| Weeks 2–4 | Weekly submissions and evaluation | One CSV per group/deadline |
| End | Final ranking and discussion | Scores, diagnostics, instructor summary |

This is a proposed pilot schedule, not a requirement that the course lasts
exactly four weeks. The game can run for at least one month and `T`, the number
of periods/submissions, should be configurable. The references to six
submissions and 2028 in the photos are not legible enough to make requirements.

## 3. Versioned static package

```text
data/teaching_game/v1/
├── manifest.json
├── source_manifest.json
├── network/
│   ├── bus.csv
│   ├── branch.csv
│   ├── sub.csv
│   ├── bus2sub.csv
│   ├── dcline.csv
│   └── zone.csv
├── candidate_sites.csv
├── planning_region_source_bus_map_v1.json
├── planning_interfaces.csv
├── dispatch_profiles/
│   ├── load.csv
│   └── generation_availability.csv
├── existing_generators.csv
├── existing_loads.csv
└── rules.json
```

`source_manifest.json` records the Zenodo DOI/version, archive checksum, source
files, and the source-to-slice transformation. `candidate_sites.csv` maps
student-visible site IDs to source bus/substation IDs. `planning_interfaces.csv`
stores the reduced teaching constraints. `dispatch_profiles/` stores the
selected time window and normalized units. `rules.json` contains schema,
scenario, dispatch, interconnection, and scoring parameters.

## 4. Strategy notation

For group `m`, candidate site `i`, generator `k`, storage device `r`, and period
`t`, formalize the whiteboard notation as:

```text
z[m,i] ∈ {0, 1}       site-placement decision
L[m,i,t] ≥ 0          connected data-center load
G[m,k,t] ≥ 0          proposed-generation output/operating level
B[m,r,t] ≥ 0          storage operating quantity
```

The recommended interpretation is that generator capacity is a design variable
with period dispatch bounded by it. Storage is deferred from the first CSV/DCOPF
release rather than silently approximated.

## 5. Student CSV contract

Use one long-form UTF-8 CSV per submission:

```text
team_<team_id>_submission_<submission_id>.csv
```

Required header:

```csv
team_id,submission_id,period,site_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh
```

Each row represents one `(team_id, submission_id, period, site_id)` record.
Empty fields represent absent generation/storage; students must not use magic
strings such as `NONE`.

Example:

```csv
team_id,submission_id,period,site_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh
team_03,week_01,1,SITE_WEST_01,40,G03,20,B03,10,40
team_03,week_01,2,SITE_WEST_01,42,G03,20,B03,10,40
team_03,week_01,1,SITE_COAST_02,25,,,,,
```

Validation rules:

- required identifiers are present on every row;
- period is an integer in `{1, ..., T}` and site ID is released;
- numeric values are finite decimals using `.`;
- load/capacity/power/energy are nonnegative unless the published rules
  explicitly allow signed values;
- generator dispatch is not submitted; the evaluator computes it from the
  source generator fleet, proposed capacity, availability, costs, and network;
- storage charge, discharge, and state of charge are not submitted in the first
  schema; the evaluator computes them subject to submitted capacities;
- duplicate keys `(team, submission, period, site, generator, storage)` reject;
- empty submissions reject with a human-readable error;
- results retain file hash, schema version, rules version, and scenario version.

Freeze the final columns after generator/storage semantics are confirmed.

For the Zenodo-backed DCOPF adapter, the released `site_id` values are the 12
instructional planning-region IDs. The versioned
`data/teaching/planning_region_source_bus_map_v1.json` maps each region to one
source Texas bus by nearest-substation anchor matching, with the highest-base-
load bus selected at that substation. This is an explicit teaching abstraction;
it does not claim that a planning region is electrically identical to one bus.
The current CSV reader converts each region's `load_mw` series into the
canonical `capacity_mw` plus normalized profile representation and uses a
published default candidate-generator marginal cost until generator bidding
rules are finalized. Storage columns are reserved and must be empty in schema
version 1.

## 6. Dispatch, feasibility, and scoring

For each period, add submitted data-center load to the selected source load
profile and solve a documented dispatch problem over the teaching network. The
recommended first solver is a linear DC optimal power flow/economic dispatch
model with generator availability and branch/interface limits. The reduced
teaching model may use planning-interface limits rather than exposing all
source branches to students.

The first formulation benchmark is implemented in
    `tools/zenodo_texas/dispatch.py`. It uses a dependency-free linear DC model
with bus power balance, generator bounds, branch thermal limits, and linear
marginal generation costs. The benchmark solver uses
active-constraint enumeration only for tiny networks; it is a formulation
validation tool, not the production solver for the 2,000-bus system. The
reference case dispatches 40 MW from a cheap remote generator and 40 MW from a
local generator when the remote branch is limited to 40 MW, with no unserved
load. The production path is `tools/zenodo_texas/dcopf.py`, a HiGHS-backed
linear DCOPF that solves one period at a time and returns generation, bus
angles, branch flows, and balance duals. The full
evaluator should call this path once per period. The first plan-to-dispatch
bridge is `tools/zenodo_texas/plan_adapter.py`: it maps a canonical plan's
source-bus connections to `capacity × profile` load and maps submitted
generators to local candidate generators. The existing browser evaluator is
kept as a compatibility path until its planning-region/interface model is
explicitly mapped to source-bus IDs.

For instructor-side competition evaluation, use
`evaluate_plans_with_prepared_dcopf` from that adapter. It evaluates all team
plans jointly in each period and keeps both base demand and submitted demand
fixed. A shared-network overload makes the joint DCOPF infeasible; the scoring
runner then marks every team in that batch infeasible and assigns the published
fixed infeasible score. This avoids partial-service or submission-order rules.

The instructor-side scoring runner is `tools/zenodo_texas/batch_runner.py`.
It consumes the collected CSV files, applies the explicit rules in
`data/teaching/dispatch_scoring_rules_v1.json`, writes `leaderboard.csv`, and
writes `evaluation.json` containing the rules version, input hashes, period
dispatch diagnostics, and team score decompositions. The checked-in rules file
is deliberately marked draft: generator capital cost and site cost are `0` until
the instructor approves calibrated values.

Run checks in order: CSV/schema; source-bus/candidate-site mapping; proposed
asset limits; dispatch feasibility; aggregate load and shared-interface limits;
then scoring. Return structured diagnostics with human-readable names.

Both feasible and infeasible submissions must produce deterministic result
records. Infeasible batches do not disappear from rankings: each team receives
the published fixed infeasible score and a human-readable solver failure reason.

The photos indicate a value term and deductions for generation, storage, and
load/operation-related costs. Implement a configurable score:

```text
score_m = value_of_submitted_load_m
          − generation_capital_and_operating_cost_m
          − site_or_interconnection_cost_m
```

Expose coefficients such as `α`, `β_G`, and `β_B` in `rules.json`; do not
hard-code unreadable whiteboard values. Publish units, signs, coefficients,
the infeasibility treatment, tie-break rule, and one worked example.

Report submitted/served load, generation cost, site/interconnection cost, total
score, feasibility, rank, failure reason when infeasible, and binding resources.

Also save server-side dispatch artifacts containing generator dispatch, branch /
interface flows, submitted load, cost, and solver status. These are evaluator
outputs, not student CSV fields.

### Scoring-parameter calibration

The ranges below are starting points for instructor calibration, not claims that
the game reproduces a commercial data-center contract.

| Parameter | Recommended first-pass range | Calibration basis |
|---|---:|---|
| Wholesale energy price | `$20–80/MWh` in ordinary periods; `$100–300/MWh` for explicitly labeled stress periods | ERCOT reports a 2024 average real-time Hub price of `$27.37/MWh` and `$52.48/MWh` for 2023 in its [2024 ORDC report](https://www.ercot.com/files/docs/2025/03/27/ORDC%20Report%202024.pdf). Keep this separate from retail rates. |
| Retail-price reference | `$86–134/MWh` | EIA's [2025 electricity-price release](https://www.eia.gov/todayinenergy/detail.php?id=65224) reports 8.62¢/kWh for U.S. industrial customers and 13.41¢/kWh for commercial customers. These are context checks, not the dispatch settlement price. |
| IT value of served load | `$100–250/MWh` | This is an instructional opportunity-value parameter. Choose it to make siting and generation tradeoffs visible; it is not directly observed in the wholesale market. |
| Candidate-generator variable cost | `$50–150/MWh` until technology is specified | Prefer the source fleet's marginal-cost column when modeling an existing unit. For new candidate generators, publish a technology-specific value rather than implying one universal cost. |
| Generator capital cost | Technology-specific `$ / MW` from NREL ATB, then scaled consistently for the classroom horizon | Use the [NREL Annual Technology Baseline data](https://atb.nrel.gov/electricity/2024/data) for CAPEX and O&M inputs. Convert `$ / kW` to `$ / MW` by multiplying by 1,000. |
| Site/interconnection cost | Start with `$0–200,000` per site-equivalent, then run a sensitivity check | There is no universal site fee. Treat this as an explicit teaching coefficient and check that it is large enough to discourage gratuitous sites but small enough not to dominate energy value. |
| Infeasible score | `0` recommended; optionally test a fixed negative value | No partial-service score is computed. A joint DCOPF failure marks the batch infeasible and records the solver reason. |

Do not mix wholesale energy prices with commercial retail prices in one score
without documenting the interpretation. The [ERCOT market overview](https://www.ercot.com/about) describes SCED as economic dispatch subject to system constraints, which is the role represented by the DCOPF price/cost layer here. The [DOE/LBNL data-center energy report](https://eta-publications.lbl.gov/sites/default/files/2024-12/lbnl-1005775.pdf)
is useful for understanding data-center energy scale, but it does not provide a
portable current dollar value for the student's IT service; use it as context,
not as a direct scoring coefficient.

Before student release, run a small sensitivity table over IT value, energy
price multiplier, generator variable cost, capital cost, and site cost. Approve
the final vector only if the ranking changes for meaningful strategic choices
and no single coefficient dominates every feasible plan.

## 7. Python implementation

```text
src/ercot_game/
├── submission_schema.py   # columns, parsing, type/range validation
├── submission_io.py       # canonical CSV I/O and file hashes
├── zenodo_loader.py       # source archive and checksum-aware ingestion
├── teaching_data.py       # Texas slice, profiles, and rules loading
├── dispatch.py             # dependency-free small dispatch benchmark
├── dcopf.py                # HiGHS-backed production single-period DCOPF
├── feasibility.py         # site, asset, dispatch, network checks
├── scoring.py             # configurable value/cost/penalty calculation
├── game_runner.py         # one-plan and weekly-batch evaluation
└── cli.py                 # validate/evaluate/rank commands
```

```bash
python -m ercot_game.cli validate submission.csv --data data/teaching_game/v1
python -m ercot_game.cli evaluate submission.csv --data data/teaching_game/v1 --out result.json
python -m ercot_game.cli rank submissions/*.csv --data data/teaching_game/v1 --out ranking.csv
```

Tests must cover valid parsing; missing columns, malformed numbers, unknown
sites, duplicate keys, negative values, and invalid periods; generator/storage
constraints; shared-interface overload; feasible and infeasible scoring;
determinism; ranking ties; retained hashes/versions; source-to-slice mapping;
unit conversion; dispatch feasibility; and a small known dispatch benchmark.

## 8. Operational workflow

1. Instructor publishes the versioned package, rules, template, examples, and
   scoring explanation.
2. Students prepare in a spreadsheet or Python notebook and run the validator.
3. The server accepts one CSV per group/deadline and records its hash.
4. The evaluator processes all accepted files with the same data/rules version.
5. Students receive score, feasibility, binding resources, and diagnostics.
6. Instructor releases rankings and discusses strategy tradeoffs.

The browser editor should be built only after the CSV contract is stable; it
should generate the same canonical CSV rather than define a second format.

## 9. Decisions requiring advisor confirmation

1. Is the pilot exactly four weeks or only a four-week minimum?
2. What are `T` and the number of submissions? The photo appears to mention six.
3. Is the scenario year 2028, and what does “online time” mean?
4. Does `G` mean capacity, dispatch, or both?
5. Does `B` mean storage capacity, dispatch, state of charge, or a build flag?
6. Are load/generation/storage values submitted per period or dispatched by the evaluator?
7. What are the exact site, asset, interconnection, and feasibility rules?
8. What are the exact scoring coefficients, units, penalties, and tie-break rule?
9. Does each weekly submission replace the prior plan, or do weekly scores accumulate?

## 10. Implementation order

1. ~~Download and checksum the Zenodo archive; inspect actual file names, units,
   identifiers, and Texas-interconnect coverage. Count buses, branches,
   generators, loads, and substations in the candidate Texas subset.~~ **Done:**
   recorded in `data/intermediate/source_manifest_zenodo_4538590.json`.
2. ~~Resolve whether the candidate is the Zenodo-derived Texas subset or the
   separate ACTIVSg2000 case; record the decision and source DOI in
   `source_manifest.json`.~~ **Done:** the selected source contains exactly
   2,000 Texas buses.
3. ~~Build a reproducible source-to-teaching-slice pipeline and validate it on a
   small sample before processing the full archive.~~ **Partially done:** the
   deterministic core-table extractor and validation report are complete;
   profile identifier resolution remains open.
4. Resolve the nine decisions and freeze `manifest.json`,
   `source_manifest.json`, and `rules.json`.
5. Implement CSV schema, parser, validator, and samples.
6. Implement dispatch on a small benchmark network, then on the verified Texas
   system.
7. Implement deterministic feasibility diagnostics, scoring, and ranking.
8. Add CLI commands and immutable server upload/submission records.
9. Add the browser editor as a convenience layer over CSV.
10. Run an instructor dry run with feasible, infeasible, overloaded-interface,
   generator, storage, and dispatch-failure cases.
11. Release student-facing documentation and template.

## 11. Dataset caveats and provenance

The selected dataset is an appropriate dispatch backbone because it provides
high-resolution synthetic U.S. topology and time-varying profiles, but it is
not real ERCOT telemetry or an official ERCOT topology. Use the verified
~2,000-bus Texas system for relevance while retaining the dataset's
synthetic/public-data provenance in every result and instructor document.
Students should receive only the smaller teaching package and the exact
version/hash used for evaluation.

References: [Zenodo record 4538590](https://zenodo.org/records/4538590),
[ACTIVSg2000 reference record](https://zenodo.org/records/3462803),
[Texas 2000-bus case repository entry](https://egriddata.org/dataset/texas-2000-bus-system-activsg2k),
[Breakthrough Energy model description](https://science-origin.breakthroughenergy.org/model),
and [the documented source-file inventory](https://github.com/swang22/Transmission-Network-Aggregator).
