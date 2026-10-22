# Classroom game state and within-week carry-over

This document describes the persistent-state contract implemented by
`src/ercot_game/game_state.py` and `src/ercot_game/round_coordinator.py`.
The file name is historical: the released game has no calendar years and no
multi-year asset state. Every submission uses the same representative-day
package (`data/processed/activsg2000_representative_v1`, 120 hourly periods
standing for the next ten years), and the only thing that carries over is
Submission 1 load, inside one week, as Submission 2 base load. The retired
half-year asset ledger is described at the end.

## Three weekly matches

The released classroom sequence is six submissions grouped into three
two-submission weeks (round keys from
`data/teaching/game_release_representative_v1.json`):

| Week | Submission 1 | Submission 2 | Energy cost | Ranking |
|---|---|---|---|---|
| Week 1 | `week-1-submission-1` | `week-1-submission-2` | none | Feedback-only and unranked. |
| Week 2 | `week-2-submission-1` | `week-2-submission-2` | none | Both submissions scored. |
| Week 3 | `week-3-submission-1` | `week-3-submission-2` | LMP, both submissions | Both submissions scored. |

The coordinator requires the six rounds in order. It rejects a second
submission when the first submission for that week has not committed
successfully. At the start of every week the state is reset to the
representative base: the carried base load and the site ledger are cleared.
Week 1 produces feedback but contributes no score. In Weeks 2 and 3 each
weekly ranking ranks the Submission 1 + Submission 2 total, and the final game
score is Week 2 S1 + Week 2 S2 + Week 3 S1 + Week 3 S2 (an invalid submission
scores 0).

## Canonical plan and evaluator-assigned assets

The active public CSV has exactly one row per site:

```text
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
```

It contains no hourly rows, public generator IDs, storage IDs, or SOC fields.
Generator capacity is at most 0.5 x connection capacity, and storage is either
zero or has energy equal to four times power. For every positive team-owned
generator or storage capacity, the evaluator derives a deterministic private
asset ID from the team and site identity. Assets are owned by the submitting
team and cannot serve another team.

## Submission 1 sites as Submission 2 base load

After a usable Submission 1 evaluation, the batch writer records each site's
hourly net grid withdrawal in `site_net_withdrawal.csv`: site load served minus
its own private generation and battery net discharge. The coordinator sums it
by bus into `carried_base_load_mw_by_bus` in the game state.

For Submission 2, `materialize_base_load_artifact` in
`src/ercot_game/base_load.py` writes a derived scenario artifact whose
`demand_bus.csv` is the representative base demand plus that withdrawal. In a
`classroom` run it goes to `<state dir>/base_load/<round_key>`; in a standalone
`ercot-game-batch run --base-load-from <Submission 1 output dir>` it goes to
`<output-dir>/base_load_artifact` (or `--base-load-artifact-dir`).

Submission 1 sites are then fixed load. They are not re-evaluated, re-scored,
re-projected or re-dispatched in Submission 2, and they keep their Submission 1
ten-year value. A Submission 2 CSV lists only new sites; a file that reuses
one of its team's Submission 1 `site_id`s is rejected. Each site's capital is
therefore charged once, in the submission that lists it. The instructor
releases the Submission 2 base load to students as per-bus totals only, never
as teams' plans.

## Transactional round boundary

`evaluate_round()`:

1. loads the prior state or starts a new state;
2. resolves the week and submission number (the week sets the energy charge);
3. resets the state when the week changes;
4. validates the current canonical CSV files and isolates rejected files;
5. for Submission 2, drops files that reuse Submission 1 site IDs and builds
   the base-load artifact;
6. evaluates the accepted plans;
7. after Submission 1, stores the per-bus net withdrawal; and
8. atomically saves the advanced state.

A plan-loader failure, base-load build failure, evaluator exception, or
unusable dispatch leaves the prior state file unchanged. Accepted teams can
still be evaluated when another submitted file is malformed.

## Storage state of charge

No stored energy carries between days, submissions or weeks. The prepared
storage model is grid-operated, ideal-efficiency, and team-dedicated. It
enforces power limits, energy limits, one-hour SOC transitions
(`SOC[t] = SOC[t-1] - 1 h * p[t]` with one signed net-power variable `p[t]` per
asset and period), discharge energy no greater than the stored energy, and the
`daily_exact_cycle` boundary: every representative day (24 hourly periods)
starts half full and ends exactly half full. Discharge is capped to the owning
team's load.

## Fair projection and state safety

Projection diagnostics are validated before state commit. Every diagnostic map
must contain only accepted team IDs; rejected or unknown teams cause the
transaction to fail. Per-team service fractions, projected loads, requested
MW, the common level, and proportional-fair utility are audit data, not
student input.

Classroom output is split from raw audit output. The shared safe output contains
aggregate counts, aggregate periods, and aggregate projection metadata. Each
team's own scalar result is written under a hashed private directory. Exact
competitor sites, asset capacities, raw dispatch periods, and full failure
diagnostics remain instructor-private.

## Retired half-year asset ledger (legacy)

The code still supports the retired half-year schedule (round keys
`2027_jan_jun` ... `2029_jul_dec` on the six-hour `activsg2000_scenarios_v2_6h`
package); a state adopts the schedule of its first round. On that schedule
only, the coordinator keeps an `AssetLedger` within a week: Submission 1 sites
and evaluator-assigned assets are materialized into Submission 2 (omitted
sites become zero-load placeholders), are re-dispatched with them, and are not
charged capital a second time (`CapitalCostScope`); an asset identity conflict
raises `AssetStateError`. The ledger resets at each week. This path is kept
for reproducibility and tests, not for the released game.

The old long-form hourly CSV and submitted asset-label fixtures are retained
only where tests explicitly exercise compatibility parsing. They are not part
of this state contract or the student workflow.
