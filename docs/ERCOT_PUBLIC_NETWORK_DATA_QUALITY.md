# Gate 2 — ERCOT Public Network Data Quality

**Audit/build date:** 2026-09-30  
**Canonical artifact:** `data/processed/ercot_public_network.json`  
**Browser artifact:** `web/data/ercot-public-network.json`  
**Schema:** `gate2.public-network.v1`

## Coverage

This artifact is a **public geographic network approximation**, not a full ERCOT electrical network. It combines:

- 2022-era HIFLD/DHS public electric transmission-line geometry queried for a documented Texas bounding box;
- 2025 EIA Form 860 plant and generator records filtered to Texas plants whose EIA balancing-authority code is `ERCO`.

The line inclusion box is `[-106.65, 25.83, -93.50, 36.50]` in WGS84 order `[west, south, east, north]`. It is an approximation because the HIFLD transmission-line layer has no ERCOT footprint or balancing-authority membership field. It includes some Texas-area infrastructure that may not belong to ERCOT and may omit cross-boundary context outside the box.

## What is source-derived

- HIFLD line source identifiers and public attributes.
- HIFLD line geometry, preserving all source vertices after consecutive duplicate removal.
- HIFLD voltage values when present and positive.
- EIA plant IDs/names, coordinates, and source-native plant/resource information.
- EIA generator IDs, technology, prime mover, and nameplate capacity.
- Source URLs, record IDs, retrieval artifacts, and SHA-256 checksums.

## What is derived

- Stable IDs generated from source name and source-native record ID.
- One `derived_endpoint` geographic node per retained line endpoint.
- `source_endpoint` topology confidence for that conservative endpoint relationship.
- Texas bounding-box inclusion and boundary-crossing flags.
- EIA plant filtering using `State=TX` and `Balancing Authority Code=ERCO`.
- Browser artifact field reduction. Geometry is not simplified in this Gate 2 build; it is copied from the canonical artifact.

No line crossing is treated as an electrical junction. No endpoint spatial merging is performed. Boundary-crossing source geometries are retained and flagged; clipping-generated nodes are not created.

## Statistics

### HIFLD line ingestion

| Metric | Value |
|---|---:|
| Raw FeatureServer features returned | 8,190 |
| Retained normalized branches | 7,769 |
| Duplicate source records removed | 421 |
| Invalid geometries | 0 |
| Boundary-crossing geometries retained/flagged | 106 |
| Canonical geometry points | 262,252 |
| Approximate geometry length | 102,930.92 km / 63,958.29 mi |
| Raw GeoJSON size | 14,933,174 bytes |

The length is a haversine sum over source vertices and is only a geometry sanity check. It must not be compared directly with ERCOT’s published transmission-mile statistic without matching definitions, voltage thresholds, circuit/segment treatment, and footprint.

### EIA ingestion

| Metric | Value |
|---|---:|
| EIA plant rows read | 17,349 |
| EIA generator rows read | 27,919 |
| Texas/ERCO plants retained | 1,404 |
| Texas/ERCO generators retained | 2,179 |
| Plants connected to network nodes | 0 |
| Generators connected to network nodes | 0 |

### Conservative graph diagnostics

| Metric | Value |
|---|---:|
| Geographic endpoint nodes | 15,538 |
| Branches | 7,769 |
| Connected components | 7,769 |
| Largest component | 2 nodes |
| Isolated nodes | 0 |
| Degree minimum / mean / maximum | 1 / 1.0 / 1 |
| Spatially merged endpoints | 0 |
| Boundary-derived nodes | 0 |
| Unresolved endpoints | 0 |

The graph is intentionally disconnected because each line has independent derived endpoints. This is an honest statement of what the public line geometry supports; it is not a failure to force a plausible electrical graph.

### Voltage distribution

| Nominal kV | Branch count |
|---:|---:|
| 69 | 1,228 |
| 115 | 536 |
| 138 | 3,884 |
| 161 | 153 |
| 230 | 117 |
| 345 | 510 |
| 500 | 7 |
| 13.8 | 11 |
| 34.5 | 2 |
| Missing/unknown | 1,321 |

The 13.8 and 34.5 kV records are reported rather than silently rejected; they are unusual for a transmission layer and should be reviewed in a later source-quality pass.

## What is unavailable

- official ERCOT bus IDs and authoritative bus names;
- authoritative ERCOT bus-to-branch topology;
- substations from the restricted-public HIFLD substation layer;
- impedance (`R`, `X`, `B`);
- thermal/emergency ratings;
- voltage limits and transformer parameters;
- real-time or planning headroom;
- bus-level load and generation profiles;
- authoritative generator-to-network-node connectivity;
- ERCOT membership for each HIFLD line feature.

No teaching parameters were created: no synthetic headroom, capacity, impedance, congestion, marginal cost, connection fee, artificial load, or curtailment assumption is present in this artifact.

## Validation status

The automated Gate 2 validation reports no errors for the generated artifact. It checks unique IDs, branch endpoint references, plant-generator references, finite coordinates, valid geometry length, and available voltage plausibility. It reports unusual positive voltage values rather than rejecting them.

The validation suite also covers malformed geometry, duplicate source records, outside-boundary filtering, deterministic IDs, provenance retention, unresolved electrical connectivity, and the rule that line crossings do not create connectivity.

## Performance characterization

| Artifact | Size |
|---|---:|
| HIFLD raw GeoJSON | 14.3 MiB |
| EIA raw ZIP | 22.5 MiB |
| Canonical JSON | 18.5 MiB |
| Browser JSON | 17.3 MiB |
| Estimated branch SVG groups at full render | 7,769 |
| Estimated endpoint-node SVG groups at full render | 15,538 |

The build parses the EIA ZIP and produces both JSON artifacts in approximately 7–10 seconds on the development machine. Browser parse/render time was not measured because Gate 2 must not modify or integrate the application.

## Gate 3 rendering recommendation

Choose **Option B: SVG with level-of-detail filtering**, initially.

The measured scale is too large for rendering every line and endpoint as a detailed, always-interactive SVG view. However, it is still small enough to support SVG overlays and interaction if Gate 3 uses:

- viewport filtering;
- zoom-dependent geometry/detail levels;
- simplified presentation geometry generated separately from canonical data;
- search-driven selection;
- limited hit targets for visible resources;
- no assumption that every endpoint is an electrical bus.

If Gate 3 requires persistent rendering of all 7,769 branches and 15,538 endpoints at once, Canvas/WebGL should be evaluated as Option C for the physical-network layer, with SVG/DOM retained for selected-resource overlays and accessible controls.

## Limitations and next decision

This Gate 2 artifact is suitable as a provenance-preserving public geographic layer, not as an evaluator network. The teaching model remains untouched. Gate 3 must decide how to present this layer and how to keep it separate from the reduced teaching/evaluation graph.
