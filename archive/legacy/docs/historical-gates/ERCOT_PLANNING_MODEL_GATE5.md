# Gate 5 — Versioned ERCOT Planning Model Integration

Status: implementation in progress; Gate 4.6 construction is frozen.

## Architecture

Gate 5 establishes a three-layer boundary:

1. **Public Network** — the normalized public EIA/HIFLD evidence already audited in Gate 3.
2. **Planning Model** — the approved Gate 4.6 geographic abstraction, promoted as `ercot-public-derived-planning` version `1.0.0`.
3. **Teaching Scenario** — a separate versioned instructional calibration that supplies headroom, transfer capacities, prices, and evaluation configuration.
4. **existing Evaluator** — the deterministic evaluator continues to receive its existing `Scenario` object and applies the existing allocation, recourse, and scoring equations.

The adapter is the only join point between the teaching artifact and the evaluator. It maps Planning Regions to the evaluator's generic bus slots and Planning Interfaces to generic corridor slots. The visible and canonical user-facing terminology is Planning Region, Connection Region, and Planning Interface; the internal compatibility names remain only to preserve existing evaluator and API contracts.

## Evaluator compatibility decision

The evaluator is compatible with this abstraction because it models resource headroom, shared transfer capacity, multi-period profiles, recourse, and scoring; it does not solve Kirchhoff power flow, infer impedance, or require physical bus identity. A planning interface can therefore be an instructional shared-capacity resource without claiming an operational line rating. No evaluator equation, allocation rule, curtailment rule, recourse rule, or scoring rule is changed in Gate 5; the evaluator mathematics remains unchanged.

| Gate 5 concept | Existing evaluator boundary | Decision |
| --- | --- | --- |
| Planning Region | `Scenario.buses` / `bus_id` | Compatible through adapter; IDs are stable planning IDs. |
| Planning Interface | `Scenario.corridors` / `corridor_id` | Compatible as an instructional shared-capacity resource. |
| Connection Region | `ConnectionPlan.bus_id` | New external alias normalized to the planning-region ID. |
| Planning Interface selection | `ConnectionPlan.path_corridors` | New external alias normalized to planning-interface IDs. |
| Student generator | `GeneratorPlan` | Remains separate from public EIA generation evidence. |
| Teaching headroom/capacity | Scenario inputs | Separate versioned calibration artifact; not public physical ratings. |

## Versioning and migration safety

The production model is `data/processed/ercot_planning_model_v1.json`; its source is the frozen `candidate_12_v2` artifact. The teaching scenario is `data/teaching/ercot_connection_scenario_v2.json` and carries an explicit reference to the model ID and version. New plans must carry the planning plan schema and model version when the planning-facing schema is enabled. Legacy plans remain valid only through an explicit legacy path; they are not silently reinterpreted against the new model.

The old synthetic fixture remains available to tests and a non-user-facing debug path during migration. Ordinary production loading uses the versioned teaching scenario, so students do not see two competing networks.

The no-argument practice server now loads `data/teaching/ercot_connection_scenario_v2.json`; an explicit `--scenario data/fixtures/ercot_small.json` remains a legacy/debug fixture path. `/api/scenario` retains `buses` and `corridors` for compatibility, and additionally returns `planning_model`, `planning_regions`, and `planning_interfaces` with stable planning IDs.

## Calibration policy

Teaching limits are deterministic instructional values, not operational ERCOT ratings. Relative scales use audited public transmission geometry and generation evidence; explicit documented modifiers create varied headroom and a small number of teachable bottlenecks. Six period multipliers create time variation while preserving reproducibility. Public generation remains evidence for calibration only; student-owned generators are submitted in plans and evaluated independently.

## Map policy

The production map foregrounds planning regions, planning interfaces, and planning anchors. Public transmission remains contextual evidence and is visually subdued. The existing geographic projection, zoom, pan, reset, selection, Map → Plan, and Evaluation → Map contracts remain in place.

## Hard stop

The Gate 5 hard stop is intentionally conservative:

If a compatibility audit discovers that evaluator semantics require physical electrical connectivity, impedance, Kirchhoff constraints, or operational ratings that the planning abstraction does not provide, Gate 5 stops. The evaluator must not be redesigned under this gate; the incompatibility must be reported for a later model-design decision.

## Verification record

The Gate 5 focused tests cover artifact counts, version matching, provenance, the absence of teaching limits from the planning artifact, deterministic calibration metadata, and adapter conversion to the existing evaluator shape. The final verification command was `pytest -q`: **578 passed in 112.69s**. A live browser smoke check on the current code at a temporary localhost port confirmed scenario `ERCOT-PLANNING-TEACHING-V2`, 12 planning regions, 20 planning interfaces, and the planning-model layer. Full mouse/keyboard workflow coverage in the browser was not automated; the existing Python and source-contract regression suite covered those preserved behaviors.
