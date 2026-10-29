# How the Official Evaluation Works

`ercot-game-batch` evaluates canonical site-level student CSV submissions
against one ACTIVSg2000 scenario block. The Python evaluator and the selected
scoring-rules JSON are authoritative. The instructor runs it on all teams'
files after each deadline; this guide describes that workflow step by step so
that you can see exactly how your score is computed and reproduce it on your
own plans. Historical/legacy hourly fixtures are compatibility tests, not
current student inputs.

## Release boundary and limitations

The production data path is the public synthetic Texas ACTIVSg2000 system.
Student files use source `bus_id` values from the selected block. The active
scenario is controlled instructional data, not historical ERCOT telemetry, a
forecast, or an official operating model.

The canonical scenario package is
`data/processed/activsg2000_representative_v1/`: 5 representative days x 24
hourly periods = 120 periods. It was derived from the hourly
`activsg2000_scenarios_v1` source blocks with instructor build tools; neither
the source blocks nor the tools are distributed (see the package's
`manifest.json` and `representative_days.csv`). The scoring rules are
`data/teaching/dispatch_scoring_rules_representative_v1.json` and the release config is
`data/teaching/game_release_representative_v1.json`.

| Day | Date | Weight (days per year) | Periods |
|---:|---|---:|---|
| 0 | 2028-01-03 | 83.77 | 0-23 |
| 1 | 2028-05-10 | 99.73 | 24-47 |
| 2 | 2028-07-12 | 82.77 | 48-71 |
| 3 | 2028-09-10 | 97.73 | 72-95 |
| 4 | 2028-09-15 (peak day) | 1 | 96-119 |

The weights sum to 365; the system peak is period 109. Together the 120
periods stand for the next ten years: there are no calendar years in the game.

## Classroom schedule

There are three weeks with two submissions each, six submissions in all, and
every submission uses the same representative package:

| Week | Energy cost | Ranking treatment |
|---|---|---|
| Week 1 | none | Practice/feedback only; neither submission counts. |
| Week 2 | none | Scored; both Submission 1 and Submission 2 count. |
| Week 3 | grid purchases at the joint-dispatch LMP, both submissions | Scored; both submissions count. |

The final game score is the sum of four scores: Week 2 Submission 1 + Week 2
Submission 2 + Week 3 Submission 1 + Week 3 Submission 2 (an invalid
submission scores 0). Week 1 is excluded.

Every week starts again from the representative base load; nothing carries
from one week to the next. Within a week, Submission 1 sites carry into
Submission 2 as base load: the Submission 2 base load is the representative
base load plus every Submission 1 site's hourly net grid withdrawal (site load
served minus its own private generation and battery net discharge), read from
`site_net_withdrawal.csv` in the Submission 1 output. Submission 1 sites are
not re-evaluated, re-scored, re-projected or re-dispatched in Submission 2 and
keep their Submission 1 value. Submission 2 CSVs list only new sites; a
`site_id` may not repeat one of the same team's Submission 1 site IDs.
Release the Submission 2 base load to students only as per-bus totals, never
as other teams' plans.

## Run a weekly batch

With no `--artifact-dir` and `--rules`, `run` uses the representative package
and rules. Week 2, Submission 1:

```bash
ercot-game-batch run \
  --submissions-dir work/week2/submission1 \
  --week 2 --submission-number 1 \
  --workers 8 \
  --solver-backend auto \
  --output-mode compact \
  --output-dir work/week2/results_submission1
```

Week 2, Submission 2, with the Submission 1 sites as base load:

```bash
ercot-game-batch run \
  --submissions-dir work/week2/submission2 \
  --week 2 --submission-number 2 \
  --base-load-from work/week2/results_submission1 \
  --workers 8 \
  --solver-backend auto \
  --output-mode compact \
  --output-dir work/week2/results_submission2
```

`--base-load-from` writes a derived scenario artifact (default
`<output-dir>/base_load_artifact`, override with `--base-load-artifact-dir`)
whose `demand_bus.csv` is base demand plus the Submission 1 withdrawal, and
re-solves every period to validate it (skip with
`--skip-base-load-validation`). On the representative package, Submission 2
without `--base-load-from` is an error.

To release the Submission 2 data to students before their Submission 2 is
due, build and validate the same artifact on its own, without evaluating
anything:

```bash
ercot-game-batch base-load \
  --base-load-from work/week2/results_submission1 \
  --output-dir work/week2/submission2_release_data
```

(`--artifact-dir` defaults to the representative package; `--workers` runs
the period checks in parallel.) It prints `submission 2 base load validation:
passed 120 periods` and writes the artifact with a `passed` manifest.
Give students only per-bus totals from it.

Validation solves every period with the strict single-period DCOPF. The site
allocation serves teams up to the edge of feasibility, so a carried
withdrawal can overshoot the boundary by solver noise (about 1e-7 MW), and
HiGHS then reports `kInfeasible` or `kUnknown`. Such a period is re-checked
with a phase-one LP: if a demand change of at most 1e-3 MW in total at the
buses that carry Submission 1 withdrawal restores feasibility, that change
(rounded 1e-6 MW further from the boundary) is written into `demand_bus.csv`,
the period is solved again strictly, and every change is recorded under
`validation.tolerance_adjustments` in the artifact's `manifest.json`
(`tolerance_adjusted_period_count`, `tolerance_adjusted_total_mw`; the
command prints the count). Anything larger is a real infeasibility: the
manifest is left `validation_status: failed` with `failed_periods`, and the
command stops with `Submission 2 base-load validation failed: ... periods
[...]`. A manifest is never left `pending`.

`--week 1|2|3` sets the energy charge (Weeks 1-2 off, Week 3 on).
`--energy-cost on|off` sets it directly; one of the two is required, and a
contradicting pair is rejected. `--submission-number` (`1` or `2`, default
`1`) is evaluator-side metadata, not a CSV field.

The production storage route is the exact multi-storage Benders solver when
the plans fit; an allocated dispatch uses one exact monolithic LP per day.
`--solver-backend auto` is the default: it uses Gurobi when `gurobipy` and a
valid license can be started, and otherwise falls back to HiGHS. Use
`--solver-backend highs` or `--solver-backend gurobi` to force a backend.
`--output-mode compact` writes scores, manifests, team diagnostics, aggregate
diagnostics, and hashes without the large per-period dispatch export. Use
`--output-mode full` when the detailed per-period dispatch is needed for debugging
or visualization (the grid map reads its line loading).

`--workers N` parallelizes the evaluation without changing its result: hourly
periods without storage are solved in `N` threads, and the site allocation
solves its five daily load-shedding LPs in up to five worker processes (one
per day, each with its own model, so the fractions do not depend on `N`; the
tie-break makes them unique). The
Benders recourse inside one dispatch stays serial: parallel recourse threads
warm-start the recourse models in a scheduling-dependent order and can move a
result at solver tolerance. Use at most the cores you may occupy.

`--roster <file>` (one `team_id` per line, or a CSV with a `team_id` column)
prints `roster: K of N teams submitted; missing: ...` and writes
`roster_check.json` (`missing_team_ids`, `not_on_roster_team_ids`) to the
output directory.

`ercot-game-batch classroom --manifest <json> --output-dir <dir>` evaluates
all six submissions in order (round keys `week-1-submission-1` ...
`week-3-submission-2`, each with `submissions_dir`, `artifact_dir` and
`rules`), carrying Submission 1 withdrawal into Submission 2 and resetting at
each week; it prints `summary: N submissions evaluated`. `--workers N` is
passed to every round's evaluation. A missing or wrong `artifact_dir` is
reported as such (`artifact_dir does not exist ...`). The run writes the final
leaderboard to `<output-dir>/instructor/final_leaderboard.csv`: per team the
four graded scores `week2_s1`, `week2_s2`, `week3_s1`, `week3_s2` (0 for a
round without a scored file) and their `total`, ranked by total, with
`missing_rounds` listing graded rounds not yet evaluated (a resumed run
includes the rounds of earlier runs, kept in `instructor/round_scores/`).
`--period-indices` is reserved
for explicitly labeled smoke tests or debugging; official evaluation uses all
120 periods.

### Eight-team example

`examples/eight_team_round/submissions` runs on the representative package
without congestion. With every capacity scaled by 6 it congests: in Week 3,
Submission 1, four teams are cut to a common 531 MW.

## Canonical CSV and checker

The active student header is exactly seven columns:

```text
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
team-blue,site-north,1001,40,20,10,40
team-blue,site-south,1002,15,0,0,0
```

Every row is one site. The file has no `period`, hourly `load_mw`,
`submission_id`, `generator_id`, or `storage_id` columns and no
horizon rows. `bus_id` must exist in the selected block's `bus.csv`.
Generator capacity cannot exceed connection capacity (G <= C; a site may run
off the grid), a generator may run in every hour, the sites of one file add up
to at most 1,000 MW of connection capacity, and storage is either zero or has
energy equal to four times power (B = 4P).
Co-located private generators of different teams share the bus's private
generation in proportion to their capacity. The LP fixes only each bus's
total private generation, so after every solve (hourly, Benders daily,
monolithic daily) the evaluator re-splits that total by capacity G, filling
around each generator's caps (capacity and segment structure, and its team's
own load at the bus). Bus totals, flows, LMPs and the objective are unchanged.
A bus whose proportional split cannot be applied keeps the solver split and is
listed under `generator_split_fallbacks` in the evaluation metadata.

Run the student-facing checker:

```bash
ercot-game-check-csv --file path/to/team.csv \
  --artifact-dir data/processed/activsg2000_representative_v1
```

Add `--artifact-dir data/processed/activsg2000_representative_v1` to validate
catalog bus IDs. The checker is a
pre-submission convenience; batch evaluation remains authoritative.

The evaluator assigns deterministic private generator and storage asset IDs from
the team/site identity. Students do not choose public generator IDs or storage
IDs. The retired hourly format and files under explicitly labeled legacy
fixture directories remain only for compatibility and reproducibility tests;
never distribute them as active templates.

## Storage and dispatch contract

Students submit storage capacities. The grid operator schedules charge,
discharge, and SOC in the centralized prepared HiGHS model. Each storage asset
has:

- power limits in MW and energy limits in MWh;
- 100% charge/discharge efficiency and a one-hour SOC transition
  (`SOC[t] = SOC[t-1] - 1 h * p[t]`, with discharge energy limited to the
  stored energy);
- `storage_boundary_mode: daily_exact_cycle`: each representative day (24
  hourly periods) starts at one-half of energy capacity and ends at exactly one-half, with no
  carry-over between days or submissions;
- one signed net-power variable per asset and period (positive discharges,
  negative charges), so the coupled horizon remains a linear program with no
  binary operating-mode variable;
- a discharge restriction to the owning team's load.

Storage cannot be used to serve another team, and storage operating cost is not
charged. A separate continuous peak-shaving path exists only for explicitly
marked no-artifact compatibility tests.

## Economics and provenance

For a valid team, the score is a ten-year present value:

```text
IT-service value
- energy purchase cost (Week 3 only)
- team-generator operating cost
- generator capital cost
- connection-site cost
- storage capital cost
```

Each energy term of period `t` (IT value, energy purchases, generator
operating cost) is weighted by
`period_weight_hours[t] = 1 h x day weight x A`, where
`A = sum_{y=1..10} 1.07^-y = 7.0236` (7% discount rate, ten years). The 120
weights sum to 61,526.57 hours. Capital costs are charged once, undiscounted.

The active coefficients are:

| Parameter | Active value | Units | Origin and reference |
|---|---:|---|---|
| IT-service value | 1,000 | USD/MWh | Instructor-chosen net margin of served computational load, between colocation rent (about $270/MWh) and GPU-cloud revenue (about $1,700/MWh). |
| Discount rate / planning life | 7% / 10 years | - | Instructor choice; annuity factor A = 7.0236. |
| Team-generator curve | 80 / 150 / 250 over 25% / 50% / 25% | USD/MWh | Source-informed convex curve for colocated natural-gas engines/turbines with standby/scarcity premium. |
| Generator capital | 2,000,000 | USD/MW | Installed on-site gas engines/aeroderivative turbines about $1,700–2,000/kW (Rabobank 2026); EIA-based Texas PUC filing figures: aeroderivative about $1,430/kW, internal-combustion engines about $2,240/kW. |
| Generator cap | 1.0 | fraction of connection capacity | `max_generator_to_connection_ratio`: G <= C, no run-hour limit; a site with G = C runs off the grid. A rules file that sets `generator_daily_energy_hours` is rejected. |
| Team connection cap | 1,000 | MW per team per submission | `max_team_connection_capacity_mw`; a file above it is rejected. |
| Reference plan B | 49.67 | billion USD | Final score (sum of W2S1, W2S2, W3S1, W3S2) of one team alone running 1,000 MW off the grid (G = C): 24.84B + 0 + 24.84B + 0; computed analytically (`data/teaching/reference_plan/`). |
| Connection-site cost | 25,000,000 | USD/MW | AI-data-center facility-capital proxy, not a universal grid-interconnection tariff; informed by JLL and Morgan Stanley. |
| Storage power capital | 400,000 | USD/MW | Rounded component of NREL's 2028 moderate four-hour projection. |
| Storage energy capital | 250,000 | USD/MWh | Rounded component of the same NREL projection. |
| Four-hour storage equivalent | 1,400,000 | USD/MW | Derived from `400,000 * P + 250,000 * (4P)`. |
| Capital basis | allocated capacities | - | Site, generator and storage capital are charged on alpha C, alpha G, alpha P, alpha B (alpha = 1 unless the site allocation is needed). |
| Storage operating cost | 0 | USD/MWh | Explicit instructor-chosen zero-cost rule. |
| Invalid/infeasible fallback score | 0 | USD | Deterministic instructor policy. |

The rules file contains a 120-period constant IT-value vector. Week 3
settlement uses the LMP
from the selected joint dispatch, not a student-chosen price vector. Existing
public generators use dataset marginal costs; team-built generators use the
common convex curve above.

## Site allocation and failure isolation

Malformed files are rejected independently so valid teams remain eligible. If
the valid joint request is infeasible, the evaluator allocates the sites:

- every site `s` (of any team) gets a fraction `alpha_s` in [0, 1] that scales
  its connection capacity, generator capacity, storage power and storage
  energy together; different sites of one team can get different fractions;
- stage 1 maximizes the total served capacity `sum_s alpha_s C_s` subject to
  the joint DCOPF in all 120 periods (storage cycling daily from half full,
  each team's generator and storage serving only its own load at the bus);
- stage 2 breaks ties by minimizing `sum_s C_s (1 - alpha_s)^2` at the
  stage-1 total (within a relative 1e-7); the objective is strictly convex, so
  the allocation is unique and solver-independent;
- there is no minimum allocation, and capital is charged on the allocated
  capacities.

The rule favors sites that need the least network per MW served: a site with
G = C needs none and is never cut. The fractions are the same in every period,
so they couple the five days. They are computed by cutting planes: a small
master over the fractions (an LP in stage 1, a QP in stage 2) proposes a
point, and one load-shedding LP per representative day (built once, first
solved by interior point, then re-solved by warm-started simplex) measures the
shed; a day that sheds more than 1e-4 MWh returns a cut from its reduced costs.
The final fractions are dispatched with one exact LP per day. Every cut site
(alpha < 1) is first scaled by 1 - 1e-4, so the dispatch and the Submission 2
base load built from it stay strictly inside the binding limits (a site within
1e-5 of full service is served in full); if the dispatch still fails, every
fraction is scaled by 1 - 1e-3, then 1 - 1e-2. The
audit records `site_fraction_by_team`, per-team service fractions (allocated
over requested capacity), projected load, the objective
(`utilitarian_max_served_capacity`) and `cap_policy` (`max_total_capacity_mw`,
`total_capacity_mw`, `requested_capacity_mw`, `iterations`, `cuts`).
Proportional-fair utility is still reported as a diagnostic. The CLI option
`--projection-iterations` is accepted for compatibility and unused.

HiGHS presolve occasionally stops with `kUnknown` on near-degenerate LPs at the
feasibility boundary (the Benders master in particular); such a solve is
repeated from scratch without presolve, then with the primal simplex, before it
is treated as unresolved.

No first-come-first-serve ordering is used. If no allocation exists (the base
network itself cannot be dispatched), the evaluator records deterministic
leave-one-team-out and individual fallback attempts where possible. A valid
team's score is not silently erased by one oversized or malformed submission.

## Privacy-safe outputs

The raw batch output is instructor-private and may contain submitted CSV
hashes, exact plans, full dispatch periods, per-team diagnostics, asset
capacities, and failure details. The classroom writer creates separate outputs:

- shared `classroom-safe-v1` summaries contain aggregate team counts, aggregate
  period/network measures, and aggregate projection metadata;
- a team's `classroom-private-v1` file lives in `teams/team-<h>/`, where `h`
  is an HMAC-SHA256 of the team ID keyed with a random per-class secret, so a
  team ID alone does not locate its folder. The secret
  (`instructor/team_folder_secret.txt`) is created on the first classroom run
  and reused on resume; `instructor/final_leaderboard.csv` and
  `instructor/round_scores/` map team IDs to folders. Never publish
  `instructor/`. When the site allocation ran, the private file's
  `projection.site_fraction` lists the alpha of each of that team's own sites
  (the instructor's per-team diagnostics carry the same field); shared files
  keep only team-level fractions and aggregates;
- exact competitor plans, raw dispatch JSON, and team-specific failure details
  are not classroom-shared.

Keep submission directories, state files, raw audit JSON, and full diagnostics
instructor-only. Release only the intended team summary and shared aggregates.

## Output artifacts

A single batch output contains `leaderboard.csv`,
`submission_manifest.csv`, `evaluation.json`,
`evaluation_sha256.txt`, per-team files under `diagnostics/`, and per-period
dispatch files under `dispatch/` (full mode), and `site_net_withdrawal.csv`,
the input of the next Submission 2. A classroom run additionally writes
`week-*/submission-*/shared/summary.json`,
`shared/aggregate_periods.json`, salted team summaries, classroom output
hashes, and the instructor-only `instructor/` directory (final leaderboard,
per-round scores, folder secret). Use the leaderboard and classroom-safe summaries for release; retain
the manifest, diagnostics, dispatch files, state file, and evaluation JSON for
audit.

`leaderboard.csv` ends with `service_fraction` (share of the requested
capacity allocated; below 1 only after the site allocation, empty for rejected
or infeasible rows) and `dropped` (`True` when the allocation gave the team
nothing, so `served_load_mwh` is 0 although `feasible` is `True`).
