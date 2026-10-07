# ERCOT Map Interaction Performance

Date: 2026-10-01  
Scope: Planning Model V1 browser interaction only

## Result

Planning Region and Planning Interface selection now uses an incremental DOM
update. The selected resource drawer, selection readout, `aria-pressed` state,
and both map representations update without calling `renderMap()` or
`renderGeographicMap()`.

The public network artifact, county geometry, projection data, and evaluator
are unchanged.

## Root cause

Before this pass, `openResourceDrawer()` ended with `renderMap()`. The schematic
renderer then called `renderGeographicMap()`, which cleared and reconstructed
the Texas boundary, county paths, public transmission paths, public generation,
Planning Interfaces, Planning Regions, and their event handlers. A 12-region
selection therefore paid for work intended for initial loading, layer changes,
or viewport changes.

The same full-render coupling affected closing the drawer.

## Rendering architecture

Full rendering remains the correct path when underlying map data or the
viewport changes:

```text
initial scenario/data load
public-layer toggle
zoom or reset
pan viewport update
        ↓
full schematic/geographic render
```

Selection now follows this path:

```text
Planning Region / Interface selection
        ↓
state.selectedResource
        ↓
resourceElementMaps lookup
        ↓
toggle selected class + aria-pressed
populate drawer + selection readout
```

The lookup maps retain the existing schematic and geographic SVG elements.
Planning Interface entries point to their group so both the visible path and
the hit path remain synchronized. Planning Region entries point to their SVG
group, including the selection frame.

## Instrumentation

`state.publicMetrics` records:

- `selectionMs`
- `planningRenderMs`
- `publicRenderMs`
- `publicCandidateMs`
- `countyRenderMs`
- `geographicRenderMs`
- `publicRenderCount`
- `countyRenderCount`

The instrumentation distinguishes initial/full rendering from selection work.
The public candidate scan is timed inside `publicLineCandidates()` and is not
called by the selection path.

## Measurements

The pre-fix code-path measurement was structural and deterministic: every
selection synchronously invoked `renderMap()` and then the full geographic
renderer. The original user report observed delays of several seconds. A
separate numeric pre-fix wall-clock sample was not retained before the
refactor; it is therefore not presented as a measured number here.

After the refactor, repeated keyboard selections were measured in the live
desktop browser at the default view:

| Interaction | Samples (ms) | Median | Worst observed |
| --- | ---: | ---: | ---: |
| Planning Region, 12 selections | 30–53 | 34 ms | 53 ms |
| Planning Interface, 5 selections | 33–46 | 35 ms | 46 ms |

These measurements include the browser automation action and a short settling
wait, so they are conservative relative to the JavaScript selection handler.
Both are below the 100 ms acceptance threshold.

The final browser check produced no console errors or warnings. The default
configuration remained Public Transmission ON, Planning Model ON, and
Generation OFF, with 634 public lines visible.

## Public and county invariants

Selection does not call public candidate filtering, public transmission
rendering, county rendering, projection, or network fetches. The full renderer
still owns those operations for legitimate data/viewport changes. The
`publicRenderCount` and `countyRenderCount` counters are intended to make this
invariant observable during future audits.

## Pan and zoom

Pan continues to apply the existing SVG viewport transform immediately during
pointer movement. Zoom and reset remain full geographic-render operations so
LOD/culling and projected geometry stay correct. This pass does not change the
public dataset or reduce geographic fidelity.

## Verification

- Focused performance contracts: 4 tests passed.
- Full regression suite after the implementation: 592 tests passed.
- Planning Region selection: drawer and selection readout updated in the live browser.
- Planning Interface selection: drawer and selection readout updated in the live browser.
- Final browser console: no errors or warnings observed.

## Remaining bottlenecks

Initial public-network loading and full renders during layer/viewport changes
remain more expensive than selection. They are intentionally separate from
ordinary resource interaction. Further optimization should be driven by target
hardware measurements rather than by selection latency.

## Read-only results visualization boundary

The published `/results` page is a browser visualization only surface
for an already completed evaluation round. It loads the four sanitized
`results.v1` artifacts:

- `round_metadata.json`
- `public_network.json`
- `team_report.json`
- `aggregate_grid_summary.json`

The page does not evaluate plans, solve DCOPF, perform fair continuous
projection, or recalculate scores. The browser viewer does not recompute the
evaluation. The evaluator is authoritative; the map and summary panels only
visualize the evaluator's published results.

The package is generated with:

```text
PYTHONPATH=src python scripts/build_results_package.py \\
  --network PATH/TO/public_network.json \\
  --evaluation PATH/TO/evaluation.json \\
  --team TEAM_ID \\
  --output-dir web/data/results
```

The package contains only the selected team's detailed report. It must not
expose raw submissions, joint CSV files, other teams' plans, or unredacted
audit data. The aggregate suppression rule suppresses summaries below three
verified contributing teams. This privacy boundary is part of the release
contract, not just a presentation preference.
