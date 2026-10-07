# GitHub-Style IBM Plex Visual Redesign

## Goal

Make the ERCOT teaching interface feel like a calm, technical GitHub-style product UI while preserving the existing map, classroom workflow, evaluator behavior, and accessibility.

## Visual direction

- Use a light semantic palette inspired by GitHub Primer: cool gray page background, white surfaces, thin neutral borders, restrained blue actions, and semantic status colors.
- Use IBM Plex Sans for UI text and IBM Plex Mono for IDs, bus/corridor identifiers, numeric values, diagnostics, and other technical data.
- Bundle the IBM Plex font files locally so the page remains consistent without a network connection; provide robust fallbacks if the font cannot load.
- Reduce visual decoration: minimal/no shadows, fewer nested rounded containers, smaller corner radii, and a tighter spacing rhythm.
- Keep the existing dark geographic context and highlighted Texas/ERCOT map, but place it inside the new neutral visual system.

## Component treatment

- Header: reduce oversized display typography and use a compact technical title hierarchy.
- Panels: use white surfaces, 1px borders, and subtle section dividers instead of large floating cards.
- Buttons: use a clear blue primary action, outlined secondary actions, compact heights, and consistent focus rings.
- Forms: use neutral inputs, compact labels/help text, and clear invalid/error borders.
- Guidance: keep instructional content but visually subordinate it to the task controls.
- Status: use semantic success, warning, error, and informational tokens; never communicate state by color alone.
- Results and classroom panels: use compact metric rows and restrained status badges rather than heavy decorative blocks.
- Map: preserve current geographic layers, zoom/pan, hover/focus behavior, and bus/corridor emphasis.

## Typography

- Define a single `--font-sans` stack beginning with the locally bundled IBM Plex Sans.
- Define a `--font-mono` stack beginning with the locally bundled IBM Plex Mono.
- Use Plex Sans for headings, body copy, labels, buttons, and instructional content.
- Use Plex Mono selectively for technical values, identifiers, table-like metrics, and raw diagnostics.
- Replace oversized/over-bold headings with a restrained scale and semibold section headings.

## Constraints

- Do not change API behavior, scenario data, scoring, evaluator output, or classroom state transitions.
- Do not copy GitHub logos, icons, or proprietary assets.
- Preserve the single geographic map and existing map interaction contract.
- Preserve responsive behavior at narrow widths.
- Keep contrast at accessible levels for body text, controls, focus indicators, and semantic states.

## Validation

- Verify IBM Plex font assets are served locally and fallback stacks remain valid.
- Verify the page uses the new neutral/blue semantic tokens rather than the current green-heavy palette.
- Verify nested panel/card density is reduced without hiding educational guidance.
- Verify map controls, bus/corridor interaction, zoom/pan/reset, and selected-resource drawer behavior.
- Verify responsive layout and keyboard focus states.
- Add source-contract checks for font declarations, semantic color tokens, reduced shadows/radii, and unchanged geographic map structure.
- Run the full pytest suite and browser visual QA.
