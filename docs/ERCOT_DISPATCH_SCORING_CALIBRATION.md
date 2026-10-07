# Dispatch-game scoring calibration

**Status:** Provisional calibration package for instructor review.

This document separates parameters that can be anchored to public engineering or
market data from parameters that are intentionally instructional. It applies to
the CSV/DCOPF competition path, which uses fixed submitted load and no
curtailment.

## Source-backed anchors

### Energy price

Use ERCOT real-time Settlement Point Prices as the market anchor. ERCOT settles
at 15-minute intervals and reports 2024 real-time Hub average prices of
`$27.37/MWh`, compared with `$52.48/MWh` in 2023. The released evaluator
operates on one-hour periods across a complete half-year. Any compact price
vector is therefore a repeating hourly teaching profile, not a six-period
submission horizon.

Sources:

- [ERCOT 2024 ORDC report](https://www.ercot.com/files/docs/2024/10/31/2024-biennial-ercot-report-on-the-ordc-20241031.pdf)
- [ERCOT real-time SPP display](https://www.ercot.com/content/cdr/html/20241107_real_time_spp.html)

**Legacy pilot profile:** `dispatch_scoring_rules_v1.json` uses ERCOT Day-Ahead Market
`HB_HUBAVG` prices for operating day `2026-10-04`, at hour-ending values
`[1, 6, 11, 13, 20, 23]`:

```text
[68.02, 39.16, 19.99, 18.42, 53.14, 46.49] $/MWh
```

This is a reproducible source-backed teaching vector, not a forecast or a
long-run ERCOT average. The selected hours intentionally include overnight,
low-price midday, and evening conditions. The source page is the [ERCOT DAM
Settlement Point Prices display](https://www.ercot.com/content/cdr/html/dam_spp.html);
the exact operating day and hours are recorded in the JSON provenance block.
The released half-year files use this six-value profile as a transparent
repeated instructional profile with `time_step_hours = 1`; the profile is
repeated over the selected 4,344-, 4,368-, or 4,416-hour calendar. It does not
replace the complete student submission horizon or claim to reconstruct
historical ERCOT hourly prices.

### Existing and candidate generator costs

For existing units, use the Zenodo generator-cost records already carried into
the prepared dispatch artifact. For candidate technologies, calculate a
marginal cost as:

```text
fuel price × heat rate + variable O&M
```

NREL ATB provides technology-specific CAPEX, fixed O&M, variable O&M, fuel,
capacity-factor, and performance assumptions. EIA also publishes generator
construction costs and historical operating expenses.

Sources:

- [NREL 2024 ATB technologies](https://atb.nrel.gov/electricity/2024/technologies)
- [NREL ATB equations and variables](https://atb.nrel.gov/electricity/2024/equations_%26_variables)
- [EIA generator construction costs](https://www.eia.gov/electricity/generatorcosts/)
- [EIA generation-cost data](https://www.eia.gov/tools/faqs/faq.php?id=19&t=6)

**Provisional rule:** do not use one universal `$100/MWh` value in the released
game. Select a named candidate technology and publish its cost assumptions, or
retain the default only for a clearly labeled pilot.

### Storage construction and operation cost

The evaluator separates storage capital cost into power capacity and energy
capacity:

```text
storage capital cost = $200,000/MW × power capacity
                     + $300,000/MWh × energy capacity
storage operating cost = $8/MWh × discharged energy
```

This gives approximately `$1,400/kW` for a four-hour system. It is close to
EIA's 2024 capacity-weighted battery construction benchmark of `$1,469/kW`
and NREL's 2021 utility-scale four-hour total-system benchmark of about
`$1,365/kW`. EIA's battery-storage case also reports `$40/kW-year` fixed O&M
and `$8/MWh` variable O&M. Because the current evaluator has no separate fixed
annual-O&M field, the `$40/kW-year` value is recorded as a reference while
`$8/MWh` is used as the operating-cost proxy; fixed O&M is not double-counted.

Sources:

- [EIA construction cost data](https://www.eia.gov/electricity/generatorcosts/)
- [EIA battery-storage cost assumptions](https://www.eia.gov/analysis/studies/powerplants/capitalcost/pdf/capcost_assumption.pdf)
- [NREL 2021 utility-scale battery storage ATB](https://atb.nrel.gov/electricity/2021/utility-scale_battery_storage)
- [NREL 2024 utility-scale battery storage ATB](https://atb.nrel.gov/electricity/2024/2023/utility-scale_battery_storage)

These are rounded instructional coefficients, not a project-specific bid or
tariff. The half-year rules files record the same provenance in JSON.

### Generator capital cost

Convert source CAPEX from `$ / kW` to `$ / MW`, then annualize it with the
chosen capital-recovery assumptions. The legacy calibration note used
`1,460` hours per representative period. The released half-year files use
literal one-hour intervals, so capital coefficients are applied once to the
plan and hourly operating quantities are multiplied by `1` hour.

The missing calibration choices are:

1. technology;
2. economic life;
3. discount rate or fixed-charge rate;
4. fraction of annualized cost assigned to the game.

NREL gives the relevant fixed-charge-rate and LCOE equations in its ATB
methodology.

**Current provisional anchor:** EIA's 2024 construction-cost table reports
`$841/kW` for combustion turbines. Using a 20-year life and an 8% discount
rate gives a capital-recovery factor of approximately `0.10185`, or about
`$85,656/MW-year`. The rules file rounds this to `$85,000/MW-year` for the
teaching game.

### Site/interconnection cost

LBNL reports empirical generator interconnection costs, including an average of
approximately `$194/kW` for completed projects during 2018–2024 in its recent
study. This is a useful anchor for generation interconnection, but it is not a
universal data-center load-connection tariff.

Source:

- [LBNL generator interconnection cost report](https://emp.lbl.gov/publications/generator-interconnection-costs-0)

**Current provisional rule:** use `$50,000/site` as a transparent instructional
proxy. This is deliberately much smaller than a full generation
interconnection upgrade and should be revisited after actual student plans are
available.

## Instructional parameters

The following cannot be responsibly inferred as a single market number:

| Parameter | Current decision needed |
|---|---|
| IT value of served load | Define it as opportunity value of service, not electricity price. Test `$100–250/MWh` and choose a value that creates strategic separation. |
| Infeasible score | Confirm `0`; no partial-service score is used. |
| Maximum load per site/team | Choose from DCOPF feasibility sweeps so both feasible and infeasible plans exist. |
| Maximum candidate-generator capacity | Set relative to site peak load. |
| Number of sites/generators | Decide whether assets are unlimited or bounded. |
| Period horizon and selected source hours | The submission horizon is the complete released half-year; confirm the selected hourly price/profile source separately. |
| Weekly submission aggregation | Decide replace-versus-accumulate policy before student release. |
| Tie breaking | Confirm deterministic team-ID ordering or choose an explicit secondary metric. |

LBNL studies show that data-center demand flexibility and large-load tariffs
are real planning considerations, but they do not establish one universal
`$/MWh` IT-service value. See [LBNL data-center demand-response field study](https://eta.lbl.gov/publications/demand-response-opportunities-and) and [LBNL large-load rate-design brief](https://datacenters.lbl.gov/publications/electricity-rate-designs-large-loads).

## Release gate

Before publishing the student rules:

1. decide whether the teaching release should use this DAM vector or a
   multi-day historical RTM/DAM aggregate;
2. select and document candidate generator technologies;
3. review the annualized combustion-turbine anchor and horizon weighting;
4. review the `$50,000/site` instructional proxy and storage coefficients;
5. replace the repeated compact teaching profile with an approved hourly
   price/value series if one is available;
6. run a parameter sweep over IT value, price, generator cost, CAPEX, storage
   cost, site cost,
   and load limits;
6. accept only a configuration with meaningful feasible/infeasible separation
   and no single cost coefficient dominating all feasible scores.
