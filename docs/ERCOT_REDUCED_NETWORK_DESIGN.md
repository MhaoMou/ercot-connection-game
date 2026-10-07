# Gate 4 — Reduced Planning Network Design

Status: Gate 4.6 reconstructed candidate produced and audited. The current synthetic teaching network, evaluator, canonical plan schema, classroom behavior, and teaching limits are unchanged. Gate 5 has not started.

## 1. Reduction objective

The purpose of Gate 4 is to design a smaller, defensible planning abstraction for a connection-planning exercise—not to recover an unavailable ERCOT electrical graph. The abstraction should preserve geographic structure, transmission-density patterns, voltage hierarchy, generation geography and mix, plausible regional interfaces, student interpretability, and interactive tractability while keeping public evidence separate from instructional operating assumptions.

## 2. Source limitations

The Gate 2 artifact contains 7,769 public transmission geometries, 15,538 conservative geographic endpoints, and 1,404 EIA plants / 2,179 generators. Its 7,769 two-node components are source-geometry components, not an ERCOT electrical topology. The data does not provide authoritative ERCOT bus identities, electrical connectivity, impedance, ratings, or line thermal limits. Endpoint proximity and visual line crossings are therefore never treated as electrical connections.

## 3. Candidate strategies

| Strategy | Strength | Risk | Gate 4 assessment |
| --- | --- | --- | --- |
| Geographic regional aggregation | Most interpretable and robust to missing topology | Interfaces need explicit evidence rules | Strong baseline; use transparent geographic regions rather than bus-like nodes |
| Data-driven geographic clustering | Reproducible and responsive to density/generation features | Cluster boundaries can look arbitrary and have no electrical meaning | Useful as a sensitivity analysis, not sufficient by itself |
| Hybrid geography + engineering hierarchy | Preserves geographic explanation while exposing density, voltage, and generation hierarchy | Requires more documented choices | Recommended architecture |

The generated candidates use a deterministic rectangular partition as an intentionally transparent hybrid baseline. It is a reproducible analysis scaffold, not a claim that rectangular cells are the final ERCOT planning regions.

## 4. Planning-node definition

A planning node is a geographic planning region, never an ERCOT bus. Each node has a stable ID, explanatory label, centroid, grid position, mapped public transmission IDs, mapped EIA plant and generator IDs, transmission counts/length/voltage distribution, generation capacity and technology totals, and derivation provenance.

## 5. Planning-corridor definition

A planning corridor is an aggregate geographic interface between two planning regions. It exists only when a source transmission geometry traverses both regions. It stores the supporting public branch IDs, crossing count, source-geometry length evidence, voltage distribution, and an explicit `teaching_transfer_limit_mw: null`. It does not claim a bus-to-bus branch, electrical connectivity, or transfer capability.

## 6. Generation aggregation

EIA generators are assigned to the geographic region containing their plant coordinates. The candidate retains total nameplate capacity, plant count, generator count, and technology-capacity totals. It does not assign a plant to a public transmission endpoint or infer an electrical bus connection.

## 7. Load-data status

No detailed regional ERCOT load allocation is introduced in Gate 4. Population is not substituted for load. If a defensible public regional/zonal load source is selected later, it must be mapped as a separate public-data layer; otherwise load remains a future teaching-scenario assumption.

## 8. Candidate scales and preservation metrics

The reproducible pipeline is `tools/ercot_reduced_network/build.py`. It emits:

- [`candidate_08.json`](../data/processed/reduced/candidate_08.json): 8 planning nodes, 9 geographic interfaces;
- [`candidate_12.json`](../data/processed/reduced/candidate_12.json): 12 planning nodes, 16 geographic interfaces;
- [`candidate_20.json`](../data/processed/reduced/candidate_20.json): 20 planning nodes, 24 geographic interfaces.

All three candidates map 7,769/7,769 public geometries and 634/634 geometries with reported high-voltage class ≥230 kV. All three map all 1,404 plants and 2,179 generators, with 172,206.9 MW of summed EIA nameplate capacity. These representation metrics are deliberately reported separately; they are not collapsed into an arbitrary composite score.

| Candidate | Nodes | Interfaces | Transmission representation | ≥230 kV representation | Generation representation | Interpretability | Interactive complexity |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 08 | 8 | 9 | 100% | 100% | 100% | Very high; broad regions | Low |
| 12 | 12 | 16 | 100% | 100% | 100% | High; useful subregional distinctions | Moderate |
| 20 | 20 | 24 | 100% | 100% | 100% | Lower; more labels and interfaces | Higher |

The 100% values mean every source record is geographically assigned to at least one region/interface record; they do not mean the candidate recovers electrical connectivity.

## 9. Visual analysis

Analysis-only SVG overlays are generated by `tools/ercot_reduced_network/render.py`:

- [`candidate_08.svg`](../data/processed/reduced/candidate_08.svg)
- [`candidate_12.svg`](../data/processed/reduced/candidate_12.svg)
- [`candidate_20.svg`](../data/processed/reduced/candidate_20.svg)

Each overlay shows subdued public line geometry, region boundaries, planning-node anchors, and dashed aggregate geographic interfaces. The overlays are not wired into the application and do not replace the current teaching map.

## 10. Comparison with the synthetic teaching network

The current teaching baseline has 32 synthetic buses and 48 representative corridors. It provides pedagogical diversity, hand-designed headroom/capacity variation, period profiles, binding behavior, and a compact evaluator-friendly plan schema. The Gate 4 candidates provide public geographic traceability and generation context but currently have no instructional headroom, congestion, cost, load, or transfer limits. Therefore public-data derivation alone does not make them a pedagogically superior replacement.

## 11. Recommended architecture

Recommend the 12-node hybrid architecture as the next design candidate. Eight regions are likely too coarse for students to reason about distinct West, Central, North, Gulf, and South behavior; twenty regions add labels and interfaces faster than they add pedagogical value. Twelve nodes and sixteen interfaces remain interpretable while leaving room for future teaching limits and connection-site diversity.

The recommendation is provisional. Before migration, the 12-node partition should be reviewed against explicit Texas/ERCOT-oriented anchors and public density/generation maps. The current rectangular partition is intentionally conservative and reproducible, but it should not be presented as an official ERCOT zonal model.

## Gate 4.6 reconstruction

The rectangular production construction was rejected after Gate 4.5 because it created empty/low-evidence cells, extreme density imbalance, generic labels, and hard-boundary artifacts. The replacement is [`candidate_12_v2.json`](../data/processed/reduced/candidate_12_v2.json), generated by [`regionalize.py`](../tools/ercot_reduced_network/regionalize.py).

The reconstruction uses twelve fixed, geographically interpretable seed anchors, a 0.1-degree raster restricted to the largest mainland ring in the bundled Texas boundary asset, nearest-seed assignment, and deterministic repair of disconnected non-primary raster components. Geography is the hard constraint; public transmission density, voltage, generation geography, and technology are summarized evidence and do not override spatial coherence. The secondary small boundary ring is excluded from the contiguous mainland planning footprint and remains documented as a geographic limitation, not an ERCOT-boundary claim.

Interfaces are regenerated from source geometries. A geometry contributes only when sampled path length is at least 5 km in each adjacent planning region. A single supporting geometry is retained only when it is 230+ kV; otherwise it is treated as weak interface evidence. No MW capacity or teaching limit is assigned.

The reconstructed audit returns **PASS**: all 12 regions have public transmission evidence, all regions are contiguous in the raster representation, IDs and labels are geographic and stable, no weak low-voltage single-geometry interface remains, and no electrical connectivity is inferred. Public geometries outside the Texas boundary remain unassigned instead of being forced into a region. Full audit details are in [`ERCOT_REDUCED_NETWORK_AUDIT.md`](ERCOT_REDUCED_NETWORK_AUDIT.md).

## 12. Provenance mapping

Every candidate node stores public transmission, plant, and generator IDs. Every candidate corridor stores supporting public branch IDs. Candidate metadata records the source artifact and method. This permits a future UI explanation such as “this interface is shown because these source geometries traverse both geographic regions,” without claiming that the lines form an electrical transfer path.

## 13. Unresolved questions

1. Which public regional or zonal load source, if any, is defensible for the teaching objective?
2. Should the final partition use fixed geographic anchors, a constrained clustering sensitivity analysis, or a reviewed hybrid boundary set?
3. What minimum public evidence should be required before displaying a candidate interface?
4. Which instructional limits and period parameters should be authored independently of public evidence?
5. How should student connection sites map to planning regions without implying public bus identity?

## 14. Reproducibility

From the repository root:

```bash
python3 tools/ercot_reduced_network/build.py
python3 -m tools.ercot_reduced_network.render
pytest -q tests/test_reduced_network.py
```

The pipeline consumes the Gate 2 artifact and emits deterministic JSON/SVG candidates. It does not modify `data/fixtures/ercot_small.json`, `web/app.js`, evaluator code, classroom code, or the canonical plan schema.

## 15. Proposed Gate 5 migration plan

Gate 5 should begin only after review of the candidate artifacts. It may define a derived-network schema and a parallel evaluator experiment, but should preserve the current teaching scenario as a baseline. Migration should require explicit teaching parameters for limits, headroom, load, scoring, and period behavior; a mapping from planning nodes to student connection choices; regression comparisons against the synthetic baseline; and a reversible feature flag. No public-data-derived value should silently become an operating limit or evaluator constraint.
