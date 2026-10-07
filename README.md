# ERCOT Data-Center Dispatch Game

Instructor-facing implementation of a competitive connection-planning game
based on the Texas portion of the Zenodo U.S. Test System dataset. The active
workflow uses the approximately 2,000-bus prepared dispatch artifact, not the
retired browser prototype or its abstract teaching network.

## Current production pipeline

```text
Zenodo Texas dispatch artifact (~2,000 buses)
        -> student long-form CSV submissions
        -> CSV/catalog validation
        -> joint DCOPF dispatch
        -> fair continuous projection if required
        -> team score and ranking
```

The Python evaluator is authoritative. Students submit CSV files; instructors
run the batch evaluator and return scores plus the intended privacy-safe
feedback artifacts. Student-owned generators and storage serve only their own
team. The score includes IT value, energy purchases, site cost, generator
capital/operating cost, and storage capital/operating cost.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/ercot_game/` | Canonical CSV reader, validator, batch evaluator, and CLI |
| `tools/zenodo_texas/` | Prepared-artifact loading, DCOPF, storage scheduling, and joint dispatch |
| `data/processed/texas_dispatch_source_v1/` | Prepared Zenodo Texas buses, branches, demand, generators, and costs |
| `data/teaching/` | Half-year scoring rules |
| `scripts/` | CSV checks, fixture generation, simulation, and summary utilities |
| `tests/` | Active CSV, batch, DCOPF, storage, and Zenodo adapter tests |
| `archive/legacy/` | Recoverable retired browser/practice implementation and historical tests |
| `docs/` | Current instructor, student, calibration, and data documentation |

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
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --horizon 4368
```

The active header is:

```text
team_id,submission_id,period,bus_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh
```

Each submitted bus must cover every period in the selected half-year. Generator
IDs and marginal costs come from `generator_limits.csv`; students submit only
the generator capacity. Storage uses MW power capacity and MWh energy capacity.

## Evaluate a half-year round

January--June:

```bash
ercot-game-batch run \
  --submissions-dir path/to/submissions \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_jan_jun_v1.json \
  --horizon 4368 \
  --source-period-offset 0 \
  --workers 8 \
  --projection-iterations 10 \
  --output-dir work/batch_results_jan_jun
```

July--December uses `dispatch_scoring_rules_jul_dec_v1.json`, horizon `4416`,
and source offset `4368`.

If the joint plan is infeasible, the evaluator applies the documented fair
continuous common service projection before deterministic fallback isolation.
Malformed submissions are rejected independently so valid teams can still be
scored. The output directory is the instructor-side source of truth.

See [`docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`](docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md)
for the complete CSV, dispatch, projection, scoring, and privacy contract.

## Tests

```bash
PYTHONPATH=src pytest -q
```

The active test suite covers the production Zenodo CSV/DCOPF/scoring path. The
previous browser/practice product is preserved only under `archive/legacy/` and
is not packaged, launched, or used as the current game implementation.
