# Phase 1 Offline Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, file-based evaluator that scores multiple weekly data-center connection plans against a small ERCOT-derived network fixture, including shared-bus allocation and flexible-curtailment recourse.

**Architecture:** Use a small Python package with immutable dataclass-based domain objects, pure evaluation functions, and JSON input/output. The Phase 1 model intentionally uses a transparent linear capacity representation: buses have time-varying headroom, lines impose shared limits, and generators reduce net load subject to capacity and cost. The evaluator processes all team submissions together, allocates shared capacity without submission-order dependence, applies bounded curtailment, and emits a complete audit record.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `json`, `hashlib`, and `argparse`; `pytest` for tests; no web framework, database, external solver, or Electrify dependency in Phase 1.

---

## Scope boundary

This plan implements only the offline evaluator. It does not implement authentication, the student web interface, a job queue, PostgreSQL, Electrify execution, AC power flow, or the Gymnasium wrapper. The evaluator must expose stable pure-Python interfaces so those components can be added later.

The fixture should be explicitly labeled as an instructional ERCOT-derived abstraction, not a production ERCOT model. It should contain a small set of named buses, shared corridors, representative hourly periods, base load, headroom, and published prices.

## File map

- Create: `pyproject.toml` — package metadata and pytest configuration.
- Create: `src/ercot_game/__init__.py` — public package exports and version.
- Create: `src/ercot_game/models.py` — domain dataclasses and enums.
- Create: `src/ercot_game/io.py` — JSON serialization, canonicalization, and SHA-256 input hashing.
- Create: `src/ercot_game/validate.py` — submission and scenario validation.
- Create: `src/ercot_game/allocation.py` — order-independent shared-bus and corridor allocation.
- Create: `src/ercot_game/recourse.py` — bounded flexible-curtailment repair.
- Create: `src/ercot_game/scoring.py` — energy, generator, flexibility, curtailment, and violation costs.
- Create: `src/ercot_game/evaluator.py` — end-to-end weekly evaluation and audit output.
- Create: `src/ercot_game/cli.py` — `validate` and `evaluate` commands for offline use.
- Create: `data/fixtures/ercot_small.json` — versioned instructional network fixture.
- Create: `examples/week_01_submissions.json` — at least three teams, including a shared-bus conflict.
- Create: `tests/test_models_and_io.py` — model round-trip and canonical hash tests.
- Create: `tests/test_validation.py` — schema and bounds tests.
- Create: `tests/test_allocation.py` — simultaneous, order-independent shared-capacity tests.
- Create: `tests/test_recourse.py` — intervention-budget and curtailment-depth tests.
- Create: `tests/test_scoring.py` — score decomposition and penalty-order tests.
- Create: `tests/test_evaluator.py` — deterministic end-to-end fixture tests.

## Domain rules for Phase 1

Use a fixed set of time slots `t = 0..T-1`. A submission contains one portfolio action for the current week:

```python
TeamPlan(
    team_id: str,
    bus_id: str,
    capacity_mw: float,
    profile: tuple[float, ...],
    generator: GeneratorPlan | None,
    intervention_budget_k: int,
    curtailment_depth_mu: float,
    flexibility_fee_per_mwh: float,
)
```

The requested load is `capacity_mw * profile[t]`. A generator contributes `min(capacity_mw, net_load)` at a fixed marginal cost for each period. A bus has available hosting headroom per period. A corridor can constrain the sum of assigned net load for all teams using that corridor.

The shared allocation rule for Phase 1 is proportional rationing. For every overloaded resource and time slot, compute:

```text
rho = min(1, available_capacity / total_requested_capacity)
allocated_capacity_i = rho * requested_capacity_i
```

To guarantee order independence, aggregate by resource before producing team allocations. If multiple resources bind, use the smallest team-specific ratio implied by the resources on that team’s path.

Flexible recourse chooses at most `K` nonzero intervention slots and never curtails more than `mu * allocated_capacity` in a slot. For Phase 1, choose the smallest curtailment needed to satisfy all remaining resource limits, prioritizing slots with the largest overload and breaking ties by time index. The algorithm must return the intervention timestamps and the exact curtailed MW in each slot.

The score is:

```text
IT value of served MWh
- grid energy cost
- generator cost
- flexibility fee
- curtailment cost
- residual unserved-energy penalty
```

All coefficients live in the fixture configuration and are echoed in the result. No random tie-breaking is permitted in official evaluation.

## Task 1: Create the package skeleton and domain model

**Files:**
- Create: `pyproject.toml`
- Create: `src/ercot_game/__init__.py`
- Create: `src/ercot_game/models.py`
- Create: `tests/test_models_and_io.py`

- [ ] **Step 1: Write failing model tests**

Test construction and equality for `GeneratorPlan`, `TeamPlan`, `Bus`, `Corridor`, `Scenario`, `EvaluationConfig`, and `EvaluationResult`. Assert that tuples are used for profiles and that a plan rejects an empty team ID only after validation, not during dataclass construction.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
pytest tests/test_models_and_io.py -q
```

Expected: collection or import failure because the package and model classes do not yet exist.

- [ ] **Step 3: Implement the minimal immutable domain model**

Use frozen dataclasses and explicit types. Include these fields:

```python
@dataclass(frozen=True)
class GeneratorPlan:
    generator_id: str
    capacity_mw: float
    marginal_cost_per_mwh: float

@dataclass(frozen=True)
class TeamPlan:
    team_id: str
    bus_id: str
    path_corridors: tuple[str, ...]
    capacity_mw: float
    profile: tuple[float, ...]
    generator: GeneratorPlan | None
    intervention_budget_k: int
    curtailment_depth_mu: float
    flexibility_fee_per_mwh: float

@dataclass(frozen=True)
class Bus:
    bus_id: str
    headroom_mw_by_time: tuple[float, ...]

@dataclass(frozen=True)
class Corridor:
    corridor_id: str
    capacity_mw_by_time: tuple[float, ...]

@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    evaluator_version: str
    buses: tuple[Bus, ...]
    corridors: tuple[Corridor, ...]
    energy_price_per_mwh: tuple[float, ...]
    it_value_per_mwh: tuple[float, ...]
    time_step_hours: float

@dataclass(frozen=True)
class EvaluationConfig:
    curtailment_cost_per_mwh: float
    unserved_penalty_per_mwh: float
    emergency_energy_cost_per_mwh: float

@dataclass(frozen=True)
class EvaluationResult:
    scenario_id: str
    input_hash: str
    team_results: tuple[dict, ...]
    aggregate_diagnostics: dict
```

Add `__all__` exports in `__init__.py` and a package version such as `0.3.0`.

- [ ] **Step 4: Run tests and commit the model layer**

Run:

```bash
pytest tests/test_models_and_io.py -q
```

Expected: PASS. Commit with:

```bash
git add pyproject.toml src/ercot_game tests/test_models_and_io.py
git commit -m "feat: add offline evaluator domain model"
```

## Task 2: Add canonical JSON I/O and validation

**Files:**
- Create: `src/ercot_game/io.py`
- Create: `src/ercot_game/validate.py`
- Modify: `tests/test_models_and_io.py`
- Create: `tests/test_validation.py`

- [ ] **Step 1: Write failing serialization and validation tests**

Cover these cases:

```python
assert load_scenario(dump_scenario(scenario)) == scenario
assert canonical_hash(payload) == canonical_hash(reordered_payload)
assert validate_plan(plan, scenario) == []
assert "capacity_mw must be nonnegative" in validate_plan(negative_plan, scenario)
assert "profile values must be in [0, 1]" in validate_plan(bad_profile, scenario)
assert "intervention_budget_k exceeds time horizon" in validate_plan(too_many_interventions, scenario)
```

Also test that validation catches unknown buses, unknown corridors, profile-length mismatch, `mu` outside `[0, 1]`, negative generator capacity, and inconsistent time-series lengths in the scenario.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_models_and_io.py tests/test_validation.py -q
```

Expected: FAIL because serialization and validation functions do not exist.

- [ ] **Step 3: Implement canonical serialization and validation**

Implement:

```python
def scenario_to_dict(scenario: Scenario) -> dict: ...
def scenario_from_dict(payload: dict) -> Scenario: ...
def plan_to_dict(plan: TeamPlan) -> dict: ...
def plan_from_dict(payload: dict) -> TeamPlan: ...
def canonical_hash(payload: dict) -> str: ...
def validate_scenario(scenario: Scenario) -> list[str]: ...
def validate_plan(plan: TeamPlan, scenario: Scenario) -> list[str]: ...
```

`canonical_hash` must JSON-encode with sorted keys and stable separators, then return a lowercase SHA-256 digest. Validation must be pure and must return deterministic, human-readable errors in a stable order.

- [ ] **Step 4: Run the tests and commit the I/O layer**

Run:

```bash
pytest tests/test_models_and_io.py tests/test_validation.py -q
```

Expected: PASS. Commit with:

```bash
git add src/ercot_game/io.py src/ercot_game/validate.py tests/test_models_and_io.py tests/test_validation.py
git commit -m "feat: add canonical evaluator input validation"
```

## Task 3: Add the versioned instructional network fixture

**Files:**
- Create: `data/fixtures/ercot_small.json`
- Create: `examples/week_01_submissions.json`
- Create: `tests/test_validation.py`

- [ ] **Step 1: Write fixture loading tests**

Load the fixture through `scenario_from_dict` and assert:

```python
scenario.scenario_id == "ercot-small-week-01"
len(scenario.buses) >= 3
len(scenario.corridors) >= 2
len(scenario.energy_price_per_mwh) == 6
validate_scenario(scenario) == []
```

Load the example submissions and assert there are at least three distinct teams and at least two teams share one bus.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_validation.py -q
```

Expected: FAIL because the fixture files do not exist.

- [ ] **Step 3: Create a small, documented fixture**

Use six representative hourly periods, three buses, two corridors, time-varying bus headroom, prices, and IT value. Include one constrained bus and one shared corridor so the example creates a meaningful conflict. Add JSON metadata fields `source_description`, `data_version`, and `model_limitations` explaining that the fixture is an educational abstraction derived from ERCOT-style data, not an official ERCOT operational model.

Create at least three plans: two plans sharing the constrained bus, one plan at another bus, and one plan using a generator. Set the two shared-bus requests high enough to trigger proportional allocation.

- [ ] **Step 4: Run fixture tests and commit**

Run:

```bash
pytest tests/test_validation.py -q
```

Expected: PASS. Commit with:

```bash
git add data/fixtures/ercot_small.json examples/week_01_submissions.json tests/test_validation.py
git commit -m "data: add small ERCOT-derived evaluator fixture"
```

## Task 4: Implement order-independent shared-resource allocation

**Files:**
- Create: `src/ercot_game/allocation.py`
- Create: `tests/test_allocation.py`

- [ ] **Step 1: Write failing allocation tests**

Test:

```python
result_a = allocate_shared_capacity(scenario, plans)
result_b = allocate_shared_capacity(scenario, tuple(reversed(plans)))
assert result_a == result_b
assert result_a["team-a"].allocated_capacity_mw == pytest.approx(60.0)
assert result_a["team-b"].allocated_capacity_mw == pytest.approx(60.0)
```

Add tests for no overload, one binding bus, one binding corridor, multiple binding resources, zero requested capacity, and deterministic time-slot handling. Verify that allocation diagnostics identify binding resources and the applied ratio.

- [ ] **Step 2: Run allocation tests and verify failure**

Run:

```bash
pytest tests/test_allocation.py -q
```

Expected: FAIL because the allocator does not exist.

- [ ] **Step 3: Implement the proportional allocator**

Define:

```python
@dataclass(frozen=True)
class AllocationResult:
    team_id: str
    allocated_capacity_mw: float
    resource_ratio_by_time: tuple[float, ...]
    binding_resources: tuple[str, ...]

def allocate_shared_capacity(
    scenario: Scenario,
    plans: tuple[TeamPlan, ...],
) -> dict[str, AllocationResult]: ...
```

Aggregate requests by bus and corridor before producing team results. Use sorted team IDs and sorted resource IDs for all iteration and tie-breaking. For each team and time slot, compute the minimum ratio across its bus and path corridors. Do not use timestamps or input list position.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
pytest tests/test_allocation.py -q
```

Expected: PASS. Commit with:

```bash
git add src/ercot_game/allocation.py tests/test_allocation.py
git commit -m "feat: add order-independent shared capacity allocation"
```

## Task 5: Implement bounded flexible-curtailment recourse

**Files:**
- Create: `src/ercot_game/recourse.py`
- Create: `tests/test_recourse.py`

- [ ] **Step 1: Write failing recourse tests**

Cover:

```python
repair = repair_with_curtailment(load_by_time, capacity_by_time, k=2, mu=0.2)
assert repair.feasible
assert len(repair.intervention_times) <= 2
assert max(repair.curtailed_mw) <= pytest.approx(0.2 * allocated_capacity)
```

Also assert that `k=0` fails when overload exists, `mu=0` cannot repair an overload, already feasible load receives zero curtailment, ties are broken by earliest time index, and an impossible repair reports residual unserved energy.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_recourse.py -q
```

Expected: FAIL because the recourse implementation does not exist.

- [ ] **Step 3: Implement deterministic minimum-curtailment repair**

Define:

```python
@dataclass(frozen=True)
class RecourseResult:
    feasible: bool
    served_mw: tuple[float, ...]
    curtailed_mw: tuple[float, ...]
    residual_unserved_mw: tuple[float, ...]
    intervention_times: tuple[int, ...]
    total_curtailed_mwh: float
    total_unserved_mwh: float

def repair_with_curtailment(
    requested_load_mw: tuple[float, ...],
    available_capacity_mw: tuple[float, ...],
    allocated_capacity_mw: float,
    k: int,
    mu: float,
    time_step_hours: float,
) -> RecourseResult: ...
```

At each slot compute overload as `max(0, requested - available)`. Rank positive overloads by descending overload then ascending time index. Select at most `k` slots and curtail no more than `mu * allocated_capacity_mw` in each selected slot. If a selected slot still has residual overload after its depth limit, report residual unserved energy. Return complete time-series vectors and never mutate inputs.

- [ ] **Step 4: Run recourse tests and commit**

Run:

```bash
pytest tests/test_recourse.py -q
```

Expected: PASS. Commit with:

```bash
git add src/ercot_game/recourse.py tests/test_recourse.py
git commit -m "feat: add bounded flexible-curtailment recourse"
```

## Task 6: Add score decomposition

**Files:**
- Create: `src/ercot_game/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Use a hand-calculated one-team case and assert every component:

```python
assert score.it_value == pytest.approx(120.0)
assert score.energy_cost == pytest.approx(40.0)
assert score.generator_cost == pytest.approx(10.0)
assert score.curtailment_cost == pytest.approx(6.0)
assert score.unserved_penalty == pytest.approx(0.0)
assert score.total == pytest.approx(64.0)
```

Test that the unserved penalty is strictly larger than curtailment cost for the same MWh, that generator dispatch cannot exceed generator capacity, and that the result includes the exact configuration coefficients.

- [ ] **Step 2: Run scoring tests and verify failure**

Run:

```bash
pytest tests/test_scoring.py -q
```

Expected: FAIL because scoring functions do not exist.

- [ ] **Step 3: Implement pure score calculation**

Define:

```python
@dataclass(frozen=True)
class ScoreBreakdown:
    it_value: float
    energy_cost: float
    generator_cost: float
    flexibility_fee: float
    curtailment_cost: float
    unserved_penalty: float
    total: float

def calculate_score(
    scenario: Scenario,
    config: EvaluationConfig,
    plan: TeamPlan,
    served_load_mw: tuple[float, ...],
    generator_dispatch_mw: tuple[float, ...],
    curtailed_mw: tuple[float, ...],
    unserved_mw: tuple[float, ...],
) -> ScoreBreakdown: ...
```

Multiply MWh quantities by `scenario.time_step_hours`. Charge grid energy only for residual grid-supplied load after generator dispatch. Charge the flexibility fee on served or contracted capacity using one documented formula, and include all terms in the output.

- [ ] **Step 4: Run scoring tests and commit**

Run:

```bash
pytest tests/test_scoring.py -q
```

Expected: PASS. Commit with:

```bash
git add src/ercot_game/scoring.py tests/test_scoring.py
git commit -m "feat: add transparent evaluator score breakdown"
```

## Task 7: Compose the deterministic evaluator and CLI

**Files:**
- Create: `src/ercot_game/evaluator.py`
- Create: `src/ercot_game/cli.py`
- Create: `tests/test_evaluator.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing end-to-end tests**

Load the fixture and example submissions, evaluate them twice, and assert:

```python
first == second
first.scenario_id == "ercot-small-week-01"
first.input_hash == canonical_hash(expected_input_payload)
len(first.team_results) >= 3
```

Assert that reversing submission order produces identical per-team scores and allocation diagnostics. Assert that the shared-bus teams receive proportional allocations and that a feasible generator-backed team has a nonnegative residual-unserved quantity of zero.

- [ ] **Step 2: Run end-to-end tests and verify failure**

Run:

```bash
pytest tests/test_evaluator.py -q
```

Expected: FAIL because the evaluator and CLI do not exist.

- [ ] **Step 3: Implement the pure evaluation pipeline**

Define:

```python
def evaluate_week(
    scenario: Scenario,
    config: EvaluationConfig,
    plans: tuple[TeamPlan, ...],
) -> EvaluationResult: ...
```

The pipeline must:

1. Validate the scenario and every plan.
2. Reject duplicate team IDs with deterministic validation errors.
3. Compute the canonical input hash from scenario, config, and sorted plans.
4. Allocate shared bus and corridor capacity jointly.
5. Dispatch each optional generator deterministically.
6. Apply bounded curtailment recourse.
7. Calculate each score breakdown.
8. Emit per-team diagnostics, aggregate binding-resource diagnostics, evaluator version, and input hash.

Use sorted team IDs when iterating. Do not mutate scenario or plan objects. If validation fails, raise a typed `EvaluationInputError` containing all stable errors rather than producing partial scores.

- [ ] **Step 4: Add CLI commands**

Implement:

```bash
python -m ercot_game.cli validate \
  --scenario data/fixtures/ercot_small.json \
  --submissions examples/week_01_submissions.json

python -m ercot_game.cli evaluate \
  --scenario data/fixtures/ercot_small.json \
  --submissions examples/week_01_submissions.json \
  --output work/week_01_results.json
```

`validate` prints deterministic errors and exits nonzero on invalid input. `evaluate` writes canonical, pretty-printed JSON with the evaluator version, scenario ID, input hash, team results, and diagnostics.

- [ ] **Step 5: Run the full test suite and commit**

Run:

```bash
pytest -q
python -m ercot_game.cli validate --scenario data/fixtures/ercot_small.json --submissions examples/week_01_submissions.json
python -m ercot_game.cli evaluate --scenario data/fixtures/ercot_small.json --submissions examples/week_01_submissions.json --output work/week_01_results.json
```

Expected: all tests pass, validation exits 0, and the output file is reproducible byte-for-byte when regenerated from the same inputs.

Commit with:

```bash
git add pyproject.toml src/ercot_game tests data/fixtures examples
git commit -m "feat: add deterministic offline competition evaluator"
```

## Task 8: Phase 1 verification and handoff artifacts

**Files:**
- Create: `README.md`
- Create: `docs/phase-1-evaluator.md`
- Create: `tests/test_reproducibility.py`

- [ ] **Step 1: Add reproducibility tests**

Run the CLI twice into two separate output paths and compare SHA-256 hashes. Also compare results after reversing the input submission order.

- [ ] **Step 2: Document the model limitations and extension boundary**

Document the JSON schema, command examples, scoring formula, proportional allocation, curtailment algorithm, evaluator versioning, and the explicit limitations: linear capacity abstraction, representative periods, no AC power flow, no stochastic scenarios, no database, and no Electrify dependency.

- [ ] **Step 3: Run final verification**

Run:

```bash
pytest -q
python -m ercot_game.cli validate --scenario data/fixtures/ercot_small.json --submissions examples/week_01_submissions.json
python -m ercot_game.cli evaluate --scenario data/fixtures/ercot_small.json --submissions examples/week_01_submissions.json --output work/week_01_results.json
```

Expected: all tests pass; CLI validation succeeds; evaluation produces a result with a stable input hash and a score breakdown for every team.

- [ ] **Step 4: Commit the Phase 1 handoff**

```bash
git add README.md docs/phase-1-evaluator.md tests/test_reproducibility.py
git commit -m "docs: verify and hand off phase 1 evaluator"
```

## Plan self-review

- Spec coverage: the plan covers deterministic evaluation, structured plans, shared-bus allocation, flexible-curtailment recourse, scoring, reproducibility, a small ERCOT-derived fixture, and the explicit Phase 1 boundary. Web, database, Electrify, and Gymnasium work remain outside this plan as required by the phase boundary.
- Placeholder scan: no `TODO`, `TBD`, or unspecified implementation steps are required; each task defines files, interfaces, tests, commands, and expected outcomes.
- Type consistency: `Scenario`, `TeamPlan`, `EvaluationConfig`, `EvaluationResult`, `AllocationResult`, `RecourseResult`, and `ScoreBreakdown` are defined before their consumers. `evaluate_week` consumes the same domain types used by allocation, recourse, and scoring.
