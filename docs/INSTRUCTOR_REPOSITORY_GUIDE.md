# Instructor Repository Guide

This repository contains the instructor-facing implementation of the ERCOT
data-center connection-planning game. It has three responsibilities:

1. prepare or verify the Zenodo-derived dispatch artifacts;
2. validate and evaluate long-form student CSV submissions with the
   instructor-side DCOPF batch evaluator; and
3. publish a privacy-safe, read-only results package for the browser map.

The repository is a teaching and research tool. It is not an official ERCOT
model, an ERCOT operations interface, or a production market simulator.

## Architecture

```text
student CSV files
        |
        v
CSV validator and batch evaluator
        |
        +--> ranking/evaluation artifacts (private instructor output)
        |
        v
sanitized results package
        |
        v
read-only browser viewer at /results
```

The browser never evaluates dispatch. Python remains authoritative for input
validation, projection, DCOPF dispatch, scoring, and failure isolation.

The public-data distinction is:

```text
Zenodo source data
        -> prepared Texas dispatch artifact
        -> instructor-side DCOPF/scoring evaluation
        -> sanitized browser results
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/ercot_game/` | Evaluator, CSV contract, batch runner, practice server, classroom service |
| `tools/zenodo_texas/` | Zenodo download/preparation and dispatch-data adapters |
| `scripts/` | Instructor utilities, package builders, CSV checks, reproducibility helpers |
| `data/teaching/` | Versioned teaching/scoring configuration |
| `data/processed/` | Prepared public-network and dispatch artifacts |
| `web/` | Practice interface and read-only results viewer |
| `tests/` | Unit, integration, contract, reproducibility, and browser-asset tests |
| `docs/` | Methodology, release notes, classroom instructions, and calibration records |
| `examples/` | Small, safe examples for instructor onboarding |
| `work/` | Local scratch/evaluation output; intentionally not versioned |

## Environment setup

Use Python 3.11 or newer. The project declares `highspy` as the DCOPF
dependency.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the full test suite:

```bash
PYTHONPATH=src pytest -q
```

## Check a student CSV

```bash
ercot-game-check-csv path/to/team.csv \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --horizon 4368
```

The expected header, period conventions, generator catalog rules, storage
fields, and error messages are documented in
[`ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`](ERCOT_INSTRUCTOR_BATCH_EVALUATION.md).

## Run an instructor batch

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
and source-period offset `4368`.

The batch output is instructor-private. Keep the complete evaluation and audit
files out of public or student-facing hosting.

## Publish sanitized results

The browser-facing package contains public network geometry, one selected
team's allowlisted report, and privacy-preserving aggregate feedback. It does
not contain raw CSV files, all-team plans, audit bundles, or cross-team
diagnostics.

```bash
PYTHONPATH=src python scripts/build_results_package.py \
  --network data/processed/texas_dispatch_source_v1 \
  --evaluation work/batch_results_jan_jun/evaluation.json \
  --team team-alpha \
  --submissions-dir path/to/submissions \
  --output-dir web/data/results
```

Start the local server:

```bash
PYTHONPATH=src python -m ercot_game.practice_server \
  --host 127.0.0.1 --port 8000
```

Open `/` for the practice interface and `/results` for the read-only results
viewer.

## Data and reproducibility policy

Raw downloads, archives, large demand tables, local batch outputs, and scratch
experiments are ignored by Git. Their source URLs, expected filenames, hashes,
and preparation instructions belong in manifests and documentation rather
than in the repository history.

Before a release, verify:

```bash
PYTHONPATH=src pytest tests/test_reproducibility.py tests/test_zenodo_dispatch_preparation.py -q
```

See [`ERCOT_PUBLIC_NETWORK_PROVENANCE.md`](ERCOT_PUBLIC_NETWORK_PROVENANCE.md),
[`ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`](ERCOT_INSTRUCTOR_BATCH_EVALUATION.md),
and [`ERCOT_RELEASE_READINESS.md`](ERCOT_RELEASE_READINESS.md) for the data
boundary, evaluation contract, and release checklist.

## Security and privacy

Do not commit:

- student CSV submissions;
- raw or unredacted evaluation/audit bundles;
- credentials, tokens, local filesystem paths, or private URLs;
- instructor-only databases or classroom session state.

The GitHub repository should be private even though the public-data sources and
the teaching code are documented.
