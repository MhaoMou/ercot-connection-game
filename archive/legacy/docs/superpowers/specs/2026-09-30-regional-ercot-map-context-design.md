# Regional ERCOT Map Context Design

## Goal

Fill the geographic teaching map with a readable regional basemap so the Texas/ERCOT network is geographically grounded, while keeping the physical network elements visually primary.

## Scope

The map will show Texas, neighboring states, northern Mexico, and the Gulf of Mexico. Texas will remain the highlighted teaching region. The surrounding regions will provide context only and will not be treated as network resources.

## Design

- Extend the geographic projection to a regional longitude/latitude extent while preserving equal scale in both directions.
- Add a local SVG context layer behind all Texas county, footprint, corridor, and bus layers.
- Use a dark muted palette for surrounding land and water; use a lighter, warmer treatment for Texas.
- Draw subtle state and country boundaries for orientation. Keep county boundaries confined to Texas.
- Preserve all existing bus coordinates, corridor paths, labels, hover/focus tooltips, zoom, pan, and reset behavior.
- Keep the ERCOT teaching footprint and network objects above the geographic context so they remain the strongest visual signals.
- Add an accessible explanation that the dark surrounding regions are geographic context and are not part of the teaching network.

## Layer order

1. Regional water and land context.
2. Regional boundaries and labels.
3. Texas counties.
4. ERCOT teaching footprint and zone labels.
5. Corridors.
6. Buses and interactive labels.

## Implementation constraints

- Use code-native SVG geometry already served by the application; do not introduce a remote tile provider or runtime network dependency.
- Keep the existing single geographic map. Do not reintroduce or duplicate the schematic grid graph.
- Prefer small, maintainable geometry definitions over a large external geodata package for this teaching-oriented view.
- Maintain keyboard and pointer accessibility for interactive network resources.

## Validation

- Verify the backdrop covers the full geographic viewport without a large blank upper region.
- Verify Texas remains visually emphasized and all current buses/corridors stay in their existing physical locations.
- Verify Mexico and the Gulf remain visible and correctly positioned relative to Texas.
- Verify zoom, pan, reset, hover, focus, and tooltips still work.
- Add or update static checks for layer order, regional context classes, viewport bounds, and absence of a second grid graph.
- Perform browser visual QA at desktop and narrow/mobile widths.

## Not in scope

- Adding live map tiles, live GIS services, county labels outside Texas, or detailed operational data for non-ERCOT regions.
- Changing network coordinates, scenario data, scoring, or game mechanics.
