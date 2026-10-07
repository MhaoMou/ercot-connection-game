# ACTIVSg2000 Multi-Year Dataset Migration Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with verification after each task.

**Goal:** Replace the current Zenodo/prototype data path with a validated three-year ACTIVSg2000-compatible scenario package and remove obsolete production files.

**Architecture:** Preserve the fixed 2,000-bus network structure while creating a versioned scenario package containing six half-year blocks of bus-level demand, generator availability, renewable profiles, generator costs, and branch limits. A strict validator will run hourly DCOPF checks and write a manifest; the evaluator and CSV validator will require that manifest.

**Tech Stack:** Python 3.13, CSV/JSON, existing HiGHS DCOPF adapter, pytest, SHA-256 manifests.

---

### Task 1: Inventory and define the new package contract

**Files:**
- Create: docs/ACTIVSG2000_SCENARIO_PACKAGE.md
- Create: src/ercot_game/scenario_package.py
- Test: tests/test_scenario_package.py

- [ ] Define package layout: data/processed/activsg2000_scenarios_v1/{network,years/2016,years/2017,years/2018,manifest.json}.
- [ ] Define manifest fields for topology hash, scenario hashes, year/block horizons, source provenance, and hourly validation summary.
- [ ] Implement read-only manifest validation that rejects missing files, missing hashes, failed validation, invalid horizons, and unsupported scenario versions.
- [ ] Add tests for valid, incomplete, and failed manifests.

### Task 2: Build deterministic three-year scenario generation

**Files:**
- Create: tools/activsg2000/build_scenario_package.py
- Create: tests/test_activsg2000_scenario_builder.py
- Modify: docs/ACTIVSG2000_SCENARIO_PACKAGE.md

- [ ] Extract the fixed 2,000-bus topology and generator/branch catalogs from the available compatible source archive into the new package’s network directory.
- [ ] Generate complete 2016–2018 hourly bus-level load by applying deterministic calendar-aware seasonal and daily multipliers to the fixed base demand shares.
- [ ] Generate deterministic generator-specific wind/solar availability profiles using generator technology and a fixed seeded profile process, bounded by generator nameplate.
- [ ] Generate generator availability flags and preserve fixed generator marginal costs.
- [ ] Copy fixed branch limits and record whether limits are fixed or scenario-specific.
- [ ] Write six half-year scenario blocks with exact hour counts and deterministic hashes.
- [ ] Add tests for row counts, ID coverage, bounds, determinism, and six-block completeness.

### Task 3: Add hourly DCOPF validation

**Files:**
- Create: tools/activsg2000/validate_scenario_package.py
- Create: tests/test_activsg2000_validation.py
- Modify: tools/zenodo_texas/dcopf.py or extract reusable solver input construction

- [ ] Load one hourly scenario state and construct the DCOPF inputs from the package.
- [ ] Apply generator availability and renewable upper bounds to the hourly generator set.
- [ ] Run the existing HiGHS DCOPF and record status, objective, and failure reason.
- [ ] Validate every hourly state in all six half-year blocks.
- [ ] Write an atomic manifest only when all states pass.
- [ ] Add tests using a tiny feasible fixture, a deliberately infeasible fixture, and a missing-ID fixture.
- [ ] Run a representative production validation before proceeding.

### Task 4: Integrate the evaluator and CSV checker

**Files:**
- Modify: src/ercot_game/batch_evaluation.py
- Modify: src/ercot_game/batch_cli.py
- Modify: src/ercot_game/csv_submission.py
- Modify: src/ercot_game/csv_validator.py
- Create/modify: tests/test_activsg2000_evaluator_integration.py

- [ ] Add a scenario-package argument and make the new package the only production default.
- [ ] Require a validated manifest before batch evaluation.
- [ ] Resolve bus and generator catalogs from the new package.
- [ ] Preserve scoring, storage, fair projection, malformed-file isolation, and no-curtailment behavior.
- [ ] Keep prototype compatibility only in tests during migration, not in runtime defaults.
- [ ] Add integration tests for feasible, infeasible, and unvalidated-package cases.

### Task 5: Update student/instructor documentation

**Files:**
- Modify: docs/student_manual/HYPERPARAMETERS.md
- Modify: docs/student_manual/README.md
- Modify: docs/student_manual/main.tex
- Create: docs/ACTIVSG2000_RELEASE_NOTES.md

- [ ] Remove claims that 2017/2018 zonal-load extensions are final releases.
- [ ] Describe the new scenario package, source provenance, generated-profile limitations, validation gate, and six half-year blocks.
- [ ] Update all commands and paths to the new artifact.
- [ ] Mark the package as a controlled instructional scenario, not historical ERCOT operation.
- [ ] Remove the retired six-period convention from active student-facing documentation.

### Task 6: Full regression and aggressive cleanup

**Files:**
- Delete only after reference audit: old Zenodo/prototype data, loaders, generated artifacts, obsolete rules, and Zenodo-only tests.
- Modify: .gitignore, README.md, and package exports as needed.

- [ ] Run rg to enumerate every reference to retired paths and classify each.
- [ ] Remove or replace references required by active code/tests/docs.
- [ ] Delete the explicitly approved obsolete paths one by one.
- [ ] Remove raw source archives after the new package is generated and hashed.
- [ ] Run focused tests, then the full suite.
- [ ] Run git diff --check, inspect package size and manifest hashes, and verify no old production paths remain.
- [ ] Commit and push the migration with a release note.

