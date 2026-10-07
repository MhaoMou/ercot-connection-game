# ERCOT Instructor Batch Evaluation

`ercot-game-batch` evaluates a directory of long-form student CSV submissions
against the prepared Texas dispatch artifact. It writes the ranked leaderboard
and audit artifacts to one output directory; that directory is the source of
truth for the ranking and audit record.

The production data path is the Texas portion of the Zenodo U.S. Test System
dataset. Student files use source `bus_id` values from that artifact and
generator IDs from `generator_limits.csv`; this batch workflow is distinct from
the older browser teaching fixture and does not use the browser's planning-
region IDs.

The prepared Zenodo demand artifact is timestamped **2016**. The assignment
uses its January--June and July--December halves as two teaching-round
calendars; these timestamps are a historical replay, not a 2028 forecast.

The supported full-application execution mode is from a source checkout. A
wheel contains the Python runtime packages, but browser assets, scoring rules,
and prepared dispatch CSVs remain repository-level resources and must be
supplied by path.

## Run a batch

January--June uses 4,368 one-hour local scoring periods and source rows
`0..4367`:

```bash
ercot-game-batch run \
  --submissions-dir work/half_year_submissions \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_jan_jun_v1.json \
  --horizon 4368 \
  --source-period-offset 0 \
  --workers 8 \
  --projection-iterations 10 \
  --output-dir work/batch_results_jan_jun
```

July--December uses 4,416 one-hour local scoring periods and source rows
`4368..8783`:

```bash
ercot-game-batch run \
  --submissions-dir work/half_year_submissions \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_jul_dec_v1.json \
  --horizon 4416 \
  --source-period-offset 4368 \
  --workers 8 \
  --projection-iterations 10 \
  --output-dir work/batch_results_jul_dec
```

The command requires a submission directory, prepared dispatch artifact,
scoring-rules JSON, output directory, and positive horizon. Canonical student
files identify Zenodo source buses directly with `bus_id`; `--region-map`
remains optional compatibility support for older files using the legacy
`site_id` alias. Every bus appearing in a production CSV must have one row for
every period in the selected half-year. Partial pilot files are rejected before
dispatch.

`--period-indices`, when supplied, selects local scoring periods and is reserved
for explicitly labeled smoke tests or debugging. `--source-period-offset`
maps local periods to source-artifact rows. The output records both local
`period_indices` and `source_period_indices`, so the calendar alignment is
auditable.

`--workers` evaluates independent hourly DCOPF solves concurrently while
preserving requested period order. `--projection-iterations` is a lower bound
on the bisection precision used by fair continuous projection; the evaluator
also evaluates the zero-service endpoint and uses a fixed tolerance, so the
old `1/1024` service cutoff does not apply.

## CSV and resource contract

Use the active bus-based header:

```text
team_id,submission_id,period,bus_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh
```

`period` is one-based in the CSV (`1..4368` or `1..4416`). Each submitted bus
must be present for every period, including periods with zero load. Generator
IDs must be present in `generator_limits.csv`; their marginal operating costs
come from that public-data catalog rather than from a student-supplied cost.
Storage fields are active: a storage device has a positive power capacity in
MW and energy capacity in MWh, and its specification must remain consistent
across rows.

The dispatch model uses fixed submitted load and does not model curtailment.
Student generators and storage are team-owned local resources and cannot serve
another team. Storage is scheduled continuously with power and energy limits,
no simultaneous charge/discharge, initial and terminal state of charge at least
`0.5 B`, and one-hour energy transitions.

For the current classroom release, source generators use the nameplate
`p_max_mw` values from the Zenodo generator catalog. The prepared hourly
renewable profile files are retained as source metadata but are not imposed as
hard availability caps, because doing so made 14 otherwise dispatchable
July--December source hours infeasible.

## Evaluation behavior

Submissions are discovered deterministically from `.csv` files. A malformed
submission is rejected in isolation and receives the configured infeasible
score; other valid teams remain eligible for evaluation. If the joint dispatch
is infeasible, the evaluator first applies one common fair continuous service
fraction to all valid teams. If no projected dispatch is available, it uses
deterministic leave-one-team-out and individual fallback behavior where
possible. The applied competition scope and service fraction are recorded in
the audit output.

The score includes IT value, energy purchase cost, generator operating cost,
generator capital cost, site cost, storage capital cost (MW and MWh
components), and storage operating cost. The evaluator's scoring-rules JSON is
the authoritative source for the numerical coefficients.

## Output artifacts

The output directory contains `leaderboard.csv`, `submission_manifest.csv`,
`evaluation.json`, `evaluation_sha256.txt`, per-team files under
`diagnostics/`, and per-period dispatch files under `dispatch/`. The JSON
records the rules, scenario and evaluator versions, local/source period
indices, input hashes, failure-isolation events, team scores, and output
hashes. Use the leaderboard for ranking and the manifest, diagnostics,
dispatch files, and evaluation JSON for audit and troubleshooting.
