# Geographic Map and Schematic Polish Design

## Goal

Improve the teaching interface's grid visualization by adding a read-only, geographic ERCOT view below the existing schematic network graph, centering and visually de-emphasizing the schematic, and preserving the existing map interaction and evaluation workflow.

## Scope

This is a presentation-only change. It does not change the evaluator, canonical submission payload, scenario data, bus/corridor definitions, scoring, or API contract.

## Design

### 1. Two complementary map views

The existing schematic SVG remains the primary topology view because it makes connectivity, corridors, and congestion easy to inspect. It will be centered within its panel, use smaller bus labels, and use thinner corridor strokes so the network is readable without dominating the page.

Directly below it, the page will show a geographic ERCOT panel. This panel will be read-only: it will reuse the scenario's footprint, bus coordinates, zone labels, and corridor geometry, but it will not introduce a second editing model. Buses and corridors will retain the existing hover/click behavior, including the resource drawer and selected-period context.

### 2. Lightweight map navigation

The geographic panel will use a dependency-free SVG viewport rather than external map tiles. It will provide accessible zoom-in, zoom-out, and reset controls, plus pointer dragging for panning. Zoom will be clamped to a sensible range and reset will return to the full ERCOT footprint. The underlying scenario coordinates remain unchanged; navigation only changes the rendered viewport.

### 3. Interaction and responsive behavior

The existing period selector and layer toggles remain shared by both views. Hovering a bus or corridor in either view updates the same information drawer. On narrow screens, each map becomes horizontally scroll-safe and the geographic controls remain reachable without obscuring the map. The geographic view will include a short explanatory caption so students understand that it is a locator view, while the schematic continues to explain electrical topology.

### 4. Verification

Add/adjust frontend asset tests for the geographic-map markup, navigation controls, and scale-related classes/hooks. Run the full Python test suite, then run a browser smoke check against the local practice server to verify both maps render, zoom/reset controls respond, the schematic is centered, and no console errors are introduced.

## Non-goals

- No external map provider, tile download, geocoding, or geographic accuracy claim beyond the teaching fixture.
- No changes to submission semantics or evaluator behavior.
- No replacement of the schematic graph with the geographic map.
