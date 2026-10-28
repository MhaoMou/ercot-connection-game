# Eight-team example round

A worked example of a full round with eight mock teams, using the site-level
submission format on the released representative-day package. It is not an official
student result and does not reveal any student's strategy.

## Scenario

- Scenario package: `data/processed/activsg2000_representative_v1` with the
  default `dispatch_scoring_rules_representative_v1.json` rules
- Horizon: 120 one-hour periods (five representative days), daily-cycle
  storage, a 2 h/day run budget for private generators
- Teams: 8, with 2 sites each; total requested and connected capacity 705 MW
- Private generation: 10--40 MW per team (at most 0.5 x the site's connection
  capacity); four-hour storage on one site per team
- Week 3, Submission 1: energy purchases settle against LMPs from the joint
  dispatch

Two teams deliberately request bus `7049` to demonstrate joint competition. The
complete joint plan was feasible, so the fair projection was not activated and
every team received its full requested connection capacity.

## Check the CSV files

From the repository root:

```bash
for file in examples/eight_team_round/submissions/*.csv; do
  PYTHONPATH=src python3 scripts/check_submission.py --file "$file" \
    --artifact-dir data/processed/activsg2000_representative_v1
done
```

## Re-run the evaluation

```bash
ercot-game-batch run \
  --submissions-dir examples/eight_team_round/submissions \
  --week 3 --submission-number 1 --workers 4 --output-mode full \
  --output-dir work/eight_team_round_results
```

Without `--artifact-dir`/`--rules` the evaluator uses the released
representative-day package and its rules; `--week 3` turns the energy charge
on. Add `--solver-backend gurobi` to force Gurobi (the default `auto` uses it
when a license is available, otherwise HiGHS).

## Recorded result

[`results.json`](results.json) is the compact result of the run above on a
laptop with HiGHS: about 9 seconds, about 0.5 GiB peak memory, all eight files
accepted, joint dispatch feasible, no projection. Ten-year present-value scores
range from $1.92B (team-08) to $4.54B (team-01). The run ID is recorded in the
JSON.

This is a standalone Submission 1 run, so every site and asset is charged
capital. Use the example to show the score decomposition, not as a
recommended calibration or a class leaderboard.

[`grid_map.svg`](grid_map.svg) is the classroom grid map for this run
(`ercot-game-grid-map --evaluation-dir <this run's output> --layout data/teaching/activsg2000_geo_layout_v1.json`):
buses colored by the total MW served to all scored teams (every request is
served in full in this uncongested run), lines colored by
peak loading over the 120 hours. Open it in a browser to hover, zoom, and pan.

The raw `evaluation.json` and per-period dispatch files are not checked in
because they are large.
