# ERCOT Game

ERCOT Game is a deterministic teaching tool for data-center connection planning. Its production practice interface uses a public-data-informed Planning Model and versioned Teaching Scenario, not operating or market data.

## What is implemented

Phase 1 is the authoritative offline evaluator for canonical multi-site/multi-generator team plans and legacy single-site inputs. Phase 2 is a local, single-team browser practice interface around that evaluator. The browser validates and serializes the form, manages selection/loading/pending/result/error state, and formats server diagnostics. It does not reimplement scoring, optimization, or feasibility logic; the server remains authoritative.

Read the [Phase 1 evaluator handoff](docs/phase-1-evaluator.md) for the canonical `TeamPlan` schema, legacy normalization, allocation/scoring semantics, response field ownership, and CLI usage. Read the [Phase 2 practice guide](docs/phase-2-practice-interface.md) for the browser map, API routes, request examples, status codes, and troubleshooting.

For instructor onboarding, start with the [Instructor Repository Guide](docs/INSTRUCTOR_REPOSITORY_GUIDE.md). It explains the repository layout, environment setup, CSV checking, half-year batch evaluation, privacy-safe results publication, and data/reproducibility boundaries.

## Canonical plan and migration

Canonical plans use `connections[]` and `generators[]`, with team-level `intervention_budget_k`, `curtailment_depth_mu`, and `flexibility_fee_per_mwh`. Each connection has `connection_id`, `bus_id`, `path_corridors`, `capacity_mw`, and `profile`; each generator has `generator_id`, `connection_id`, `capacity_mw`, and `marginal_cost_per_mwh`. Legacy `bus_id`/`path_corridors`/`capacity_mw`/`profile`/`generator` input is normalized server-side to canonical arrays. See the [canonical schema and migration section](docs/phase-1-evaluator.md#canonical-teamplan).

## Production teaching scenario and map

The default practice server loads [`data/teaching/ercot_connection_scenario_v2.json`](data/teaching/ercot_connection_scenario_v2.json) together with [`data/processed/ercot_planning_model_v1.json`](data/processed/ercot_planning_model_v1.json): 12 Planning Regions, 20 Planning Interfaces, six periods, and instructional operating conditions. Public transmission and generation geography are contextual evidence; the Planning Model is not ERCOT's official electrical network model. The map-first interactions and tutorial panels are documented in the [Phase 2 map guide](docs/phase-2-practice-interface.md#scenario-fixture-and-map).

The older [`data/fixtures/ercot_small.json`](data/fixtures/ercot_small.json) fixture remains available for explicit evaluator regression/debugging and legacy compatibility tests. It is not the production default. See the [instructor release note](docs/ERCOT_INSTRUCTOR_RELEASE_NOTE.md) and [student quickstart](docs/ERCOT_STUDENT_QUICKSTART.md).

## Instructor CSV batch evaluation

Instructors can evaluate a directory of long-form student CSV submissions with
the `ercot-game-batch` command. This is an instructor-side offline workflow;
valid teams continue to be scored when another submission is malformed or
causes a joint dispatch failure. If the joint plan is infeasible, the evaluator
first attempts the documented fair continuous projection; if no common
service fraction is feasible, it proceeds through deterministic isolation
fallbacks. The dispatch path models fixed load and no curtailment. The output
directory is the source of truth for the ranking and audit record.

```bash
ercot-game-batch run \
  --submissions-dir work/half_year_submissions \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_jan_jun_v1.json \
  --horizon 4368 \
  --source-period-offset 0 \
  --workers 8 \
  --projection-iterations 10 \
  --output-dir work/batch_results_jan_jun
```

For July--December, use the second rules file, local scoring periods
`0..4415`, and source rows `4368..8783`:

```bash
ercot-game-batch run \
  --submissions-dir work/half_year_submissions \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --rules data/teaching/dispatch_scoring_rules_jul_dec_v1.json \
  --horizon 4416 \
  --source-period-offset 4368 \
  --workers 8 \
  --projection-iterations 10 \
  --output-dir work/batch_results_jul_dec
```

Canonical student files identify Zenodo source buses directly with `bus_id`.

The prepared Zenodo demand artifact is timestamped 2016. Course rounds use its
two contiguous calendar halves as a teaching replay; the data are not a 2028
forecast.
The generator ID must come from the prepared artifact's
`generator_limits.csv`; its marginal operating cost is taken from that
catalog. For production runs, every bus appearing in a CSV must have one row
for every period in the selected horizon; partial pilot files are rejected.
The submission horizon is six months at one-hour resolution: 4,368 hours for
January--June and 4,416 hours for July--December. Private generators and
storage are owned by the submitting team, and storage capital/operating costs
are included in the score.

See the [instructor batch evaluation guide](docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md)
for the input contract, failure isolation behavior, and output artifacts.

## Quick start

Python 3.11 or newer is required. From this directory:

```bash
PYTHONPATH=src python -m ercot_game.practice_server --scenario data/fixtures/ercot_small.json --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> after the server starts. An installed checkout may use:

```bash
ercot-game-practice --scenario data/fixtures/ercot_small.json --host 127.0.0.1 --port 8000
```

The supported full-application mode is a source checkout: browser assets,
teaching/scoring JSON, and the prepared Zenodo artifact are repository-level
resources and are not bundled into the wheel. A package installation can be
used for the Python runtime, but run browser and batch commands from the
checkout (or keep the checkout on `PYTHONPATH`, for example
`PYTHONPATH=src:. python -m ercot_game.batch_cli`).

The evaluator CLI and verification commands are in the [Phase 1 handoff](docs/phase-1-evaluator.md#commands-and-verification). Run the full suite with `pytest -q`.

## Practice API at a glance

| Route | Behavior |
| --- | --- |
| `GET /api/health` | Returns evaluator status and version. |
| `GET /api/scenario` | Returns the teaching fixture, map metadata, zones, and tutorial hints. |
| `GET /api/scenario?period=N` | Returns the selected zero-based period; strict query rules apply. |
| `POST /api/evaluate` | Accepts canonical or complete legacy `{"plan": {...}}` and returns the authoritative result. |
| `GET /`, `GET /styles.css`, `GET /app.js` | Serves the local practice browser interface. |
| `GET /results`, `GET /results.js` | Serves the read-only sanitized results viewer. |

Success is `200`; malformed/missing input or an invalid period is `400`; oversized bodies are `413`; invalid plans/evaluation inputs are `422`; unknown routes are `404`; unexpected failures are safe `500` responses with a request ID. See the [full API contract](docs/phase-2-practice-interface.md#api-routes-and-query-syntax).

## Practice-only boundary

This is not a production service, official ERCOT tool, market simulator, or operational decision system. It has no authentication, persistence, deadlines, rankings, instructor control plane, remote execution, or Gymnasium/RL wrapper, and it does not submit plans to ERCOT or Electrify. Future multi-team and research work is described in the [Phase 2 handoff](docs/phase-2-handoff.md).

## Phase 3 local classroom service

Phase 3 adds the local multi-team classroom service described in the [Phase 3
service guide](docs/phase-3-multiteam-service.md). It uses one Python process,
SQLite persistence, round-scoped student/instructor sessions, mutable drafts,
immutable idempotent submissions, deadline/lock transitions, joint canonical
evaluation, instructor publication/retraction, visibility filtering, and
replayable audit bundles. The Phase 1 evaluator remains authoritative: shared
resources are allocated in canonical `(connection_id, team_id)` order, invalid
official plans receive zero revenue, and rankings are deterministic and
versioned.

The classroom runbook is: create a versioned round and register teams, issue
scoped sessions, open the round, collect drafts/submissions, explicitly lock
at the UTC deadline, evaluate the complete snapshot, inspect/replay the audit
artifact, publish, and back up the SQLite file. A rejected late submission
does not automatically lock the round. Retract rather than mutate a published
result when an instructor finds a material problem; successful evaluation
retries reuse the stored run and audit artifact.

Round setup is exposed through `POST /api/instructor/rounds`. It is a global
instructor setup capability authenticated with any instructor bearer session;
students are rejected. The JSON payload is `{round_id, policy, teams,
optional clone_from}`. New rounds start in `draft`; cloning copies the source
policy and team memberships unless explicit policy/team overrides are given,
without copying submissions or results. Success is `201`; malformed input,
authentication, authorization, missing clone sources, and duplicate IDs use
structured `400`/`401`/`403`/`404`/`409` errors with request IDs.

Published visibility is policy-controlled: `private` shows a student only its
own result, `public` shows published ranking fields to authenticated round
participants, and `aggregate` exposes only the supported aggregate count.
No visibility mode exposes another team’s plan or private diagnostics. After
retraction, affected students, other students, and instructors all receive a
hidden empty leaderboard in every mode; instructors retain audit/results
access to the persisted evaluation.

The Task 7 acceptance workflow creates four independent weekly rounds and team
registrations in SQLite, then exercises the round workflow over HTTP: opening,
scoped sessions, draft save/read, immutable submission and retry, authorization,
deadline rejection, evaluation, pre-publication empty leaderboards for the two
valid student participants and the instructor, publication, visibility, audit
replay, and retraction. Deadline movement,
SQLite close/reopen, and persistence inspection are direct service-control
steps; they are distinct from the per-round HTTP operations. After restart it
uses a new HTTP server on the same database to verify round state, submission
receipts, public/aggregate/private visibility, instructor audit access,
replayed ranked results, retraction behavior, and persisted input/output
hashes, including the fetched audit bundle input hash. The determinism check
compares complete forward/reverse evaluation payloads, not only rankings or
hashes. It also verifies that affected students, other students, and
instructors see hidden leaderboard data after retraction while instructor
audit/results remain available.

This remains a local teaching service, not an official ERCOT interface,
operational dispatch system, market simulator, or production identity service.
Electrify execution and Gymnasium/RL adapters remain future boundaries.
