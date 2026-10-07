# Instructor batch examples

These deterministic CSVs are teaching fixtures for the current long-form
submission schema. They are not real student submissions. They are deliberately
small one-period smoke fixtures for demonstrating parser errors and the
failure-isolation path; they are not valid production half-year submissions.
Use the instructor guide for the 4,368-hour and 4,416-hour production runs.

The files demonstrate the approved joint-infeasibility behavior:

- `team-a.csv` is a moderate, valid one-period submission that can be scored.
- `team-b.csv` is a valid but intentionally oversized one-period submission.
  When both are evaluated together, the evaluator first attempts fair
  continuous projection; if projection is unavailable, deterministic fallback
  identifies the batch-blocking team and preserves valid-team scoring.
- `invalid-negative-load.csv` has the same schema but an intentionally invalid
  negative load. It is retained in `submission_manifest.csv`, excluded from
  the DCOPF, and assigned the configured infeasible score.

The active production header is the bus-based schema from
`ercot_game.csv_submission.BUS_CSV_COLUMNS`:

```text
team_id,submission_id,period,bus_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh
```

The examples use Zenodo bus `3001003`, valid generator `14023`, and period `1`,
so they can be evaluated with a one-period smoke-test horizon. Storage columns
are active in the current schema; these particular fixtures leave them blank.
There are no curtailment or load-shedding fields, and the fixed submitted load
is not curtailed.

From the repository root, an example run is:

```bash
ercot-game-batch run \
  --submissions-dir examples/instructor_batch \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_jan_jun_v1.json \
  --horizon 1 \
  --period-indices 0 \
  --output-dir work/instructor_batch_example_results
```

The shipped files use the real catalog ID and bus schema. The intentionally
invalid fixture is included so the same command also demonstrates per-file
rejection and manifest retention. Do not use this one-period command for
classroom scoring; production requires complete 4,368- or 4,416-period files.
