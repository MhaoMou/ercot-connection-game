# Zenodo-Only Repository Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository’s supported product exclusively the Zenodo-derived, approximately 2,000-bus CSV submission evaluator with DCOPF dispatch and scoring, removing the obsolete browser/practice design and its terminology.

**Architecture:** Keep the current batch boundary: a canonical long-form CSV is validated against `bus.csv` and `generator_limits.csv`, converted to canonical team/site/generator/storage records, evaluated by `tools.zenodo_texas`, and scored by `src/ercot_game.batch_evaluation`. Replace the compatibility-heavy domain model with only the fields consumed by that path. Remove the old six-period browser/practice service, web assets, fixture data, and tests that exercise that retired product.

**Tech Stack:** Python 3.11+, `highspy`, pytest, setuptools, JSON/CSV artifacts, Markdown documentation.

---

### Task 1: Lock the Zenodo-only contract with focused tests

**Files:**
- Create: `tests/test_zenodo_only_contract.py`
- Modify: `tests/test_zenodo_adapter_contract.py`
- Modify: `tests/test_batch_evaluation.py`

- [ ] **Step 1: Add tests asserting canonical model fields only**

The test must construct `ConnectionPlan`, `GeneratorPlan`, `StoragePlan`, and `TeamPlan` using only source-bus, capacity/profile, generator, and storage fields, and assert the removed webpage-era names are not dataclass fields or serialized outputs.

- [ ] **Step 2: Add tests for complete-horizon CSV evaluation**

Use the existing prepared-artifact fixtures and assert that a valid CSV produces a team score containing IT value, energy cost, site cost, generator capital/operating costs, and storage capital/operating costs.

- [ ] **Step 3: Run the focused tests and confirm they fail against the compatibility model**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_zenodo_only_contract.py
```

Expected: failure because the current model still exposes legacy fields.

### Task 2: Replace the compatibility-heavy domain model

**Files:**
- Modify: `src/ercot_game/models.py`
- Modify: `src/ercot_game/__init__.py`
- Modify: `src/ercot_game/csv_submission.py`
- Modify: `src/ercot_game/batch_evaluation.py`
- Modify: `tools/zenodo_texas/plan_adapter.py`
- Test: `tests/test_zenodo_only_contract.py`

- [ ] **Step 1: Define only canonical records**

Use these field sets:

```python
ConnectionPlan(connection_id, bus_id, capacity_mw, profile)
GeneratorPlan(generator_id, connection_id, capacity_mw, marginal_cost_per_mwh)
StoragePlan(storage_id, connection_id, power_mw, energy_mwh)
TeamPlan(team_id, connections, generators, storages)
```

No compatibility constructor, `path_corridors`, intervention budget, curtailment depth, flexibility fee, legacy single-site aliases, or abstract `Scenario` types remain in the production model.

- [ ] **Step 2: Remove no-op corridor and legacy parameter propagation**

Update source-index remapping and fair projection to reconstruct canonical connections and team plans without webpage-era fields.

- [ ] **Step 3: Update CSV conversion to construct the canonical model directly**

The CSV remains the sole student input contract; its location column is `bus_id`, and storage/generator fields remain the only optional site-owned assets.

- [ ] **Step 4: Run the focused Zenodo tests and fix failures**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_zenodo_only_contract.py tests/test_csv_submission.py tests/test_csv_validator.py tests/test_batch_evaluation.py tests/test_zenodo_adapter_contract.py tests/test_zenodo_dcopf.py
```

### Task 3: Remove the retired browser/practice product surface

**Files:**
- Delete: `web/`
- Delete: `src/ercot_game/practice_server.py`, `practice_serialization.py`, `cli.py`, `evaluator.py`, `io.py`, `validate.py`, `allocation.py`, `recourse.py`, `scoring.py`, `multiteam.py`, `auth.py`, `round_models.py`, `round_store.py`, `evaluation_jobs.py`, `remote_jobs.py`, `results_artifacts.py`, and `planning_adapter.py`
- Delete: legacy browser/practice fixtures and phase 1–3 tests that only cover the retired service
- Modify: `pyproject.toml`

- [ ] **Step 1: Remove practice/browser entry points and package declarations**

Retain only `ercot-game-batch` and `ercot-game-check-csv` console commands and the `tools.zenodo_texas` package.

- [ ] **Step 2: Delete obsolete web assets and abstract scenario fixtures**

Do not delete Zenodo raw/prepared artifacts, scoring rules, submission examples, or the DCOPF adapter.

- [ ] **Step 3: Run import and package checks**

Run:

```bash
PYTHONPATH=src python -c "import ercot_game, ercot_game.batch_cli, ercot_game.csv_validator; import tools.zenodo_texas"
```

### Task 4: Rewrite active documentation around the current game

**Files:**
- Modify: `README.md`
- Modify: `docs/INSTRUCTOR_REPOSITORY_GUIDE.md`
- Modify: `docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`
- Create: `docs/ZENODO_GAME_ARCHITECTURE.md`
- Create: `docs/LEGACY_PRODUCT_REMOVAL.md`

- [ ] **Step 1: Describe the current pipeline explicitly**

Document:

```text
Zenodo Texas dispatch artifact (~2,000 buses)
    -> canonical student CSV
    -> DCOPF dispatch
    -> fair continuous projection if the joint plan is infeasible
    -> team score and ranking
```

- [ ] **Step 2: Remove legacy webpage terminology from active documentation**

Do not describe browser tabs, teaching regions/interfaces, `K`, `μ`, flexibility fees, path corridors, or the old six-period scenario as active features.

- [ ] **Step 3: Add a terminology guard test**

The test scans active README/docs/scripts/source paths and fails if retired field names occur outside the explicit migration/removal note.

### Task 5: Full regression and repository audit

**Files:**
- Modify: `tests/test_documentation.py`
- Modify: `tests/test_reproducibility.py`

- [ ] **Step 1: Run all retained tests**

Run:

```bash
PYTHONPATH=src pytest -q
```

- [ ] **Step 2: Run legacy-term and import audits**

Run:

```bash
grep -RInE --exclude-dir=.git --exclude-dir=__pycache__ 'intervention_budget_k|curtailment_depth_mu|flexibility_fee_per_mwh|path_corridors' README.md docs src tools scripts tests
```

Expected: no matches in active product code, active documentation, or retained tests; any intentional historical note must be clearly labeled and excluded by the guard test.

- [ ] **Step 3: Verify the instructor workflow end to end**

Run CSV validation on a complete generated submission, execute a small batch with the Zenodo artifact, and confirm the score output has the generator/storage cost components.

- [ ] **Step 4: Report retained historical material separately**

The final report must list any archived historical documents or fixtures retained for provenance and confirm they are not packaged, imported, or presented as the current product.
