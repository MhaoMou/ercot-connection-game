# ACTIVSg2000 scenario package

The production game uses the public synthetic Texas ACTIVSg2000 model. The
canonical classroom release is the representative-day package
`data/processed/activsg2000_representative_v1`: 5 representative days x 24
one-hour periods = 120 periods that together stand for the next ten years of
the game. There are no calendar years in the game; the source year labels
below (2027--2029) belong to the derivation input only. They are not historical source-data years or forecasts.

## Representative-day package

The package was derived from the 2028 blocks of the hourly source package
(below). The build and validation tools are maintained by the instructor and
are not distributed with this repository; the released package is complete
as committed and needs no rebuilding. The 366 days of 2028 are described by their 24-hour system load
divided by the annual peak hour, clustered into four groups with deterministic
PAM k-medoids (no random numbers), and each medoid becomes a representative
day. The day with the annual peak hour is added as a fifth day with weight
exactly 1. The other weights are cluster sizes scaled so that all five weights
sum to 365:

| Day | Date | Source block | Weight | Periods |
|---:|---|---|---:|---|
| 0 | 2028-01-03 | `jan_jun` | 83.77 | 0-23 |
| 1 | 2028-05-10 | `jan_jun` | 99.73 | 24-47 |
| 2 | 2028-07-12 | `jul_dec` | 82.77 | 48-71 |
| 3 | 2028-09-10 | `jul_dec` | 97.73 | 72-95 |
| 4 | 2028-09-15 (peak day) | `jul_dec` | 1 | 96-119 |

The system peak is period 109. `representative_days.csv` and `manifest.json`
record the selection, the weights, and the source periods. Bus demand is
materialized in `demand_bus.csv` (one row per period); generators, branches
and DC lines are copied from the source block with static limits. The
manifest reports `validation_status: passed` only after every one of the 120
periods solves the single-period DCOPF; the committed manifest records this
validation (`validation_status: passed`, 120 passed periods).

The scoring rules `data/teaching/dispatch_scoring_rules_representative_v1.json`
weight period `t` by
`1 h x day weight x 7.0236` (ten-year annuity factor at 7%); the weights sum
to 61,526.57 hours.

## Hourly source package

The representative days were selected from an hourly source package
(`activsg2000_scenarios_v1`) that is kept by the instructor and is not
published in this repository; students and the evaluator never need it. It
covers six half-year blocks (source year labels 2027--2029) on the fixed
ACTIVSg2000 topology of 2,000 buses, 3,206 branches, and 544 generators.

Bus demand starts from the ACTIVSg2000 bus PD values and uses a bounded
calendar-aware seasonal, daily, and weekly multiplier. Active generators use
their catalog status, PMIN, and PMAX values in every hour. ACTIVSg2000 does
not provide generator technology labels or hourly availability data, so no
synthetic wind/solar derating is applied. Generator marginal costs and branch
limits are copied from the public ACTIVSg2000 files.

This is a controlled instructional scenario. It is not historical ERCOT
telemetry, an official ERCOT model, or a forecast.

## Provenance

- [ACTIVSg2000 source model](https://github.com/caseformat/ACTIVSg2000)
- Birchfield et al., “Grid Structural Characteristics as Validation Criteria
  for Synthetic Networks,” IEEE Transactions on Power Systems, 2017.
