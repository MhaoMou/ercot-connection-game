# Cozy Pixel Semantic Icon Family

## Goal

Replace the current generic pixel icon direction with a small, original family of illustrated cozy-RPG engineering objects. The icons should feel handcrafted and object-like while remaining readable and serious within the ERCOT teaching application.

This is a presentation-layer change. Existing DOM IDs, JavaScript selectors, event wiring, API contracts, accessible text, map geometry, and application behavior remain unchanged.

## Artistic direction

The family uses a shared artistic grammar rather than a rigid template:

- SVG symbols designed on a 24×24 logical grid with integer-aligned geometry;
- chunky pixel silhouettes made from rectangles, stepped polygons, and crisp geometry;
- warm-brown outer structure and shadow planes;
- object-specific limited palettes using cream, green, amber, and brick;
- 2–4 tonal steps and small cream highlight clusters;
- intentional negative space and differentiated canvas occupancy;
- slight handcrafted asymmetry where it improves recognition;
- no smooth line-icon treatment, generic UI glyphs, pure-black outlines, or copied game assets.

The symbols must remain legible at rendered sizes of 16px and 24px. A symbol receives a simplified small variant only if the shared 24×24 artwork becomes muddy at 16px; the simplified variant preserves the dominant silhouette.

## Symbol family

The hidden inline SVG library defines these reusable symbols:

- `icon-network`: open transmission structure with separated green electrical nodes and amber energy pixels;
- `icon-plan`: broad folded cream parchment with green route marks and an amber corner tab;
- `icon-evaluation`: taller framed score sheet with cream face, green check, and amber score marks;
- `icon-classroom`: dark-green chalkboard mass with brown stand and cream teaching marks;
- `icon-connection`: compact placeable green electrical node with cream connector and amber contact;
- `icon-generator`: heavier green-metal machine with an offset component, amber electrical element, and dark lower/right shadow;
- `icon-bus`: compact terminal-like electrical block with connection tabs and green/amber center;
- `icon-corridor`: deliberately horizontal stepped transmission segment with separated endpoint terminals;
- `icon-help`: bright amber/yellow quest-marker or token silhouette with dark stepped outline, cream highlight, and strong exclamation mark;
- `icon-error`: unmistakably brick/red engineering notice with a distinct warning silhouette and dark red shadow;
- `icon-success`: green-dominant result/check object with its own open checkmark silhouette, not a recolored error symbol.

## Integration

Use the symbols selectively:

- section navigation: Network, Plan, Evaluation, Classroom;
- meaningful actions: Add Connection Site, Add Generator, Run Practice Evaluation, Explore Network;
- selected-resource inspector: Bus, Corridor, Connection Site, Generator;
- map legend: only Bus and Corridor, because those are the concepts the legend explains;
- help, error, and success symbols only where those states genuinely exist;
- result and validation summaries where an icon reinforces the existing state text.

Do not add icons to zoom, reset, close, dropdowns, checkboxes, or ordinary utility actions in this pass. Avoid repeated copies of the same icon inside a small cluster when the text already establishes object identity.

## Accessibility and behavior

The symbol library is hidden from assistive technology as a definition block. Rendered symbols paired with visible text use `aria-hidden="true"`; existing labels, button text, live regions, and status text remain the accessible source of meaning. An icon receives its own accessible name only when it communicates information not otherwise present in text.

No existing IDs, selectors, event handlers, API contracts, accessible text, or interaction behavior may change. Icons are inserted as presentation elements adjacent to existing content.

## Verification

Add focused source-contract tests that verify:

- all expected symbol definitions exist;
- every `<use>` reference resolves to a defined symbol;
- semantic placements exist for the approved navigation, actions, inspector, legend, and state contexts;
- existing accessible names and labels remain present;
- paired symbols use `aria-hidden="true"`;
- utility controls do not receive unnecessary symbols.

Visually inspect all symbols at 16px and 24px rendered sizes. Simplify individual symbols only where the 16px silhouette or key accent becomes unclear. Confirm that the repeated family reads as a coherent set without making nearby UI clusters visually noisy.

## Scope boundary

This work does not redesign the overall Cozy Pixel theme, map geometry, controls, typography, layout, or application logic. It introduces and integrates the semantic icon family only.
