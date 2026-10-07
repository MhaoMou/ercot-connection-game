# Gate 1 — Real ERCOT Public-Data Audit

**Project:** ERCOT Connection Planning Game  
**Gate:** 1 of 6 — data audit only  
**Audit date:** 2026-09-30  
**Status:** Complete; application changes intentionally deferred

## 1. Executive conclusion

The complete, current ERCOT operational or planning bus-branch model required for a faithful full-network AC/linearized power-flow evaluator was **not verified as publicly downloadable and reusable** during this audit. ERCOT publishes extensive modeling documentation, planning reports, transmission studies, project artifacts, and operational/market reports, but those public artifacts are not equivalent to a complete machine-readable model containing every bus, branch endpoint, transformer, impedance, rating, contingency, load, generator-to-bus mapping, and time-varying operating assumption.

The most defensible public-data target is therefore a **two-layer system**:

1. **Real/public network explorer:** a geographically grounded ERCOT-region view assembled from lawful public government and ERCOT sources, with provenance and uncertainty attached to every imported object. This can support map exploration, search, regional context, named facilities where public, and scale demonstrations.
2. **Derived teaching/planning model:** a smaller, explicitly derived graph used by the course evaluator. It may use public geometry and named facilities as its backbone, but its electrical parameters, headroom, load profiles, interconnection limits, prices, curtailment rules, and scoring coefficients must remain clearly labeled as instructional assumptions unless an authoritative public source supports them.

This is a **Level C public-data approximation with a path toward partial Level B fidelity**, not a claim that the application can safely become a full ERCOT operational replica. The existing 32-bus/48-corridor fixture is suitable as a teaching prototype but is not a defensible representation of ERCOT scale.

No application scenario, evaluator, map, API contract, or UI was changed for Gate 1.

## 2. Scope and method

This audit asked four questions:

- What public sources can establish the physical/geographic network and its scale?
- Which fields are actually available without credentials or restricted access?
- Which fields would still need derivation or instructional assumptions?
- What architecture keeps the public network useful without pretending it is an authoritative operational model?

The review prioritized official ERCOT pages and public artifacts, then federal government data. It did not use credentials, authenticated ERCOT/MIS access, ECEII/CEII material, leaked files, or attempts to bypass an access boundary. URLs and source roles are recorded below. “Public” means reachable through the cited public page at audit time; it does not imply that every linked file has identical licensing, update cadence, or permission for redistribution.

## 3. Source inventory

| Source | Publisher / status | What it can support | Important limitation for this project | Gate-1 disposition |
|---|---|---|---|---|
| [ERCOT Modeling](https://www.ercot.com/gridinfo/modeling) | ERCOT; public modeling documentation | CIM16/CIM10 Network Operations Model schema references, modeling expectations, DER modeling material, process context | Public schema/process documents do not establish that a current complete bus-branch dataset with electrical parameters is publicly downloadable | Use as model-governance and field-semantics reference; do not infer a full model from it |
| [ERCOT Grid Information](https://www.ercot.com/gridinfo) | ERCOT; public information hub | Links to the Data Access Portal, Electrical Bus to Hub List, State Estimator reports, Network Operations Model change schedule, and related grid information | Catalogue/report availability is not proof of complete topology or unrestricted bulk access to operational model data | Use to inventory authorized public artifacts in Gate 2 |
| [ERCOT Planning](https://www.ercot.com/gridinfo/planning/) | ERCOT; public planning reports and downloads | Long-Term System Assessment, Regional Transmission Plan artifacts, constraints/needs reports, public project studies, maps, and selected ZIP/PDF/XLSX files | Coverage is study-, project-, or report-specific; diagrams do not provide complete machine-readable endpoints, impedances, ratings, or bus IDs | Use for cross-checking names, voltage classes, corridors, projects, and regional context |
| [ERCOT System Planning / Market Reports](https://www.ercot.com/gridinfo/sysplan/) | ERCOT; public reports | Projected loads, resource adequacy, transmission constraints/plans, and the Transmission Project and Information Tracking spreadsheet | These reports are not a complete operational model and may aggregate or omit sensitive details | Use as provenance and scenario-context material, not as the sole importer |
| [ERCOT Resource Adequacy](https://www.ercot.com/gridinfo/resource/index.html) | ERCOT; public resource reports | Monthly Generator Interconnection Status Reports, capacity trends, and public interconnection-cost/reporting artifacts | Exact generator-to-ERCOT-bus mapping and complete electrical generator parameters were not verified | Use to cross-check resource classes, status, and public capacity context |
| [ERCOT Resource Integration](https://www.ercot.com/services/rq/integration/) | ERCOT; public interconnection-process page | Public description of the interconnection process and RIOO/RIOO-RS data flow into the Network Model | Process documentation and public attachments do not establish an unrestricted full network-model export | Use to document why interconnection/resource data is not automatically equivalent to public bus-level data |
| [Network Data Support Working Group](https://www.ercot.com/committees/ros/ndswg/) | ERCOT; public governance page | Confirms that NDSWG coordinates transmission-model data supporting the real-time operational model, including topology changes and data accuracy | Governance evidence is not a public topology dataset | Use to distinguish model stewardship from public release |
| [NPRR290](https://www.ercot.com/mktrules/issues/NPRR290) | ERCOT; public historical issue page | Historical evidence that daily PSS/E transmission data packages were specified for the MIS Public Area, including topology, contingencies, and mappings | Historical language does not prove current accessibility, license, completeness, or authorization; this project must not automate or bypass MIS/authenticated/ECEII boundaries | Record as architectural/historical evidence only; verify any current public route manually before considering it |
| [ERCOT Company Profile](https://www.ercot.com/about/profile/index.html) | ERCOT; public profile | High-level scale context: more than 54,100 miles of transmission lines and 1,250 generation units are stated on the profile page | These are system-level facts, not exact counts of public GIS features, buses, branches, or model elements | Use only as scale context; exact imported counts belong to Gate 2/3 audit |
| [EIA Form 860 detailed data](https://www.eia.gov/electricity/data/eia860/index.php) | U.S. Energy Information Administration; public ZIP/XLS data | Plant- and generator-level records for existing/planned resources at plants with at least 1 MW combined nameplate capacity; generator type, fuel, capacity, status, and related attributes | Plant/generator records do not provide ERCOT bus IDs, branch endpoints, impedances, or a complete transmission model | Strong candidate for public generator/resource enrichment in Gate 2 |
| [EIA location FAQ](https://www.eia.gov/tools/faqs/faq.php?id=567&t=1) | EIA; public authoritative clarification | EIA states that plant coordinates are in EIA-860/860M, transmission-line data/shapefiles are available through HIFLD, and EIA/HIFLD do not publish electric-substation locations | Explicitly confirms the substation gap; EIA data is not an ERCOT electrical network model | Use as a hard boundary in importer design |
| [HIFLD Electric Substations catalog entry](https://catalog.data.gov/dataset/electric-substations-c633a) | HIFLD / DHS via Data.gov; catalog metadata | Identifies the federal electric-substation dataset and its provenance/license link | Current metadata marks access level as **restricted public**; it must not be downloaded or automated without confirming authorized access | Do not assume availability; investigate only through an authorized route in a later gate |
| [HIFLD Next collections](https://hifld.publicenvirodata.org/collections) | Public HIFLD-related catalogue interface | Current catalogue context for HIFLD collections | Catalogue presence does not prove that a specific layer is open, complete, or suitable for redistribution | Candidate discovery only; verify each layer and terms before use |
| [Census cartographic boundary files](https://www.census.gov/geographies/mapping-files/2025/geo/carto-boundary-file.html) | U.S. Census Bureau; public basemap geography | State/county/boundary context for map rendering | Geography is not electrical infrastructure and must never be presented as network topology | Basemap only; already used by the current application |

### 3.1 Public source interpretation

The strongest public combination currently identified is:

- **EIA-860/860M** for public plant/generator attributes and coordinates;
- **HIFLD transmission-line geometry**, if the exact current layer and terms are confirmed through an authorized public source in Gate 2;
- **ERCOT public planning reports and project artifacts** for names, voltage-class context, project/corridor cross-checks, and provenance;
- **Census geography** for visual context only.

That combination can produce a serious geographic network explorer. It still does not supply a complete ERCOT electrical network model suitable for claiming authoritative power-flow feasibility.

## 4. Field-availability audit

The table below describes what is known from the reviewed public sources, not what the final importer is allowed to assume.

| Required field | Public availability assessment | Safe use in the game |
|---|---|---|
| ERCOT bus ID / official bus name | Not verified as an unrestricted current public field in the reviewed material | Keep separate from public GIS feature IDs; use only after an authorized, documented source is confirmed |
| Substation/facility name | May appear in public project reports and GIS layers; coverage and identity quality vary | Display as a public facility label with source/provenance and confidence |
| Latitude/longitude | Public plant coordinates are available through EIA; transmission/substation geometry may be available through specific government GIS layers, subject to access | Use for geographic exploration, not automatic ERCOT bus identity |
| Nominal voltage / kV | Often present in transmission GIS attributes or public diagrams, but completeness and semantics must be audited | Use as a display/filter field with “reported/unknown” states; do not silently fill missing values |
| Transmission line geometry | EIA directs users to HIFLD for transmission-line data; exact current layer, terms, and completeness must be checked in Gate 2 | Use for map geometry after provenance and coverage checks |
| Electrical line endpoints | Geographic line geometry does not guarantee authoritative ERCOT bus-to-bus endpoints | Derive only as an explicitly uncertain GIS connectivity graph, or keep unresolved |
| Line thermal/emergency ratings | Not verified as complete in public sources reviewed | Treat as unavailable; instructional limits may be added only in the derived teaching model |
| Resistance/reactance/susceptance | Not verified as complete in public sources reviewed | Do not claim AC/DC power-flow fidelity from public GIS alone |
| Transformer identity/parameters | Not verified as complete in public sources reviewed | Keep out of the real/public layer unless a lawful authoritative source is confirmed |
| Generator plant/resource ID | EIA provides plant/generator identifiers; ERCOT public reports provide resource/interconnection context at varying granularity | Preserve source-native IDs and a provenance join; do not equate EIA and ERCOT IDs without evidence |
| Generator-to-ERCOT-bus mapping | Not verified as public and complete | Keep unmapped or map only to a public geographic facility with an explicit uncertainty flag |
| Generator capacity/fuel/status | Public through EIA-860 and ERCOT public resource reports, subject to date and definition alignment | Good candidate for public resource enrichment and teaching metadata |
| Bus-level load | ERCOT publishes system/zone/load-related reports, but a complete public bus-level load model was not verified | Use aggregate/zone context or derive teaching loads explicitly |
| Time-varying load/generation profiles | Public aggregate reports exist; a complete bus-level synchronized profile set was not verified | Keep profiles as scenario assumptions or document their derivation |
| Prices / IT value / curtailment coefficients | These are game/evaluation inputs, not physical public-network fields | Keep in scenario configuration and label as instructional/economic assumptions |
| Contingencies / voltage limits / security criteria | Historical/public planning documents may describe study assumptions, but completeness for a current operational model was not verified | Do not claim N-1 or operational security evaluation unless separately implemented and sourced |

## 5. Expected scale

ERCOT’s public profile gives useful order-of-magnitude context: it states that the ERCOT grid connects more than **54,100 miles of transmission lines** and approximately **1,250 generation units**. Those figures establish that the current 32-bus/48-corridor fixture is a deliberately small teaching abstraction, not a scale proxy.

The audit does **not** invent an exact public-network count. The number of imported facilities, line features, plant records, and connected components will depend on the selected source versions, spatial filter, deduplication rules, and whether features represent lines, circuits, segments, substations, taps, or other GIS objects. Exact counts belong to the Gate 2 scale audit after source acquisition is lawful and reproducible.

The expected software implications are:

- a full geographic layer may contain thousands of visible records and potentially many more SVG/DOM elements than the current fixture;
- the map must use level-of-detail rendering, viewport filtering, simplified geometry, and selective hit targets;
- search and filtering should be primary interaction mechanisms;
- the evaluator must never iterate over every geographic feature when a reduced teaching graph is sufficient;
- public-network objects need source IDs, source timestamps, provenance, confidence, and “display-only vs evaluator-eligible” flags.

## 6. Security, access, and licensing boundaries

The migration must follow these rules:

1. Do not use credentials, authenticated MIS downloads, ECEII/CEII data, private utility files, leaked archives, or reverse-engineered access paths.
2. Do not treat a historical or public-facing ERCOT page as blanket permission to fetch every linked artifact programmatically.
3. Verify the access level and reuse terms for each HIFLD/EIA/ERCOT file at import time. Data.gov currently labels the HIFLD Electric Substations catalogue entry “restricted public,” so it is not a default open-import source.
4. Preserve source attribution, retrieval date, version/file hash, and license/terms in importer manifests.
5. Never merge public GIS objects into “official ERCOT buses” merely because names or coordinates look similar. Such joins require documented evidence and a confidence field.
6. If a public source is later withdrawn, restricted, or materially changed, the repository must retain only what is permitted and record the failure rather than silently substituting an unverified mirror.

## 7. Recommended architecture

### 7.1 Public Network Explorer

This layer is for geographic and data-literacy teaching:

- public-source map features and source-native identifiers;
- transmission geometry where legally and technically verified;
- public generator/plant points from EIA;
- ERCOT report-derived labels and project references;
- explicit `source`, `retrieved_at`, `source_version`, `confidence`, and `is_evaluator_eligible` metadata;
- scalable map rendering and search;
- no claim that a displayed line is an authoritative ERCOT branch with known electrical parameters.

### 7.2 Teaching / Planning Model

This layer is for the competitive game and RL environment:

- a reduced graph derived from public geography and named facilities;
- a documented selection rule for included buses, corridors, plants, and study periods;
- explicit synthetic/derived fields for headroom, load profiles, interconnection limits, prices, IT value, generator cost, curtailment, intervention budget `K`, and depth `μ`;
- the existing evaluator semantics preserved until a separately approved migration changes them;
- a model manifest that states which values are observed, derived, calibrated, or instructional assumptions.

This separation is necessary for scientific honesty and for stable classroom scoring. A larger map should not silently turn the current teaching evaluator into an under-specified “real ERCOT” power-flow solver.

## 8. Gate plan after this audit

### Gate 2 — source selection and scale audit

- Confirm the exact lawful public HIFLD transmission-line route, current field schema, and terms.
- Confirm whether any usable substation layer is genuinely accessible without special permission; otherwise use public project/report names, EIA plants, and an explicitly incomplete facility layer.
- Acquire only approved public artifacts through a reproducible importer.
- Record feature counts, geographic extent, duplicate rates, missingness, geometry validity, and source versions.
- Produce `docs/REAL_ERCOT_SCALE_AUDIT.md`.
- Do not replace the production fixture yet.

### Gate 3 — data architecture and importer pipeline

- Add raw-source manifests and immutable provenance records.
- Normalize source-native IDs without pretending they are ERCOT bus IDs.
- Build a versioned public-network artifact and a separate derived teaching-model artifact.
- Add validation for coordinate systems, geometry, missing fields, duplicate facilities, and source drift.
- Keep the current application fixture as the active scenario until a later gate.

### Gate 4 — teaching-network design and evaluator migration

- Decide which public/derived facilities become evaluator-eligible teaching buses and corridors.
- Decide whether path selection is geographic, reduced-graph, or an aggregate interface; do not create thousands of corridor checkboxes by default.
- Define how instructional electrical parameters are generated, calibrated, and disclosed.
- Preserve or explicitly version the existing scoring/evaluator behavior.
- Produce `docs/REAL_ERCOT_EVALUATOR_MIGRATION.md` before changing evaluation code.

### Gate 5 — application integration

- Add the public-network explorer and scalable rendering.
- Add the versioned teaching scenario only after the evaluator migration is approved.
- Preserve Map → Plan, Evaluation → Map, stale-result handling, classroom mode, and accessibility semantics.
- Add regression tests and provenance displays.

### Gate 6 — cleanup and release audit

- Remove obsolete synthetic resources only when replacement behavior is stable and explicitly approved.
- Run full scenario, evaluator, map, API, accessibility, responsive, and data-provenance regression checks.
- Publish a final data card describing source dates, coverage, uncertainty, and known omissions.

## 9. Required decisions before implementation

The following decisions should be made at Gate 2, not guessed in code:

- Is the public-network map intended to show transmission lines only, or lines plus public plant/resource points?
- Is an authorized HIFLD substation layer available to the course team, or must substations remain an incomplete/report-derived layer?
- What geographic boundary defines the target: ERCOT footprint, Texas state boundary, or an ERCOT approximation clipped to Texas?
- What is the desired evaluator scale: a few dozen, a few hundred, or a larger reduced graph?
- Which electrical fields are intentionally instructional rather than observed?
- Which source/version will be frozen for a semester so student rankings remain reproducible?

## 10. Audit answers to the migration deliverables

1. **Most complete public network available:** likely a composite public geographic network, not a verified complete ERCOT operational model. EIA generator/plant data plus a lawful HIFLD transmission-line layer and ERCOT public planning artifacts is the strongest current direction.
2. **Public vs restricted fields:** plant/generator attributes and coordinates are public through EIA; transmission geometry may be public through HIFLD; substation access is currently marked restricted public; ERCOT bus IDs, authoritative bus-branch endpoints, impedances, ratings, and complete bus-level loads were not verified as unrestricted.
3. **Scale:** ERCOT public profile reports >54,100 transmission miles and ~1,250 generation units. Exact imported feature counts are unknown until Gate 2.
4. **Current fixture comparison:** 32 buses and 48 representative corridors are a small synthetic teaching abstraction, not an ERCOT-scale network.
5. **Architecture:** separate a scalable public Network Explorer from a reduced, versioned Teaching/Planning Model.
6. **Evaluator recommendation:** keep feasibility and revenue evaluation on the reduced teaching model; do not claim full-network power-flow feasibility from public GIS geometry.
7. **Map recommendation:** use level-of-detail, viewport filtering, simplified geometries, search, and selective interaction; do not render a full feature inventory as one interactive DOM graph.
8. **Data pipeline:** use versioned raw manifests, source-native IDs, normalization, validation, provenance, and explicit confidence/eligibility flags.
9. **Security:** no restricted/authenticated data, credentials, ECEII/CEII, leaked files, or bypasses.
10. **Licensing:** verify and record terms per downloaded artifact; do not assume all ERCOT, HIFLD, or EIA materials are interchangeable or redistributable.
11. **Next gate:** perform the lawful source-selection and scale audit, then report exact counts and field completeness before changing the app.
12. **Stop condition:** Gate 1 is complete and this migration stops here pending approval for Gate 2.

## 11. Sources consulted

- [ERCOT Modeling](https://www.ercot.com/gridinfo/modeling)
- [ERCOT Grid Information](https://www.ercot.com/gridinfo)
- [ERCOT Planning](https://www.ercot.com/gridinfo/planning/)
- [ERCOT System Planning / Market Reports](https://www.ercot.com/gridinfo/sysplan/)
- [ERCOT Resource Adequacy](https://www.ercot.com/gridinfo/resource/index.html)
- [ERCOT Resource Integration](https://www.ercot.com/services/rq/integration/)
- [ERCOT Network Data Support Working Group](https://www.ercot.com/committees/ros/ndswg/)
- [ERCOT NPRR290](https://www.ercot.com/mktrules/issues/NPRR290)
- [ERCOT Company Profile](https://www.ercot.com/about/profile/index.html)
- [EIA Form EIA-860 detailed data](https://www.eia.gov/electricity/data/eia860/index.php)
- [EIA FAQ: location of electric power plants and transmission lines](https://www.eia.gov/tools/faqs/faq.php?id=567&t=1)
- [Data.gov: HIFLD Electric Substations](https://catalog.data.gov/dataset/electric-substations-c633a)
- [HIFLD Next collections](https://hifld.publicenvirodata.org/collections)
- [U.S. Census Bureau cartographic boundary files](https://www.census.gov/geographies/mapping-files/2025/geo/carto-boundary-file.html)

## 12. Gate 1.5 redacted CIM investigation

Gate 1.5 investigated ERCOT’s **Preview of Modified Redacted CIM Network Model** before committing to the EIA/HIFLD-style fallback. ERCOT’s public CIM16 FAQ and Market Notice confirm that preview representations exist in MIS and distinguish them from full models posted to ECEII locations. However, the official ERCOT data-product metadata for the redacted CIM Network Model and Difference Report marks the product **Secure**, **ECEII = Yes**, lists authorized market-participant audiences, requires a digital certificate, and places the product in a secure MIS channel.

The public Market Notice link resolves to an MIS secure data-product path; no ordinary-public downloadable ZIP/XML artifact was exposed. We therefore did not authenticate, download, scrape, inspect, or count the redacted model. The CIM schemas and public documentation establish what the model can conceptually represent, but they do not prove which objects or values survive redaction.

This does not change the Gate 1 recommendation. For the current project, proceed with a lawful public-data network explorer plus a separate reduced teaching/evaluation model. Treat the redacted CIM as a possible future authorized research source, not as an application dependency or verified public network dataset. The complete investigation is recorded in [`ERCOT_REDACTED_CIM_AUDIT.md`](ERCOT_REDACTED_CIM_AUDIT.md).

