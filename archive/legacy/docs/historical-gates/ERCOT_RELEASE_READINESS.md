# ERCOT Gate 6 Release Readiness Audit

Date: 2026-09-30  
Production scenario: `ercot-planning-teaching-v2` / `2.0.0`  
Planning model: `ercot-public-derived-planning@1.0.0`

## Final decision

**RELEASE READY WITH KNOWN LIMITATIONS**

No P0 blockers remain. The primary student workflow is operational, the production default is the public-data-informed Planning Model / Teaching Scenario path, and the existing evaluator mathematics are preserved. The remaining limitations are documented below and should be addressed with real device/browser coverage or instructor feedback rather than another architecture gate.

## Status summary

| Area | Status | Evidence / limitation |
| --- | --- | --- |
| Core planning workflow | PASS | Live scenario load, plan creation, optional generator, feasible/infeasible evaluation, and result navigation verified. |
| Public Network | PASS | Default public transmission layer is on; default view reports 634 rendered public lines. Generation is off by default. |
| Planning Model | PASS | 12 Planning Regions and 20 Planning Interfaces rendered and keyboard-selectable. |
| Teaching Scenario | PASS | V2 loads by default; calibration audit found no required recalibration. |
| Evaluation | PASS | Feasible, infeasible, region-bound, and interface-bound behavior covered by Gate 5.5 tests and live representative workflow. |
| Desktop UI | PASS | Default browser view inspected; hierarchy, labels, controls, and map framing are usable. |
| Tablet UI (1024 / 768) | NOT VERIFIED | Connected browser did not expose a viewport override capability in this session. |
| Mobile UI (390) | NOT VERIFIED | Responsive CSS exists and automated assets remain green, but a true 390px browser viewport was not available for manual inspection. |
| Classroom | PASS WITH LIMITATION | Full classroom service behavior is covered by the automated suite; the full live instructor/student UI flow was not replayed manually in this pass. |
| Accessibility | PASS | AX tree exposes semantic navigation, buttons, labels, status regions, 12 region controls, and 20 interface controls; decorative SVG symbols are hidden. |
| Performance | PASS WITH LIMITATION | Default view: 634 public paths and 957 total geographic paths; zoomed view observed roughly 4,670–6,307 public lines. Public asset is 17.9 MB; local request timings were acceptable, but mobile performance was not measured. |
| Reproducibility | PASS WITH LIMITATION | Version matching, deterministic artifact hashes, and generation-module smoke checks passed; a clean external checkout regeneration was not performed. |
| Documentation | PASS | README now identifies the V2 production default; instructor and student notes added. |
| Deployment hygiene | PASS WITH LIMITATION | Relative static/API paths and no embedded local filesystem paths found in production assets. Local-only host examples remain intentionally documented. |

## Production mental model

The landing screen now communicates:

`PUBLIC NETWORK` geographic context → `PLANNING MODEL` 12 regions / 20 interfaces → `TEACHING SCENARIO` instructional assumptions.

The deeper provenance explanation remains behind **About network data**. The header explicitly states that the application is public-data-informed and not an official ERCOT planning recommendation.

## Terminology audit

Planning-mode production text now uses Planning Region and Planning Interface for map headings, accessible labels, selection readouts, inspectors, tooltips, connection editors, and binding navigation. Legacy terms remain only in explicit legacy-mode branches, evaluator/API schema fields, historical Gate reports, tests, and the isolated `ercot_small.json` fixture.

The README and Phase 2 guide were corrected so they no longer describe the legacy fixture as the production default.

## Network and map audit

Verified in the live browser:

- Public transmission ON, Planning Model ON, Generation OFF is the default.
- All 12 Planning Regions are rendered and selectable.
- All 20 Planning Interfaces are rendered and selectable.
- Planning Model anchors use concise labels; the duplicate long zone-label layer is suppressed in Planning Model mode to prevent default-view collisions.
- Selected-region and selected-interface inspectors retain public-derived context separately from instructional scenario values.
- Binding state is rendered with text and map styling rather than color alone.
- Reset View restored the default map after zoom interaction.
- Public transmission remains subdued behind Planning Model resources at the default view.

The browser automation bridge intermittently timed out on semantic locator clicks for SVG/map controls; coordinate and keyboard activation were used where needed. No application console errors were observed after the final reload.

## Help, evaluation, validation, and error states

The existing Help disclosures explain the objective, map layers, plan construction, generators, evaluator diagnostics, provenance, and limitations without exposing pipeline-internal Gate methodology. Feasible and infeasible results expose status, score, accepted/curtailed values, binding resources, and actionable diagnostics. Raw server JSON remains collapsed. Form ranges and actionable field errors remain exposed.

The automated suite covers server/API errors, stale-result invalidation, Classroom retry/error handling, legacy fixture isolation, and versioned submission behavior. Live initial loading, empty plan, and loaded production states were inspected.

## Legacy isolation and version safety

The old `data/fixtures/ercot_small.json` scenario remains available for explicit regression/debugging and legacy request-shape tests. The production server default resolves to `data/teaching/ercot_connection_scenario_v2.json` and joins `data/processed/ercot_planning_model_v1.json`. Planning submissions retain `planning_model_version`, `scenario_version`, and `plan_schema_version`; the full automated suite covers version and historical-submission behavior.

## Security and deployment findings

No secrets, private URLs, absolute filesystem paths, or development-only asset references were found in production HTML, JavaScript, CSS, or server static routes. The Classroom service is intentionally local and uses its documented instructor bootstrap/session boundary; it is not being represented as a production identity service. Localhost examples in README and historical guides are intentional deployment instructions, not embedded runtime dependencies.

## Findings

| Priority | Finding | Disposition |
| --- | --- | --- |
| P0 | None | No release blockers found. |
| P1 | Duplicate/colliding Planning Region labels on the default map | Fixed by using concise anchor labels and suppressing duplicate planning-zone labels in Planning Model mode. |
| P1 | Production README/Phase 2 guide described the legacy fixture as default | Fixed; legacy fixture is now explicitly isolated. |
| P2 | Tablet/mobile viewport matrix and mobile performance remain unverified | Documented limitation; requires a browser/device environment with viewport control. |
| P2 | Full manual Classroom UI replay remains incomplete | Automated service coverage passes; schedule a short instructor-led acceptance session before a live class. |
| P2 | High-zoom public layer renders thousands of SVG paths | No demonstrated desktop bottleneck; measure on target student hardware before optimizing. |

## Verification record

- Gate 6 focused tests: `4 passed` (included in the focused 160-test Gate 6/regression mix).
- Gate 5.5 focused tests: `6 passed`.
- Full regression suite after Gate 6 changes: **588 passed**.
- Production browser: scenario loaded, 12 regions, 20 interfaces, default 634 public lines, no console errors after final reload.
- Artifact hashes recorded during audit:
  - Planning Model V1: `4b7d4f40e1926c540045eadc27127def2729b8f19c07128668af54a4bea69755`
  - Teaching Scenario V2: `5e23c5e4f72fa9a6da0704a0b0eaa14e2e7b76eb5d019bea597351d9c02525df`
  - Public Network: `bb31ae4cc86bbbc083aaa2f1ab87aae4636492f6dd8fe13ab255f51cf8d06490`

## Release notes

- [Instructor release note](ERCOT_INSTRUCTOR_RELEASE_NOTE.md)
- [Student quickstart](ERCOT_STUDENT_QUICKSTART.md)
- [Teaching Scenario audit](ERCOT_TEACHING_SCENARIO_AUDIT.md)
- [Gate 5.5 E2E QA](ERCOT_GATE5_5_E2E_QA.md)
