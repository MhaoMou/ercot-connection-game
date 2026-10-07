# Instructor Release Note

## What students are using

The application is a local, practice-only connection-planning exercise. Its production scenario is `ercot-planning-teaching-v2` (`2.0.0`) evaluated with Planning Model V1 (`1.0.0`).

| Layer | Meaning | Status |
| --- | --- | --- |
| Public Network | Public transmission and generation geography plus source-derived attributes used as geographic context | Public-data-derived context; not the evaluator network |
| Planning Model | 12 derived Planning Regions and 20 derived Planning Interfaces | Versioned reduction for teaching; not ERCOT’s official electrical model |
| Teaching Scenario | Headroom, transfer limits, prices, loads, costs, and evaluation conditions | Instructional assumptions for the exercise |

Public transmission geography is derived from public U.S. government datasets, including HIFLD transmission geography and EIA Form 860 generation context. The Planning Model is a reduced geographic abstraction and must not be presented as an ERCOT endorsement, operating model, interconnection study, or planning recommendation.

Students build one or more connection sites, select Planning Regions and optional Planning Interfaces, specify profiles, optionally attach generators, and run practice evaluations. The evaluator is authoritative for the displayed score and diagnostics. Feasibility and binding-resource explanations are intended for learning, not dispatch or market decisions.

For the classroom service, retain the Planning Model version, Teaching Scenario version, and plan schema version with every stored submission. Do not silently reinterpret historical submissions after changing a scenario; create a new versioned round instead.

See [the student quickstart](ERCOT_STUDENT_QUICKSTART.md), [the planning-model report](ERCOT_PLANNING_MODEL_GATE5.md), and [the Gate 5.5 calibration audit](ERCOT_TEACHING_SCENARIO_AUDIT.md) for supporting detail.

## Published results viewer

After an instructor-side evaluation round is complete, publish only a
sanitized results package to the read-only `/results` route. The browser
visualization is an explanation and inspection aid; it is not a second
evaluator and must not recompute dispatch, feasibility, projection, or score.
The evaluator-authoritative output remains the source of truth for all
numerical results and diagnostics. The browser viewer does not recompute the
evaluation.

Build the package from the prepared public-network artifact, the authoritative
evaluation output, and the selected team identifier:

```text
PYTHONPATH=src python scripts/build_results_package.py \\
  --network PATH/TO/public_network.json \\
  --evaluation PATH/TO/evaluation.json \\
  --team TEAM_ID \\
  --output-dir web/data/results
```

The builder emits four browser-facing JSON artifacts under the versioned
`results.v1` contract:

| Artifact | Purpose |
| --- | --- |
| `round_metadata.json` | Round, horizon, scenario, and publication metadata |
| `public_network.json` | Public buses, branches, coordinates, and map attributes |
| `team_report.json` | The selected team's score, plan consequences, and diagnostics |
| `aggregate_grid_summary.json` | Privacy-preserving system-level summaries |

The package has a strict selected-team-only privacy boundary. It must not
contain raw submissions, joint CSV files, other teams' plans, cross-team
identifiers, or unredacted instructor audit bundles. The aggregate suppression
rule publishes information only when it has at least three verified contributing teams; smaller groups are suppressed even if an input file declares a larger team count.

The `/results` page may show the public network, the selected team's
resources, and suppressed aggregate stress summaries. It is browser
visualization only: the evaluator-authoritative score and diagnostics are
computed before publication and loaded as sanitized artifacts. Instructors
should inspect the generated package before serving it and should never copy
raw batch-evaluation directories into `web/data/results`.
