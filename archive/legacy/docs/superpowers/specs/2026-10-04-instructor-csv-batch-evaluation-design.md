# Instructor CSV Batch Evaluation Design

**Status:** Approved design

**Date:** 2026-10-04

## Goal

Provide a deterministic instructor-side workflow that evaluates a directory of
student CSV submissions with the existing Zenodo-backed DCOPF adapter, scores
valid teams, isolates invalid or destructive submissions, and emits an auditable
leaderboard without introducing curtailment.

## Scope

This is a focused implementation of the offline instructor batch path. It does
not redesign the Planning Model, the DCOPF formulation, the browser interface,
the existing classroom workflow, or the dataset-year choice. The dispatch
horizon remains configurable so the same implementation can support pilot
horizons and future half-year blocks.

## Existing components to preserve

- `src/ercot_game/csv_submission.py` parses the established long-form CSV
  contract and converts rows to canonical `TeamPlan` objects.
- `tools/zenodo_texas/plan_adapter.py` maps canonical plans to the prepared
  Texas dispatch artifact and performs joint DCOPF evaluation.
- `tools/zenodo_texas/dcopf.py` remains the production dispatch authority.
- Existing classroom and Phase 3/4 service workflows remain unchanged.

The existing `tools/zenodo_texas/batch_runner.py` is the starting point, but it
must be hardened into a documented instructor-facing workflow.

## Architecture

```text
submission CSV files
        |
        v
deterministic discovery and per-file validation
        |-----------------------------|
        v                             v
valid plans                   rejected submissions
        |
        v
joint DCOPF evaluation
        |
        +-- feasible: score all valid teams jointly
        |
        +-- infeasible: leave-one-team-out diagnosis
                              |
                              +-- feasible remainder: score remainder jointly
                              +-- unresolved: score valid teams individually
        |
        v
leaderboard + diagnostics + immutable audit manifest
```

The batch evaluator is orchestration only. It does not duplicate the DCOPF,
network model, or browser evaluator mathematics.

## Inputs

The command accepts:

```text
--submissions-dir <directory>
--artifact-dir <prepared dispatch artifact>
--rules <scoring-rules.json>
--output-dir <results directory>
--horizon <positive integer>
--period-indices <optional comma-separated source period indices>
```

The first implementation uses directory discovery only. Discovery must remain
deterministic: files are sorted by filename before validation, and the final
accepted order is sorted by declared team ID.

The student CSV header remains:

```csv
team_id,submission_id,period,site_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh
```

Each CSV contains one team and one submission. Period values are one-based in
the student contract and must lie in `1..horizon`; source dispatch indices are
zero-based and are supplied separately through the period mapping.

Storage columns remain reserved in the active schema. Non-empty storage fields
are rejected rather than approximated. No curtailment or load-shedding fields
are added.

## Failure isolation

### Invalid submission

A CSV that fails decoding, header, schema, identifier, numeric, range, or
referential validation is excluded from the DCOPF. It receives the configured
`infeasible_score`, has `feasible=false`, and is listed after valid scored teams
with a specific `failure_reason`.

### Joint dispatch

All valid plans are first evaluated jointly. If the joint DCOPF is feasible,
all valid teams are scored in the shared network context and the run is marked
`competition_scope=joint`.

If the joint DCOPF is infeasible, the evaluator retries after removing each valid
team, in sorted team-ID order. If one or more removals restore feasibility, the
first deterministic removal is treated as the batch-blocking team:

- the removed team receives `infeasible_score`;
- the remaining valid teams are scored jointly;
- the run records the removed team, solver reason, and retry trace.

If no single removal restores feasibility, every valid team is evaluated
individually. The run is marked
`competition_scope=individual_fallback` and includes a warning that shared
competition could not be evaluated consistently.

No failure path introduces curtailment, load shedding, or integer recourse.
Submitted load remains fixed.

## Scoring

For a feasible team:

```text
score = IT value of submitted load
      - grid energy purchases
      - generator operating cost
      - generator capital cost
      - site cost
```

All quantities are computed from the evaluated dispatch and published rules.
The scoring rules file supplies the period value and energy-price vectors,
time-step duration, generator capital coefficient, site coefficient, default
generator cost, and infeasible score. The implementation validates that all
vectors cover the selected horizon and that all coefficients are finite.

Ranking is deterministic: descending score, then ascending team ID. Invalid or
infeasible teams remain visible in the leaderboard but do not displace valid
teams in the primary ranking order.

## Outputs

The evaluator writes:

```text
leaderboard.csv
submission_manifest.csv
evaluation.json
diagnostics/<team_id>.json
dispatch/period_<index>.json
```

`leaderboard.csv` contains rank, team ID, validity, feasibility, score, served
load, IT value, energy cost, generator operating cost, generator capital cost,
site cost, competition scope, and failure reason.

`evaluation.json` contains the run ID, scenario/rules/evaluator versions,
input file hashes, accepted and rejected submissions, failure-isolation trace,
subset evaluations, final ranking, solver statuses, aggregate diagnostics, and
output hashes.

The manifest records SHA-256 hashes for every input submission and generated
artifact. Repeating a run with the same inputs, rules, artifact, and period
mapping must produce the same rankings and canonical audit payload.

## Verification

Focused tests cover:

1. deterministic CSV discovery and ordering;
2. valid one-team and multi-team submissions;
3. malformed headers, missing values, negative values, unknown sites, duplicate
   keys, and mixed team IDs;
4. invalid-submission isolation;
5. jointly feasible dispatch;
6. leave-one-team-out recovery;
7. individual fallback when recovery is unresolved;
8. deterministic ranking and tie-breaking;
9. fixed-load/no-curtailment behavior;
10. generator operating and capital costs;
11. output files and audit metadata;
12. input/output hashing;
13. repeat-run determinism;
14. CLI exit codes and diagnostics.

Verification will run focused batch tests first and then the full project
regression suite. Any unavailable full-scale DCOPF or environment limitation
will be reported rather than inferred as passing.

## Explicit non-goals

- No new network reduction or Planning Model changes.
- No changes to the DCOPF equations or solver selection.
- No curtailment or integer programming.
- No storage dispatch implementation in the reserved schema.
- No dataset-year decision.
- No browser upload UI.
- No authentication, rankings service, or remote scheduler integration.
