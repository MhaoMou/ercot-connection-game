# Student Quickstart

This assignment is a file-based planning game. Each team submits one CSV
proposal for the released half-year horizon. The instructor-side evaluator
checks the file, combines valid team proposals, solves the hourly DCOPF
dispatch problem, applies the documented fair continuous projection if the
joint request is infeasible, and returns scores and diagnostics.

## Workflow

1. Read the assignment handout and the released data dictionary.
2. Inspect the Zenodo Texas bus, branch, generator, and demand tables.
3. Choose one or more source `bus_id` values and create an hourly load profile.
4. Optionally attach team-owned generators and storage devices to those buses.
5. Write the required CSV file using the exact header and one-based period index.
6. Run the local format checker before submitting:

   ```bash
   python scripts/check_submission.py \
     --file submissions/team_a.csv \
     --year 2017 --round jan_jun \
     --artifact-dir data/processed/texas_dispatch_source_v1
   ```

   Use `--year 2017 --round jul_dec` for the July--December release. The
   instructor will identify the released year; the checker derives the exact
   horizon from that year and half-year.

7. Submit the CSV through the instructor-designated channel.
8. Use the returned score, dispatch summary, and binding-resource diagnostics
   to refine the next submission.

## Important modeling facts

- The Texas subset of the Zenodo dataset is the source of the bus and
  generator identifiers.
- Each submission covers one half-year of one-hour periods. The released
  calendar determines the exact horizon: 2016 has 4,368/4,416 hours and 2017
  and 2018 have 4,344/4,416 hours for January--June/July--December.
- A team's generators and storage serve only that team's load.
- Generator operating costs are taken from the supplied Zenodo generator
  catalog. Student files specify the selected generator and capacity, not a
  replacement operating-cost curve.
- Storage is specified in MW and MWh. It must respect its power and energy
  limits, cannot discharge more energy than is currently stored, and must end
  the horizon with at least half of its energy capacity available.
- The exercise does not include a student-controlled curtailment decision.

See [Instructor Batch Evaluation](ERCOT_INSTRUCTOR_BATCH_EVALUATION.md) for
the canonical CSV schema and evaluation outputs. See the assignment handout in
`docs/student_manual/` for the full rules and scoring explanation.
