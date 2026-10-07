# ERCOT Gate 5.5 End-to-End QA Report

Date: 2026-09-30  
Scenario: `ercot-planning-teaching-v2` / `2.0.0`  
Planning model: `ercot-public-derived-planning@1.0.0`

## Final status

**PASS** for the Gate 5.5 acceptance scope. No Teaching Scenario V2 calibration changes were required. Planning Model V1 regionalization, the 20 planning interfaces, and evaluator mathematics were not modified.

## Live browser workflow

Verified against the running local practice interface at `http://127.0.0.1:8000/`:

1. Scenario loads as `ERCOT-PLANNING-TEACHING-V2` with six periods.
2. The Network section identifies the `ERCOT PLANNING MODEL`.
3. Public transmission, Planning Model, and Generation layers are present and independently controllable.
4. The geographic map renders 12 planning regions, 20 planning interfaces, 634 public transmission geometries, and 279 county-boundary paths.
5. Keyboard activation selects a planning region and opens a provenance-separated inspector.
6. Keyboard activation selects a planning interface and opens a provenance-separated inspector.
7. A connection site can be created from the plan editor; Planning region and Planning interfaces terminology is shown in Planning Model mode.
8. A five-MW optional generator can be added and attached to the connection site.
9. A 20-MW plan evaluates as feasible with a live result of `$9,200`.
10. The same plan at 80 MW evaluates as infeasible and reports `bus:PANHANDLE`, residual unserved energy, and the negative score.
11. Binding-resource links navigate back to the selected planning region and preserve the evaluator binding state.

## Provenance and terminology audit

The inspector now separates:

- `PUBLIC-DERIVED / PLANNING CONTEXT`: public transmission geometry, length, plant counts, and public crossing evidence;
- `TEACHING SCENARIO`: instructional headroom and transfer-limit conditions.

The UI explicitly states that scenario headroom and transfer limits are not public physical ratings. Planning-mode map headings, accessible labels, selection readouts, connection-site labels, and interface help text use Planning Model terminology. Legacy synthetic terminology remains only in the fallback legacy mode and in preserved source strings required by compatibility tests.

## Network coverage

All 12 planning regions were inspected through the rendered map accessibility tree. All 20 planning interfaces were inspected through rendered controls. The public layer and county-boundary layer were also confirmed present. The separate calibration report records the full region comparison, interface-relevance sweep, project-size sensitivity, period sensitivity, and representative plan suite.

See [ERCOT Teaching Scenario Audit](ERCOT_TEACHING_SCENARIO_AUDIT.md).

## Evaluation and scoring audit

The standardized audit covered 10–80 MW project sizes, all 12 regions, all 20 interfaces, multiple projects, optional generation, feasible plans, headroom-constrained plans, interface-constrained plans, and deliberately infeasible plans. Feasible plans receive normal positive totals; infeasible plans receive deterministic diagnostics and penalty-based totals rather than disappearing from the ranking. The representative plans and score-component scale are documented in the calibration report.

## Accessibility and interaction checks

Verified:

- planning regions and interfaces expose keyboard-focusable controls;
- resource selection works through keyboard activation;
- existing visible labels remain the accessible source of meaning;
- the provenance sections are readable text rather than color-only distinctions;
- feasible and infeasible results expose text status, score, diagnostics, and binding-resource navigation;
- the raw server response remains collapsed by default;
- validation ranges for `K` and `μ` remain exposed in the form help text;
- the complete automated asset/accessibility regression suite passes.

## Automated regression

Command:

```text
PYTHONPATH="src:/private/tmp/ercot-gate55-pytest" python3 -m pytest -q
```

Result: **584 passed**.

The first sandboxed attempt could not bind ephemeral HTTP test ports; the suite was rerun with local socket permission and completed successfully. The temporary pytest installation was outside the project and no project dependency was added.

## Checks not fully verified in this pass

- A systematic desktop/tablet/mobile viewport matrix was not run because the connected browser did not expose its viewport capability in this session.
- Classroom-mode interactions were covered by the automated regression suite, but not replayed manually through every live browser control in this pass.
- Drag-pan and zoom were not exhaustively replayed in the browser because the Gate 5.5 workflow focused on resource coverage, provenance, evaluation, and navigation; the existing map interaction tests remain green.

These are explicit coverage limits, not reported failures or evaluator blockers.

