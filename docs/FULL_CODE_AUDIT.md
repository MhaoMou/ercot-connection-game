# Full Code Audit — 2026-10-05

## Scope

This audit covered the student CSV path, half-year batch evaluation, source-row
calendar mapping, DCOPF adapter, renewable availability data, team-owned
generator and storage behavior, fair continuous projection, packaging, active
instructor documentation, and the browser/service regression suite.

The audit used four independent read-only reviews followed by disjoint,
test-first corrective work. No new evaluator mathematics, network reduction, or
scoring policy was introduced.

## Corrective work completed

| Area | Status | Evidence |
|---|---|---|
| Jan–Jun / Jul–Dec source calendar | PASS | Local scoring periods are separate from source rows; Jul–Dec maps to rows 4368–8783. Regression tests pass. |
| Team-owned generators | PASS | Candidate capacity is bounded by each team’s local site load before the shared DCOPF. |
| Team-owned storage | PASS | Aggregate discharge is locally bounded; SOC uses MWh and the configured time step; idle-storage retry prevents false infeasibility. |
| Renewable dispatch policy | PASS WITH DOCUMENTED SCOPE | Solar, wind, and hydro profile files are retained in the prepared artifact, but the current no-curtailment classroom evaluator uses Zenodo nameplate limits so all source hours remain dispatchable. |
| Malformed CSV isolation | PASS | Strict parsing and `csv.Error` isolation prevent one malformed file from aborting other teams. |
| Generator catalog validation | PASS | Missing, malformed, non-finite, and negative catalog costs fail setup or per-file validation explicitly. |
| Fair continuous projection | PASS | Zero-service endpoint and a `1e-6` resolution/tolerance prevent the former `1/1024` cutoff. |
| DCOPF result/cache handling | PASS | Unrounded flow calculation, empty/infeasible/unresolved status separation, immutable cached data, and file fingerprints are covered by tests. |
| Packaging | PASS — source-checkout model | TOML parses; isolated wheel/import smoke test passed. Repository-level web/data assets remain deployment resources. |
| Active documentation/examples | PASS | Current half-year, source-offset, CSV, storage, projection, and catalog contracts are documented; placeholder IDs were removed from active examples. |
| Student manual source | PASS | `docs/student_manual/main.tex` compiled successfully after the audit. |
| Checked-in student PDF | PASS | The current source was compiled and the regenerated checked-in PDF was text- and render-verified. |
| Full regression suite | PASS | Solver-enabled audit environment: `760 passed in 107.33s`. |
| Production catalogs | PASS | Actual prepared artifact loads 2,000 bus IDs and 598 generator-cost records. |

## Findings that were fixed

1. July–December previously evaluated January source rows because the
   half-year scoring index was passed directly into the full-year demand table.
2. Student generators could export through the shared network and reduce other
   teams’ purchases even though the rules said resources were private.
3. Storage could discharge more than local load, export to another team, or
   create negative additional demand.
4. The old storage heuristic could force charging and make an otherwise
   feasible plan appear infeasible.
5. Storage SOC transitions ignored non-one-hour time steps in the public adapter.
6. Malformed or oversized CSVs could escape per-file isolation.
7. Invalid generator catalog costs could pass validation and abort a batch later.
8. Fair projection could miss feasible fractions below `1/1024` and fall back to
   order-dependent team removal.
9. Renewable hourly availability files were present in the prepared data but
   were not used by the DCOPF.
10. DCOPF flows were calculated from rounded angles, and all non-optimal solver
    statuses were reported as physical infeasibility.
11. Cached prepared data could be mutated by callers and remain stale after
    same-path artifact replacement.
12. Active examples and packaging metadata contained stale schema, horizon, or
    placeholder catalog references.
13. The production bus catalog loader incorrectly required a one-column file;
    it now accepts the prepared artifact's full bus table and extracts
    `bus_id`.

## Remaining release limitations

### Complete half-year acceptance outputs

Both complete-horizon acceptance runs completed on Electrify and their output
manifests and hashes were recorded:

```text
Jan–Jun:  4,368 hours, source rows 0..4367
Jul–Dec:  4,416 hours, source rows 4368..8783
```

The earlier July--December run produced before the source-row mapping fix is
not used.

Acceptance records:

* Jan--Jun output: `results/jan_jun_20261005`, evaluation hash
  `bca3e6d2b199e719727622f56f3cab4e4ad518d40f10e61156fa020b4981cd44`;
* Jul--Dec output: `results/jul_dec_nameplate_final`; all four test teams were
  feasible under the nameplate policy.

The Jan--Jun test batch scored all four teams. The corrected Jul--Dec batch
accepted and feasibly scored all four test teams. A separate conservative
one-team reference also scored feasibly: 4,416 MWh served and score
317,838.08.

The nameplate-policy baseline solved all 4,416 July--December periods. The
previous profile-capped result is retained only as diagnostic evidence and is
not a release result.

### Source-year wording

Active instructor and student documentation now explicitly identifies the
prepared artifact as timestamped 2016 and describes the two half-year rounds as
a teaching replay. Historical notes that mention 2028 are not part of the
active student workflow.

### P2 — browser viewport matrix was not re-measured in this code audit

The existing browser/service regression suite passes, but this audit did not
repeat manual visual checks at 1440, 1024, 768, and 390 pixels. That remains a
UX verification task rather than a dispatch-code blocker.

### P2 — repository-level deployment assets

The wheel/import smoke test passed for Python packages. The browser, prepared
data, and scenario assets remain repository-level resources and must be shipped
with the documented source-checkout deployment or packaged separately.

## Verification record

Central checks performed after integration:

```text
Focused dispatch/CSV/calendar suite: 125 passed, 2 skipped in local runtime
Post-change DCOPF/batch suite:       73 passed
Nameplate-policy focused suite:      84 passed
Baseline full repository suite:      760 passed in 107.33s with HiGHS
Direct DCOPF artifact smoke:         source rows 0, 4368, 8783 optimal
July--December nameplate baseline:   4,416 / 4,416 source periods optimal
Student manual source compilation:   success; checked-in PDF regenerated and render/text verified
TOML/package smoke test:              passed by packaging audit worker

The post-change full-suite rerun was attempted, but the sandbox denied local
socket binding for the practice-server/web-asset tests (96 errors and 6
related failures); this is an environment restriction, not a reported
application assertion failure. Those tests are covered by the earlier
solver-enabled baseline above.
```

The local-runtime skips report:

```text
No module named 'highspy'
```

## Audit decision

**RELEASE READY WITH KNOWN LIMITATIONS for code-level regression and source-
checkout integration.**

The nameplate-policy dispatch regression and complete July--December baseline
are verified. The remaining limitations are the previously documented manual
viewport matrix and repository-level deployment packaging; these are not
dispatch-correctness blockers. The checked-in PDF, half-year acceptance runs,
and source-year wording are current.
