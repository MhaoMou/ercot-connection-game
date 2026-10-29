# Repository Guide

This repository contains the ACTIVSg2000-based data-center connection-planning
game: the data you plan on, the tools you use to check and preview your plans,
and the official evaluator that validates every team's CSV files, runs the
joint DCOPF dispatch, and produces auditable team scores. This guide explains
how the pieces fit together. If you are new, start with the tutorial
(`docs/student_tutorial/tutorial.pdf`).

The released game runs on one representative-day package: 5 representative
days x 24 hourly periods = 120 periods that together stand for the next ten
years (no calendar years). Scores are ten-year present values. The hourly
`activsg2000_scenarios_v1` source blocks are its derivation input; they are
built locally and are not distributed.

## Production boundary

```text
ACTIVSg2000 hourly source -> 5 representative days x 24 h (~2,000 buses)
        -> canonical seven-column site-level student CSV
        -> catalog validation (optional checker context)
        -> daily-cycle joint DCOPF
        -> utilitarian site allocation when needed
        -> score components, ranking, and audit outputs
```

The retired browser/practice implementation is recoverable under
`archive/legacy/`; it is not packaged, launched, or part of the current game.

## Important paths

- `src/ercot_game/`: canonical CSV and batch-evaluation code.
- `tools/activsg2000/`: DCOPF and dispatch adapter.
- `src/ercot_game/base_load.py`: turns Submission 1 sites into Submission 2
  base load.
- `data/processed/activsg2000_representative_v1/`: canonical representative-day
  package (120 hourly periods, day weights in `representative_days.csv`).
  The tools that built it are maintained by the instructor and not
  distributed.
- `data/teaching/dispatch_scoring_rules_representative_v1.json`: ten-year
  present-value scoring rules.
- `data/teaching/game_release_representative_v1.json`: release config (weeks,
  energy-cost switch, Submission 2 rules).
- `data/teaching/ieee14_demo_representative/`: small IEEE 14-bus demo package
  with the same 120-period structure.
- `scripts/check_submission.py`: student-file validation entry point.
- `examples/eight_team_round/`: deterministic eight-team example round with its
  results and classroom grid map.
- `tests/`: active production tests.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Validate and evaluate

```bash
ercot-game-check-csv \
  --file path/to/team.csv \
  --artifact-dir data/processed/activsg2000_representative_v1

# Submission 1 (the representative package and rules are the defaults)
ercot-game-batch run \
  --submissions-dir path/to/submission1 \
  --week 2 --submission-number 1 \
  --workers 8 \
  --output-dir work/week2_submission1

# Submission 2: Submission 1 sites become base load
ercot-game-batch run \
  --submissions-dir path/to/submission2 \
  --week 2 --submission-number 2 \
  --base-load-from work/week2_submission1 \
  --workers 8 \
  --output-dir work/week2_submission2
```

The current CSV header is:

```text
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
```

Each data row is one site. There are no `period`, hourly `load_mw`,
`submission_id`, `generator_id`, or `storage_id` columns, and no horizon rows to
generate. The seven-column CSV has no asset-ID columns; the evaluator assigns
deterministic private generator and storage IDs internally from each team/site
pair, and those IDs are not student inputs.
`--artifact-dir` and `--horizon` remain optional catalog context for the
checker. The retired hourly schema is kept only for explicitly marked
compatibility fixtures.

## Fast student preview

Students can use the `ercot-game-preview` command in Colab to iterate on a
plan without waiting for the exact storage-coupled LP:

```bash
PYTHONPATH=src python -m ercot_game.student_preview \
  --submissions-dir path/to/submissions \
  --week 2 \
  --workers 2 \
  --output preview.json
```

The preview is a conservative screening tool. It defaults to the
representative package and rules and solves all 120 periods (`--preview-stride`
defaults to 1 there); `--week` or `--energy-cost` sets the energy charge. It validates submitted storage and includes storage
construction cost, but uses an idle-storage dispatch policy for speed.
Consequently it is a conservative screening estimate and must not be used for
ranking or final scores. The instructor batch evaluator remains authoritative and performs the
exact joint storage dispatch LP.

The CSV uses source `bus_id` values directly. Site capacities are specified in
MW/MWh, and each team's submitted resources serve only that team. The score
includes IT value, site cost, generator capital/operating cost, and storage
capital cost (undiscounted), plus ten-year present values of IT value
($1,000/MWh), generator operating cost and, in Week 3 only, the energy cost (energy purchases
at the LMP of the joint dispatch) (`--week 3` or `--energy-cost on`). Week 1 is
practice/feedback only; in Weeks 2 and 3 both submissions are scored, and the
final game score is Week 2 S1 + Week 2 S2 + Week 3 S1 + Week 3 S2. Each week
starts from the representative base. Within a week, Submission 2 is evaluated
with `--base-load-from <Submission 1 output dir>` (required on the
representative package): each Submission 1 site's hourly net grid withdrawal
(`site_net_withdrawal.csv`) is added to the base load, and Submission 2 CSVs
list only new sites. Release that base load to students as per-bus totals
only, never as teams' plans. `--submission-number` is not a CSV field.

To prepare that release before evaluating Submission 2, build and validate the
Submission 2 artifact alone:

```bash
ercot-game-batch base-load \
  --base-load-from <Submission 1 output dir> \
  --output-dir <Submission 2 release data dir>
```

Every period is re-solved; periods that sit within solver tolerance of the
feasibility boundary (Submission 1 serves teams up to that edge) are accepted
after a demand change of at most 1e-3 MW, recorded in the artifact's
`manifest.json` (`validation.tolerance_adjustments`); a real infeasibility
stops with the offending periods and `validation_status: failed`. See
`docs/OFFICIAL_EVALUATION.md`. `--workers N` parallelizes the
hourly dispatch without changing results, `--roster <file>` lists teams with
no submission, and the `classroom` command writes
`instructor/final_leaderboard.csv` (the four graded scores and their total)
and salts the private team folder names with an instructor-only secret.

## Classroom grid map

After each evaluated submission, release a privacy-safe interactive map with
the score breakdown and service fractions. Each bus is colored by the total MW
*served* to all scored teams at that bus (site fraction x connection
capacity, read from the evaluator output's `site_net_withdrawal.csv`), so
rejected files (including Submission 2 files that reuse a Submission 1
`site_id`), infeasible teams and sites allocated nothing add nothing; no team or site IDs appear in the file. Each line is colored by its
peak loading over the 120 evaluated hours (from `dispatch/`, written with
`--output-mode full`). The artifact defaults to the representative package.

```bash
ercot-game-grid-map \
  --evaluation-dir <evaluator output directory> \
  --title "Week 2, Submission 1" \
  --output <release directory>/grid_map.svg
```

`--dispatch-dir` defaults to `<last --evaluation-dir>/dispatch` when present.
For Submission 2, pass the Submission 1 output first and the Submission 2
output second (`--evaluation-dir <S1 out> --evaluation-dir <S2 out>`) so
Submission 1 sites (now base load) are shown too, with Submission 2 line
loading. The bus positions and names come from
`data/teaching/activsg2000_geo_layout_v1.json` (approximate geographic
locations from the 2016 ACTIVSg2000 release; bus names from the MATPOWER
`case_ACTIVSg2000.m`), so every round's map looks the same.

The map is interactive in any browser:

- **Hover a bus** for its name and its load at the system peak hour, split
  into existing base load and new data-center load served to all teams
  together, plus its average and highest energy price (LMP).
- **Hover a line** for its end buses, thermal limit, peak loading and hours at
  or near its limit.
- **Two layers**: "MW served" (new data-center load per bus) and "Energy
  price (LMP)" (average price per bus over the evaluated hours, from
  `dispatch/`).
- **Click a red (binding) line** to highlight the buses where one more MW of
  new load adds at least 0.05 MW to its flow, from DC shift factors relative
  to the reference bus (an approximation).
- **Search** for a bus by number or name; zoom in to see bus numbers. Scroll
  or pinch zooms gently, drag pans, and double-click resets.

A bus with a single team still reveals that team's total at that bus, but not
which team it is; the map never splits load by team.

## Data and privacy

Keep student CSVs, full evaluation JSON, dispatch diagnostics, and audit
bundles instructor-private. Do not publish cross-team plans. Raw downloads and
large local outputs remain outside version control according to `.gitignore`.

Run the active suite with:

```bash
pip install -e ".[test]"   # once, installs pytest
PYTHONPATH=.:src pytest -q
```
