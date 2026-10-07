# Instructor CSV Batch Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic instructor CLI that validates a directory of student CSV submissions, isolates invalid or batch-blocking teams, evaluates valid teams with the existing Zenodo-backed DCOPF, and writes ranked/audited outputs.

**Architecture:** Move the batch orchestration currently in `tools/zenodo_texas/batch_runner.py` into a first-class `ercot_game.batch_evaluation` module. Keep the existing CSV parser, plan adapter, and DCOPF solver as authorities; retain the old tool module as a compatibility re-export. Add a dedicated `ercot-game-batch` entry point that performs deterministic discovery, failure isolation, scoring, and output writing.

**Tech Stack:** Python 3.11+, dataclasses, standard-library CSV/JSON/hashlib/pathlib, existing `highspy` DCOPF adapter, pytest.

---

### Task 1: Establish the batch domain types and deterministic submission collection

**Files:**
- Create: `src/ercot_game/batch_evaluation.py`
- Modify: `src/ercot_game/csv_submission.py`
- Create: `tests/test_batch_evaluation.py`

- [ ] **Step 1: Write tests for deterministic discovery and per-file isolation**

Add tests that create a temporary submission directory containing `b.csv`,
`a.csv`, and one malformed CSV. Assert that discovery reads files in sorted
filename order, valid submissions are returned sorted by declared `team_id`,
and the malformed file produces a rejected record without raising out of the
batch collector.

The test should assert a rejected record has:

```python
assert rejected.valid is False
assert rejected.failure_reason
assert rejected.path == malformed_path
```

- [ ] **Step 2: Run the new test and verify the expected failure**

Run:

```bash
pytest -q tests/test_batch_evaluation.py -k discovery
```

Expected: failure because `ercot_game.batch_evaluation` and the batch
collection API do not yet exist.

- [ ] **Step 3: Add immutable batch collection types and collection logic**

Implement in `src/ercot_game/batch_evaluation.py`:

```python
@dataclass(frozen=True)
class SubmissionRecord:
    path: Path
    team_id: str
    submission_id: str | None
    submission: CSVSubmission | None
    valid: bool
    failure_reason: str | None

@dataclass(frozen=True)
class BatchCollection:
    accepted: tuple[SubmissionRecord, ...]
    rejected: tuple[SubmissionRecord, ...]

def collect_csv_submissions(
    directory: str | Path,
    *,
    region_to_source_bus: Mapping[str, str],
    horizon: int,
    default_generator_cost_per_mwh: float,
) -> BatchCollection:
    ...
```

The function must:

- reject a missing/non-directory path with `ValueError`;
- select only `.csv` files;
- sort paths by filename before reading;
- catch `OSError`, `UnicodeDecodeError`, and `ValueError` per file;
- derive an unparsed team ID as `UNPARSED::<filename>` when the CSV cannot
  provide one;
- reject duplicate declared team IDs while retaining every involved file in
  the rejected records;
- sort accepted records by `team_id` before returning them.

Do not change the existing `CSV_COLUMNS` contract or permit storage values.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest -q tests/test_batch_evaluation.py -k discovery
```

Expected: PASS.

---

### Task 2: Implement joint evaluation and failure isolation

**Files:**
- Modify: `src/ercot_game/batch_evaluation.py`
- Modify: `tools/zenodo_texas/plan_adapter.py:125-197`
- Modify: `tests/test_batch_evaluation.py`
- Modify: `tests/test_zenodo_batch_runner.py`

- [ ] **Step 1: Write tests for all failure-isolation branches**

Add tests using a small deterministic fake dispatch function or a monkeypatch
around `evaluate_plans_with_prepared_dcopf` with this behavior:

```python
def fake_joint_dispatch(artifact_dir, plans, *, period_indices):
    ids = tuple(sorted(plan.team_id for plan in plans))
    if ids == ("team-a", "team-b"):
        raise DCOPFInfeasible("synthetic joint overload")
    return feasible_dispatch_for(ids)
```

Assert that:

1. a feasible joint set receives `competition_scope == "joint"`;
2. when removing `team-a` restores feasibility, `team-a` receives the
   configured infeasible score and `team-b` is scored jointly;
3. when no two-team subset is feasible, valid teams are evaluated individually
   and the run reports `competition_scope == "individual_fallback"`;
4. a malformed CSV receives a rejected record and does not enter the solver;
5. the old all-teams-infeasible behavior is no longer expected.

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
pytest -q tests/test_batch_evaluation.py tests/test_zenodo_batch_runner.py
```

Expected: failure in the new failure-isolation assertions and the existing
joint-infeasibility expectation.

- [ ] **Step 3: Add explicit evaluation metadata types**

Extend the first-class module with:

```python
@dataclass(frozen=True)
class TeamScore:
    team_id: str
    rank: int
    valid: bool
    feasible: bool
    score: float
    served_load_mwh: float
    it_value: float
    energy_cost: float
    generator_operating_cost: float
    generator_capital_cost: float
    site_cost: float
    competition_scope: str
    failure_reason: str | None = None

@dataclass(frozen=True)
class FailureIsolationEvent:
    attempted_team_ids: tuple[str, ...]
    removed_team_id: str | None
    outcome: str
    reason: str

@dataclass(frozen=True)
class BatchEvaluation:
    rules_version: str
    competition_scope: str
    input_sha256_by_team: dict[str, str]
    team_scores: tuple[TeamScore, ...]
    rejected_submissions: tuple[SubmissionRecord, ...]
    isolation_events: tuple[FailureIsolationEvent, ...]
    dispatch: BatchDispatchResult | None
    failure_reason: str | None = None
```

Use `competition_scope` values only from `{"joint", "individual_fallback", "not_evaluated"}`.

- [ ] **Step 4: Implement subset evaluation and deterministic isolation**

Implement a private helper that evaluates a non-empty tuple of valid plans and
returns either `BatchDispatchResult` or the original `DCOPFInfeasible` reason.

Implement `evaluate_csv_batch` with this exact order:

1. collect submissions;
2. create zero-score rejected records for malformed files;
3. evaluate all accepted plans jointly;
4. on joint infeasibility, try accepted plans with each team removed in sorted
   team-ID order;
5. select the first removal that succeeds;
6. score the remainder jointly and mark the removed team infeasible;
7. if no removal succeeds, evaluate every accepted plan independently;
8. combine valid scores and rejected scores;
9. rank feasible valid teams first by descending score and ascending team ID,
   then infeasible/rejected records by ascending team ID;
10. assign one-based ranks to the final ordered output.

The existing score formula remains:

```python
score = it_value - energy_cost - generator_operating_cost \
        - generator_capital_cost - site_cost
```

Do not add curtailment, load shedding, or storage dispatch.

- [ ] **Step 5: Update plan-adapter documentation and preserve compatibility**

Change the joint adapter docstring so it states that `DCOPFInfeasible` is
expected by the batch orchestrator and does not imply that every team is
automatically scored infeasible. Keep the function signature unchanged.

Change `tools/zenodo_texas/batch_runner.py` to re-export the first-class
symbols from `ercot_game.batch_evaluation`, retaining imports used by existing
tests and scripts.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest -q tests/test_batch_evaluation.py tests/test_zenodo_batch_runner.py
```

Expected: PASS.

---

### Task 3: Add auditable output files and hash manifests

**Files:**
- Modify: `src/ercot_game/batch_evaluation.py`
- Modify: `tests/test_batch_evaluation.py`

- [ ] **Step 1: Write output-contract tests**

Add a test that runs a feasible two-team batch and asserts the output directory
contains exactly the required top-level files/directories:

```python
assert (out / "leaderboard.csv").exists()
assert (out / "submission_manifest.csv").exists()
assert (out / "evaluation.json").exists()
assert (out / "evaluation_sha256.txt").exists()
assert (out / "diagnostics" / "team-a.json").exists()
assert (out / "dispatch" / "period_0.json").exists()
```

Parse the JSON and assert it contains `run_id`, `rules_version`,
`input_sha256_by_team`, `competition_scope`, `isolation_events`, and
`output_sha256`.

- [ ] **Step 2: Run the output test and verify the expected failure**

Run:

```bash
pytest -q tests/test_batch_evaluation.py -k output
```

Expected: failure because only the old leaderboard/evaluation files exist.

- [ ] **Step 3: Implement canonical output writing**

Implement:

```python
def write_batch_outputs(
    evaluation: BatchEvaluation,
    output_dir: str | Path,
    *,
    scenario_version: str,
    evaluator_version: str,
    period_indices: tuple[int, ...],
) -> None:
    ...
```

Write UTF-8 CSV files with stable field order. Serialize JSON using sorted
keys, `allow_nan=False`, and a trailing newline. Include a generated run ID in
the JSON, but derive it from the canonical input/rules/period payload rather
than wall-clock time so repeat runs are byte-stable.

Write per-team diagnostics and one dispatch JSON file per evaluated period.
Include solver status, objective cost, submitted load by team, generator
dispatch by team, and binding/flow diagnostics already returned by the DCOPF
adapter.

After writing the leaderboard, submission manifest, diagnostics, and dispatch
files, calculate their SHA-256 hashes and write the sorted hash map into
`evaluation.json`. Do not include `evaluation.json` in its own hash map; instead
write its hash to a separate `evaluation_sha256.txt` file after the JSON is
complete. This avoids a self-referential hash while still making every output
artifact verifiable.

- [ ] **Step 4: Test repeat-run determinism**

Run the same evaluation twice into separate temporary output directories and
assert that `leaderboard.csv`, `submission_manifest.csv`, and the canonical
contents of `evaluation.json` match exactly after excluding only the output
directory path.

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest -q tests/test_batch_evaluation.py -k 'output or determinism'
```

Expected: PASS.

---

### Task 4: Add the instructor command-line entry point

**Files:**
- Create: `src/ercot_game/batch_cli.py`
- Modify: `pyproject.toml`
- Create: `tests/test_batch_cli.py`
- Modify: `README.md`
- Create: `docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`

- [ ] **Step 1: Write CLI contract tests**

Test these commands through `main([...])`:

```text
ercot-game-batch --help
ercot-game-batch run --submissions-dir ... --artifact-dir ... --rules ... --output-dir ... --horizon 1
```

Assert:

- missing required arguments return exit code `2`;
- a valid run returns `0`;
- a malformed submission does not make the process crash;
- invalid rules or a missing artifact return exit code `2` with a human-readable
  `error:` line on stderr.

- [ ] **Step 2: Run CLI tests and verify the expected failure**

Run:

```bash
pytest -q tests/test_batch_cli.py
```

Expected: failure because the new entry point and parser do not yet exist.

- [ ] **Step 3: Implement the CLI**

Implement `batch_cli.main` with a `run` subcommand and these required options:

```python
--submissions-dir PATH
--artifact-dir PATH
--rules PATH
--output-dir PATH
--horizon int
--period-indices TEXT
--region-map PATH
```

Load the region map from JSON, load rules through the batch evaluator, parse
period indices as non-negative comma-separated integers, invoke the batch
evaluator, write outputs, print the output directory and a one-line summary,
and return `0`. Convert expected input errors to `error: ...` and return `2`.

Add this entry point to `pyproject.toml`:

```toml
ercot-game-batch = "ercot_game.batch_cli:main"
```

- [ ] **Step 4: Document the instructor workflow**

Add to the README and create the instructor guide with:

```bash
ercot-game-batch run \
  --submissions-dir work/pilot_submissions \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_v1.json \
  --region-map data/teaching/planning_region_source_bus_map_v1.json \
  --horizon 6 \
  --period-indices 0,1,2,3,4,5 \
  --output-dir work/batch_results
```

Document that the command is instructor-side, that valid teams continue to be
scored when another team fails, that no curtailment is modeled, and that the
output directory is the source of truth for the ranking and audit record.

- [ ] **Step 5: Run CLI tests**

Run:

```bash
pytest -q tests/test_batch_cli.py
```

Expected: PASS.

---

### Task 5: Update regression coverage and examples

**Files:**
- Modify: `tests/test_zenodo_batch_runner.py`
- Modify: `tests/test_evaluation_jobs.py` only if compatibility imports require it
- Create: `examples/instructor_batch/README.md`
- Create: `examples/instructor_batch/team-a.csv`
- Create: `examples/instructor_batch/team-b.csv`

- [ ] **Step 1: Replace the old all-team failure expectation**

Change the existing infeasible-batch test so it asserts valid teams are not
all automatically assigned the infeasible score. Use one moderate and one
oversized submission, then assert the moderate team is feasible/scored and the
oversized team has the configured infeasible score when leave-one-out recovery
identifies it.

- [ ] **Step 2: Add an invalid-submission example**

Create a malformed CSV fixture with a negative load and document that it is
retained in `submission_manifest.csv` but excluded from the DCOPF.

- [ ] **Step 3: Run all batch and compatibility tests**

Run:

```bash
pytest -q tests/test_batch_evaluation.py tests/test_batch_cli.py tests/test_zenodo_batch_runner.py tests/test_evaluation_jobs.py
```

Expected: PASS.

---

### Task 6: Final verification and handoff

**Files:**
- Modify: `docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md`

- [ ] **Step 1: Run focused verification**

Run:

```bash
pytest -q tests/test_batch_evaluation.py tests/test_batch_cli.py tests/test_zenodo_batch_runner.py
```

Record the exact passing count.

- [ ] **Step 2: Run the full regression suite**

Run:

```bash
pytest -q
```

Do not claim completion if any existing regression fails. Investigate failures
as regressions unless the failure is an explicitly documented environment
limitation.

- [ ] **Step 3: Run a real prepared-artifact smoke test**

Run the documented six-period example against
`data/processed/texas_dispatch_source_v1` and inspect:

```text
work/batch_results/leaderboard.csv
work/batch_results/evaluation.json
work/batch_results/diagnostics/
work/batch_results/dispatch/
```

Verify that no output contains `NaN` or `Infinity`, that all input hashes are
present, and that the command reports the selected period mapping.

- [ ] **Step 4: Update the instructor guide with actual verification evidence**

Record the focused and full-suite test counts, the smoke-test command, and any
unverified full-horizon limitation. State explicitly that the current active
CSV schema reserves storage and that the dataset-year choice remains outside
this implementation.
