# Full Code Audit Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven development to implement this plan task-by-task, with review between tasks.

**Goal:** Correct the confirmed release-blocking defects found by the full audit without changing the agreed DCOPF scoring model or student-facing game rules.

**Architecture:** Keep calendar/scoring periods separate from source-artifact rows; make team-owned resources local by construction; make storage scheduling conservative and physically bounded; isolate malformed submissions; then harden packaging, docs, and release tests. Existing public-network data, evaluator mathematics, and half-year scoring coefficients remain unchanged unless a test demonstrates a correctness defect.

**Tech Stack:** Python 3.11, pytest, HiGHS/highspy, setuptools, LaTeX/Tectonic.

---

### Task 1: Establish audit regression fixtures

**Files:**
- Modify: `tests/test_batch_evaluation.py`
- Modify: `tests/test_zenodo_adapter_contract.py`
- Modify: `tests/test_zenodo_dcopf.py`
- Modify: `tests/test_csv_submission.py`
- Create: `tests/test_release_audit_regressions.py`

- [ ] Add failing tests for Jul–Dec source-row mapping, private generator export, aggregate storage discharge, forced-charge fallback, malformed oversized CSV isolation, and projection behavior below the old `1/1024` threshold.
- [ ] Run only the new tests and confirm each fails for the currently observed reason.
- [ ] Keep all fixtures small and in-memory except one artifact-header fixture that verifies source timestamps at rows 4368 and 8783.

### Task 2: Separate scoring-period indices from source-artifact indices

**Files:**
- Modify: `src/ercot_game/batch_evaluation.py`
- Modify: `src/ercot_game/batch_cli.py`
- Modify: `tools/zenodo_texas/plan_adapter.py`
- Modify: `tools/zenodo_texas/batch_runner.py`
- Modify: `tests/test_batch_cli.py`
- Modify: `tests/test_batch_evaluation.py`

- [ ] Add an explicit `source_period_indices` sequence to the dispatch boundary while retaining local `period_indices` for scoring vectors and output ordering.
- [ ] Add CLI `--source-period-offset` with validated values `0` or `4368`; default it from the selected half-year (`horizon=4368` uses `0`, `horizon=4416` uses `4368`) only when the caller has not supplied explicit source indices.
- [ ] Pass local periods to scoring and source periods to `solve_prepared_period`; record both in audit output.
- [ ] Reject mismatched index lengths, duplicate indices, and source indices outside the artifact horizon with actionable messages.
- [ ] Add calendar-alignment tests proving Jul–Dec begins at source row 4368 and ends at 8783.

### Task 3: Enforce team ownership for generators and storage

**Files:**
- Modify: `tools/zenodo_texas/plan_adapter.py`
- Modify: `tests/test_zenodo_adapter_contract.py`
- Modify: `tests/test_zenodo_dcopf.py`

- [ ] Build per-team, per-bus net load before constructing student generator candidates.
- [ ] Cap the combined candidate capacity at each team-owned bus to that team’s local net load; allocate the cap deterministically across that team’s generators so a generator cannot export to background demand or another team.
- [ ] Build storage schedules per team and bus; cap total discharge at that team’s local load and never permit negative additional demand.
- [ ] Preserve generator dispatch and storage accounting fields in both joint and individual/fallback results.
- [ ] Add tests where a generator or battery would otherwise supply another team and assert that the shared network must still serve that other team.

### Task 4: Make storage scheduling physically safe and time-step aware

**Files:**
- Modify: `tools/zenodo_texas/plan_adapter.py`
- Modify: `tests/test_zenodo_adapter_contract.py`

- [ ] Pass `time_step_hours` into `_storage_schedule` and update SOC in MWh as `(charge_mw - discharge_mw) * time_step_hours`.
- [ ] Preserve initial and terminal SOC of at least `0.5 * B`, power limits, energy limits, and no simultaneous charge/discharge.
- [ ] Do not force charging merely because a period is below the median. If a proposed storage schedule makes dispatch infeasible, retry the same plan with idle storage before reporting physical infeasibility.
- [ ] Ensure all storage discharge is bounded by local residual load and aggregate storage at a site.
- [ ] Make single-plan `submitted_load_mw` match batch accounting by excluding storage activity from computational load totals.

### Task 5: Apply renewable availability profiles

**Files:**
- Modify: `tools/zenodo_texas/dcopf.py`
- Modify: `tools/zenodo_texas/prepare_dispatch.py`
- Modify: `tests/test_zenodo_dcopf.py`
- Modify: `tests/test_zenodo_dispatch_preparation.py`

- [ ] Load normalized hourly `solar.csv`, `wind.csv`, and `hydro.csv` profile columns into the prepared artifact, keyed by source generator ID.
- [ ] For renewable units, set each period’s upper bound to `min(nameplate_p_max, hourly_profile_value)`; retain nameplate limits for technologies without a profile.
- [ ] Validate profile row counts and timestamps against the demand artifact during preparation; fail preparation with a clear message if they disagree.
- [ ] Add a regression test that a zero solar profile produces zero solar dispatch even when nameplate capacity is positive.

### Task 6: Isolate malformed submissions and harden catalog validation

**Files:**
- Modify: `src/ercot_game/csv_submission.py`
- Modify: `src/ercot_game/csv_validator.py`
- Modify: `src/ercot_game/batch_evaluation.py`
- Modify: `src/ercot_game/batch_cli.py`
- Modify: `tests/test_csv_submission.py`
- Modify: `tests/test_csv_validator.py`
- Modify: `tests/test_batch_evaluation.py`

- [ ] Use strict CSV readers and catch `csv.Error` in identity reading, submission parsing, collection, validation, and CLI boundaries.
- [ ] Reject malformed quoting and oversized fields as per-file validation failures.
- [ ] Require finite, non-negative generator catalog costs; treat a missing or unreadable production catalog as a batch setup error rather than silently weakening membership checks.
- [ ] Keep one malformed file from preventing valid teams from being evaluated, and add tests for oversized fields, malformed quotes, `NaN` costs, and missing catalogs.

### Task 7: Make fair projection total and auditable

**Files:**
- Modify: `src/ercot_game/batch_evaluation.py`
- Modify: `tests/test_batch_evaluation.py`
- Modify: `docs/student_manual/main.tex`
- Modify: `docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`

- [ ] Explicitly evaluate the zero-service endpoint and define the minimum positive service tolerance used by the evaluator.
- [ ] Increase or tolerance-control bisection iterations so a feasible positive fraction below `1/1024` is not silently discarded.
- [ ] Remove or clearly label any legacy order-dependent team-removal fallback; it must not be presented as fair continuous projection.
- [ ] Make projection failures and the applied service fraction visible in audit output and consistent across manual and instructor documentation.

### Task 8: Correct DCOPF result handling and cache boundaries

**Files:**
- Modify: `tools/zenodo_texas/dcopf.py`
- Modify: `tests/test_zenodo_dcopf.py`

- [ ] Compute reported branch flows from unrounded solver angles, then round only serialized output.
- [ ] Distinguish feasible empty models, physical infeasibility, and unresolved solver errors instead of mapping all nonoptimal statuses to `DCOPFInfeasible`.
- [ ] Prevent callers from mutating cached prepared artifacts; use immutable row structures or defensive copies.
- [ ] Include artifact file fingerprints in cache identity or provide an explicit cache invalidation boundary for replaced artifacts.

### Task 9: Repair packaging, fixtures, and release documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`
- Modify: `examples/instructor_batch/README.md`
- Modify: `work/pilot_submissions/README.md`
- Modify: `tests/test_documentation.py`
- Modify: `tests/test_zenodo_batch_runner.py`
- Rebuild: `docs/student_manual/main.pdf`

- [ ] Package the runtime modules and required static assets or document the supported source-checkout execution mode explicitly; add a clean-install smoke test.
- [ ] Replace placeholder generator IDs and obsolete short-horizon commands in active examples.
- [ ] Reconcile projection, storage, CSV, and half-year terminology across active manuals while preserving historical reports.
- [ ] Recompile the student manual and verify the PDF contains complete-horizon, storage-cost, checker, and projection instructions.

### Task 10: Final verification and audit report

**Files:**
- Create: `docs/FULL_CODE_AUDIT.md`
- Modify: `docs/ERCOT_RELEASE_READINESS.md`

- [ ] Run focused regression tests after each task, then the complete suite with the required localhost permission.
- [ ] Run both complete half-year acceptance evaluations with correct source calendars and record output hashes.
- [ ] Run a clean package/install smoke test and verify the browser/static workflow from the documented commands.
- [ ] Record every finding as fixed, known limitation, or release blocker; do not claim bug-free status without passing evidence.
- [ ] Stop after the audit report; any new feature or evaluator-policy change must be separately approved.
