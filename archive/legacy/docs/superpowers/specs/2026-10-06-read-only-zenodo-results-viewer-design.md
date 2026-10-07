# Read-Only Zenodo Results Viewer Design

## Goal

Reuse the existing ERCOT teaching webpage as a privacy-preserving, read-only
results viewer that displays an evaluated team plan over the Zenodo-derived
Texas power network.

## Scope

This is a presentation and data-adapter change. It does not change the
evaluator mathematics, CSV submission contract, dispatch model, scoring rules,
or instructor-side batch evaluation. The existing practice/submission
experience remains available; the new viewer is exposed through a separate
`/results` route or equivalent results mode.

## Design decisions

### Results delivery

The first release loads one sanitized round package from a fixed
`web/data/results/` directory. The browser never receives raw submissions or
other teams' identifying plan data. A package contains:

```text
round_metadata.json
public_network.json
team_report.json
aggregate_grid_summary.json
```

`team_report.json` contains only the selected team's plan and results.
`aggregate_grid_summary.json` contains anonymized, coarse system-level
statistics and must not expose another team's locations, capacities, profiles,
or identifiers.

### Network source

The toy teaching grid is replaced by a web-friendly artifact derived from the
prepared Zenodo Texas dispatch dataset. The public artifact may contain buses,
branches, generators, geographic coordinates, and display-safe attributes.
The conversion step validates coordinates and branch endpoints before the
artifact is used by the webpage.

### Viewer layout

The results route contains:

1. a compact round/team score summary;
2. the interactive map;
3. the selected-resource inspector;
4. a small set of performance plots and diagnostics.

The plan editor, classroom controls, toy-grid scenario controls, and
submission actions are not shown in this read-only mode.

### Map layers

The map preserves the existing zoom, pan, reset, keyboard selection, and
accessibility interactions. Its visible layers are ordered as follows:

1. public geography and geographic context;
2. public Zenodo network;
3. the selected team's own sites, generators, and storage;
4. anonymized congestion/utilization overlays.

The public network is displayed at multiple detail levels. Overview views use
selective labels and simplified geometry; closer views reveal more buses,
branches, and technical details. The first implementation retains the current
SVG map architecture with label culling and measured performance. A canvas or
hybrid dense-layer renderer is deferred unless full-network measurements show
that SVG is inadequate.

### Privacy

The viewer must not expose:

- another team's bus or generator selections;
- another team's capacities or hourly profiles;
- team identifiers attached to shared congestion;
- raw joint CSV files;
- exact aggregate statistics that isolate a small number of teams.

Shared statistics are rounded, binned, or suppressed when necessary. Detailed
diagnostics remain private to the selected team's report.

## Data flow

```text
Zenodo source + instructor evaluation
        |
        v
sanitized round-package generator
        |
        v
web/data/results/*.json
        |
        v
read-only /results viewer
```

The viewer is a consumer of evaluated artifacts. It does not run DCOPF,
recompute scores, or infer results from raw team submissions.

## Error handling

- Missing result packages show an explicit unavailable-results state.
- Malformed JSON or schema mismatches show a readable data-version error.
- Missing optional aggregate overlays do not prevent the team report or public
  network from rendering.
- Missing coordinates or invalid branch endpoints are reported by the artifact
  validation step and are not silently drawn.

## Testing and acceptance criteria

The implementation must add or update tests for:

- loading a valid results package;
- rejecting malformed or incomplete package data;
- converting Zenodo network records into map records;
- ensuring the browser-facing package contains no raw other-team data;
- rendering the selected team's resources;
- rendering anonymized aggregate overlays;
- preserving map zoom, pan, reset, selection, and keyboard behavior;
- displaying a graceful missing-results state;
- measuring full-network render/update behavior at representative zoom levels.

The existing evaluator, CSV checker, and practice workflow must remain
regression-tested without modification to their contracts.

## Out of scope

- changing dispatch or scoring mathematics;
- adding instructor authentication;
- browser-side evaluation;
- replacing the evaluator with a JavaScript implementation;
- exposing a live upload workflow;
- redesigning the existing submission editor;
- replacing SVG before performance evidence requires it.

