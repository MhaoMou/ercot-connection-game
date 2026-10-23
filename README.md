# ERCOT Data-Center Dispatch Game

Instructor-facing implementation of a competitive connection-planning game
based on the public synthetic Texas ACTIVSg2000 2,000-bus system. The active
workflow uses the checked-in representative-day package
(`data/processed/activsg2000_representative_v1`): 5 representative days x 24
hourly periods = 120 periods, weighted to stand for the next ten years. All 120
periods have passed the release DCOPF validation. The hourly ACTIVSg2000 source
package from which the days were drawn is a local derivation input and is not
distributed or needed to play.

## Current production pipeline

```text
ACTIVSg2000 hourly source -> 5-day x 24-hour representative package (validated)
        -> student canonical site-level CSV submissions
        -> CSV/catalog validation
        -> daily-cycle joint DCOPF dispatch (per hourly period)
        -> fair continuous projection if required
        -> ten-year present-value team score and ranking
```

The Python evaluator is authoritative. Students submit CSV files; instructors
run the batch evaluator and return scores plus the intended privacy-safe
feedback artifacts. Student-owned generators and storage serve only their own
team. The score (from `data/teaching/dispatch_scoring_rules_representative_v1.json`)
is a ten-year present value: IT value of \$1,000/MWh served, a team-generator
curve of \$80/\$150/\$250 per MWh over 25%/50%/25% of capacity and (in Week 3)
grid energy at the LMP, each weighted per period by `period_weight_hours`
(1 h x day weight x annuity factor A = 7.0236 at a 7% discount rate; the
weights sum to 61,526.57 h, so a fully served MW is worth about \$61.5M of IT
value). Capital costs are charged once and undiscounted: site cost of \$25M/MW
of connection capacity, generator capital cost of \$2.0M/MW, and storage
capital costs of \$400k/MW plus \$250k/MWh. Generator capacity is capped at
0.5 x connection capacity, and each generator may produce at most 2 h x its
capacity per representative day (`generator_daily_energy_hours` = 2, a
run-hour budget like an engine air permit); storage is zero or exactly four
hours (B = 4P).
Without energy cost a site breaks even at about 41% served. Storage operating
cost is not charged, and an invalid submission scores 0.

The five representative days are 2028-01-03 (weight 83.77), 05-10 (99.73),
07-12 (82.77), 09-10 (97.73), and the peak day 09-15 (weight exactly 1, holding
peak period 109); the day weights sum to 365.

The classroom game has three weekly matches of two submissions, six
submissions in all, every one on the same representative package (there are no
calendar years). Week 1 is practice/feedback only, with no energy cost. Week 2
is scored with no energy cost. Week 3 is scored with grid energy charged at the
LMP in both submissions. The final ranking is the sum of the four scores:
Week 2 S1 + Week 2 S2 + Week 3 S1 + Week 3 S2. In Submission 2 the base load
is the representative base plus each Submission 1 site's hourly net grid
withdrawal; Submission 1 sites keep their Submission 1 value, and the
Submission 2 CSV lists only new sites. Between submissions the instructor
releases only per-bus load totals, never teams' plans. Each week resets to the
representative base.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/ercot_game/` | Canonical CSV reader, validator, batch evaluator, and CLI |
| `tools/activsg2000/` | Scenario construction, per-period validation, DCOPF, storage scheduling, and joint dispatch |
| `data/processed/activsg2000_representative_v1/` | Canonical validated representative-day ACTIVSg2000 package (built by `tools/activsg2000/build_representative_package.py`) |
| `data/teaching/` | Scoring rules and release config (`dispatch_scoring_rules_representative_v1.json`, `game_release_representative_v1.json`) and the IEEE 14-bus practice demo (`ieee14_demo_representative/`) |
| `scripts/` | CSV check and scoring-rules generation (`create_representative_scoring_rules.py`) |
| `tests/` | Active CSV, batch, DCOPF, storage, and ACTIVSg2000 adapter tests |
| `docs/` | Student tutorial, guest lecture, hyperparameters, instructor guides, and data documentation |
| `examples/eight_team_round/` | Eight-team example round and grid map |

## Setup

Python 3.11+ and `highspy` are required:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Validate a student CSV

```bash
ercot-game-check-csv \
  --file path/to/team.csv \
  --artifact-dir data/processed/activsg2000_representative_v1
```

The checker enforces the release's 0.5 x connection generator cap.

The active canonical header is exactly seven columns, with one data row per
site:

```text
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
team-blue,site-north,1001,40,20,10,40
team-blue,site-south,1002,15,0,0,0
```

Canonical submissions contain no hourly `period`/`load_mw` rows and no
`submission_id`, `generator_id`, or `storage_id` columns. `bus_id` values come
from the package's `bus.csv`; capacities use MW/MWh.

For Python callers, `CANONICAL_CSV_COLUMNS` is the named active constant.
`CSV_COLUMNS` and `BUS_CSV_COLUMNS` remain deprecated compatibility aliases to
that same tuple. The retired ten-column hourly names are available only for
explicit historical/legacy parsing and are not current submission examples.

## Evaluate a weekly round

Submission 1 of Week 2 (omit `--artifact-dir`/`--rules` to use the
representative release; `--week` sets the energy charge: weeks 1-2 off,
week 3 on):

```bash
ercot-game-batch run \
  --submissions-dir path/to/week2_sub1 \
  --artifact-dir data/processed/activsg2000_representative_v1 \
  --rules data/teaching/dispatch_scoring_rules_representative_v1.json \
  --week 2 --submission-number 1 \
  --workers 8 \
  --projection-iterations 10 \
  --output-dir work/week2_sub1
```

Submission 2 of the same week adds the Submission 1 sites to the base load:

```bash
ercot-game-batch run \
  --submissions-dir path/to/week2_sub2 \
  --week 2 --submission-number 2 \
  --base-load-from work/week2_sub1 \
  --workers 8 \
  --output-dir work/week2_sub2
```

`--base-load-from` is required for Submission 2 on the representative package
(the run stops with an error otherwise); it reads the Submission 1
`site_net_withdrawal.csv` and writes a derived artifact under
`<output-dir>/base_load_artifact`. Instead of `--week`, `--energy-cost on|off`
sets the LMP energy charge directly. Submission number is evaluator-side
metadata and is not a CSV column. The `classroom` command runs all six
submissions from one manifest.

Generator status, PMIN, PMAX, and marginal costs come from the dataset; because
ACTIVSg2000 does not provide technology labels or hourly availability data, the
release uses static generator limits.
See `docs/ACTIVSG2000_SCENARIO_PACKAGE.md`.

For practice, the IEEE 14-bus demo uses the same flow with
`--artifact-dir data/teaching/ieee14_demo_representative` and
`--rules data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json`.

Hosting capacity on the full package (`ercot-game-hosting-capacity`) solves
2,000 buses x 120 periods = 240,000 LPs, about 19 minutes with Gurobi
(32 workers) on a server.

If the joint plan is infeasible in a period, the evaluator applies the uniform
fair projection: a common MW level rises by water-filling, teams served below
50% of their request are dropped (largest short request first), and
deterministic fallback isolation follows only if that fails.
Malformed submissions are rejected independently so valid teams can still be
scored. The output directory is the instructor-side source of truth.

See [`docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`](docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md)
for the complete CSV, dispatch, projection, scoring, and privacy contract.

## Tests

```bash
pip install -e ".[test]"   # once, installs pytest
PYTHONPATH=.:src pytest -q
```

The active test suite covers the production ACTIVSg2000 CSV/DCOPF/scoring path. The
previous browser/practice product is preserved only under `archive/legacy/` and
is not packaged, launched, or used as the current game implementation.

## License

The source code is released under the [MIT License](LICENSE). The documentation
and course materials (the tutorial, slides, and files under `docs/`) are
released under [CC BY 4.0](LICENSE-docs.md).
