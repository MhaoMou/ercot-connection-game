# ERCOT Public-Region Network Explorer — Gate 3

Status: implemented for review; Gate 4 is intentionally not started.

## Scope

Gate 3 adds a read-only public-data context layer to the existing geographic teaching map. The public layer is independent from the synthetic teaching network and from the practice evaluator. No public geometry is converted into evaluator buses, corridors, connectivity, headroom, or feasibility constraints.

## Layers and interaction

- **Public transmission** is enabled by default and rendered as subdued, voltage-aware linework.
- **Teaching network** remains enabled by default and remains the visually dominant interactive layer.
- **Generation** is available as an optional, disabled-by-default plant-level layer.
- Public transmission and generation use pointer inspection only; they are not added to the keyboard navigation sequence.
- Public transmission detail reports the public identifier, HIFLD provenance, voltage when reported, and the unresolved geographic-topology limitation.
- Generation is aggregated by EIA plant ID from generator records and reports plant ID, aggregate capacity, generator count, and technologies.
- Endpoints are not rendered as bus markers, and no intersections are inferred as electrical connectivity.

## Data and provenance

The browser artifact is `web/data/ercot-public-network.json`, generated from the Gate 2 pipeline. The current artifact contains 7,769 public transmission branches, 1,404 EIA plants, and 2,179 generator records. Sources and limitations are disclosed in the expandable **About network data** panel and in:

- `docs/ERCOT_PUBLIC_NETWORK_DATA_QUALITY.md`
- `docs/ERCOT_PUBLIC_NETWORK_PROVENANCE.md`
- `data/raw/README.md`

The app serves this artifact independently from the scenario endpoint. A failed public-artifact request leaves the teaching map and evaluator usable and reports a non-blocking warning state.

## Rendering and performance strategy

The implementation starts with SVG, as specified for Gate 3, and limits work using both viewport culling and zoom-based level of detail:

- zoom ≤ 1.3: only public lines at or above 230 kV;
- 1.3 < zoom ≤ 2: lines at or above 115 kV plus lines without a reported voltage;
- zoom > 2: all visible public lines;
- plant markers use 100 MW, 25 MW, and 0 MW thresholds at the same zoom tiers.

Each browser branch carries a precomputed bounding box, so line candidates can be rejected before projection and DOM creation. The client records fetch, JSON parse, and initial public-map render durations in `state.publicMetrics` for browser-side characterization. The visible-line count is also exposed in the layer status text.

During manual browser verification at the default view, the live status reported **634 public lines visible** while the teaching network remained interactive. The artifact response is approximately 17.9 MB uncompressed over the local development server; this is an expected Gate 3 limitation and a future optimization target (compressed/partitioned tiles or a vector-tile representation) rather than a reason to couple the data to the evaluator.

## Regression and visual audit

Verified in the current implementation:

- static asset route serves the public artifact;
- default layer states are public transmission ON, teaching network ON, generation OFF;
- public loading status transitions to a live line count;
- public SVG groups render independently of the teaching groups;
- public legend entries are separated from teaching-model entries;
- About network data disclosure is present and expandable;
- public artifact pipeline tests pass;
- existing DOM IDs and evaluator-facing event wiring are preserved.

## Gate 3.5 verification record

The live in-app browser was reloaded at the default viewport and verified the independent loading state, the default layer states, the teaching-map accessibility tree, and the live status of 634 public lines. A screenshot inspection showed the Texas frame, subdued public context, square teaching buses, readable teaching labels, in-map controls, and no visible page-level horizontal overflow at that viewport.

The requested matrix is recorded explicitly below:

| Viewport | Zoom 1.0 | Zoom ≈1.5 | Zoom ≈2.5 | Result |
| --- | --- | --- | --- | --- |
| 1440 px | not available in current in-app automation | not available | not available | Could not set this viewport |
| 1024 px | not available in current in-app automation | not available | not available | Could not set this viewport |
| 768 px | not available in current in-app automation | not available | not available | Could not set this viewport |
| 390 px | not available in current in-app automation | not available | not available | Could not set this viewport |
| Current live browser viewport | visually inspected | zoom action timed out | zoom action timed out | Default view verified; zoom evidence incomplete |

No CSS or map redesign was made during this verification pass. Because the available browser control surface could not set arbitrary viewport widths and its zoom-button action timed out, the four-width/three-zoom visual matrix is not claimed as passed.

Public-line interaction was also not claimed as passed: the public paths are present as pointer-only, non-focusable SVG elements and the source code limits their tooltip fields to public ID, HIFLD source, voltage, and the explicit geographic-topology limitation. However, the current automation surface did not provide reliable pointer targeting of thin public paths for direct end-to-end tooltip confirmation. No public-line path has a teaching resource role, keyboard tab stop, or evaluator event handler.

Representative live instrumentation observed in the browser:

- `state.publicMetrics.lastTransmissionCount`: 634 at default zoom;
- `state.publicMetrics.lastGenerationCount`: 0 with generation disabled by default;
- `state.publicMetrics.lastRenderZoom`: 1 at the default view;
- `state.publicMetrics.fetchMs`, `parseMs`, and `renderMs`: recorded by the client on initial load for future browser-side profiling, but not exposed through the current accessibility tree.

The unresolved browser-only checks are therefore explicit follow-up items for a full visual browser QA environment; they are not defects silently marked as passed.

## Gate boundary

This gate does not add public-data evaluation, public bus mapping, inferred topology, dispatch modeling, or authoritative ERCOT operational claims. Those are explicitly outside the Gate 3 scope.
