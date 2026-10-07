# Gate 1.5 — ERCOT Redacted CIM Network Model Audit

**Project:** ERCOT Connection Planning Game  
**Gate:** 1.5 — narrow source/access investigation  
**Audit date:** 2026-09-30  
**Status:** Complete; stopped before Gate 2  
**Decision:** The redacted CIM model is not an ordinary-public source for this project

## 1. Question investigated

Gate 1 identified a potentially stronger source than a composite EIA/HIFLD-style geographic network: ERCOT’s **Preview of Modified Redacted CIM Network Model**. This audit tested whether that model can be obtained by an ordinary public user without restricted credentials and whether it can therefore be used as the primary real-data network source.

The investigation was limited to official ERCOT pages, ERCOT Market Notices, ERCOT data-product metadata, ERCOT public protocols, and ERCOT public CIM documentation. No credentials, cookies, tokens, authenticated MIS access, ECEII material, or full model were used.

## 2. Exact posting discovered

ERCOT’s public CIM16 FAQ identifies the posting as:

> **Preview of Modified Redacted CIM Network Model**

The September 11, 2025 Market Notice links that name to the ERCOT MIS page and says that ERCOT created two CIM16 representations of the August ML2 CIM Network Operations Model: a redacted model on the MIS preview page, and a full representative model for TSPs in the ECEII NMMS Citrix Postings location. The FAQ distinguishes:

- `RTC` files: CIM10 redacted models representing the post-RTC go-live model;
- `CIM16` files: draft representations at the conclusion of the CIM16 project.

The public notice’s link resolves to the MIS data-product path:

`https://mis.ercot.com/secure/data-products/data-product-details?id=np3-451-sg`

The exact file URL, filename, model-load date, and downloadable artifact were not exposed in the public pages reviewed.

## 3. Accessibility and security finding

ERCOT’s official data-product record for the related redacted CIM Network Model and Difference Report reports:

| Field | ERCOT metadata |
|---|---|
| Product | Redacted CIM Network Model and Difference Report |
| EMIL ID | `np3-450-sg` |
| Status | Active |
| Audience | `CRRAH, IMRE, LSE, QSE, RE, TSP, DSP, CP, TO, REC` |
| Security classification | **Secure** |
| ECEII | **Yes** |
| Channel | Secure, EWS |
| File type | ZIP, XML |
| Posting type | Model |
| MIS posting location | `Grid/Modeling/Network Ops Model` |
| Digital-certificate roles | `ICE_E_ADMIN_ECEII`, `MDT_G_VIEW`, `ICE_M_VIEW_ECEII` |
| Access instruction | Authenticate with a digital certificate |

The precise CIM16 preview product is linked by the Market Notice to the MIS secure path `np3-451-sg`; the public page did not expose independent downloadable metadata for that product. The available official evidence is sufficient for the access decision: the preview lives inside MIS secure data-product infrastructure, while the corresponding full model is explicitly identified as ECEII-restricted.

**Conclusion:** an ordinary public user cannot be assumed to download the redacted model. It requires authenticated MIS access and a digital certificate/authorized role. “Redacted” does not mean “openly downloadable.” We therefore stopped before attempting any artifact retrieval.

## 4. Posting/model dates and CIM version

| Item | Evidence and result |
|---|---|
| Initial CIM16 redacted posting | ERCOT FAQ: August 18, 2025 initial draft representations; the FAQ was last updated September 18, 2025 |
| Representative model described in Market Notice | August ML2 CIM Network Operations Model |
| RTC redacted representation | CIM10; file names are identified by `RTC` according to the FAQ |
| CIM16 redacted representation | Draft CIM16 representation; file names are identified by `CIM16` according to the FAQ |
| Current operational model date | Not exposed in the public pages reviewed |
| Exact file version/hash | Not obtainable without the secure artifact |
| Future transition | ERCOT FAQ states all CIM-based models are expected to transition to CIM16 after the project cutover, described as Q1 2027 in the FAQ |

The public ERCOT Modeling page provides CIM10/CIM16 schemas and a CIM10-to-CIM16 mapping document. Those documents establish the format and transition context, not the contents of the restricted preview model.

## 5. Artifact inspection status

No redacted CIM ZIP/XML was downloaded. Consequently, the following are **not verifiable from an ordinary public session**:

- filename and compressed size;
- extracted size and directory/file structure;
- XML/RDF namespaces in the posted artifact;
- object counts;
- model-load metadata inside the file;
- redaction rules and omitted values;
- graph topology and connectivity;
- coordinate coverage;
- electrical-parameter coverage.

This is an intentional stopping result, not a failed parser implementation. Building a parser before lawful access to an approved artifact would create a false impression that the source had been validated.

## 6. What public documentation says the model conceptually contains

ERCOT’s public CIM materials and Nodal Protocols describe a Network Operations Model containing the types of information needed for operations and modeling, including electrical buses, transmission facilities, topology, model changes, load representations, ratings, transformer representations, and other network/equipment data. The CIM16 FAQ specifically notes affected model areas including ratings, transformer modeling, load modeling, ICCP/SCADA modeling, reactive capability, and Remedial Action Scheme representation.

This documents the **schema/conceptual scope** of the model. It does not establish that each field survives redaction or is usable in the secure-preview product, so no missing value is filled from documentation.

## 7. Redaction-survival audit

Because the artifact is not available to an ordinary public user, every artifact-content result below is marked **not verifiable**. This avoids confusing “the CIM schema can represent a field” with “the redacted model actually provides a usable value.”

| Category | Schema/documentation supports the concept? | Redacted artifact observed? | Object count | Usable in this project? |
|---|---:|---:|---:|---:|
| Substations / conducting equipment containers | Yes, conceptually | Not verifiable | Not available | No decision possible |
| Voltage levels | Yes | Not verifiable | Not available | No decision possible |
| Buses / connectivity nodes | Yes, conceptually | Not verifiable | Not available | No decision possible |
| Terminals | Yes, conceptually | Not verifiable | Not available | No decision possible |
| AC line segments | Yes, conceptually | Not verifiable | Not available | No decision possible |
| Transformers | Yes; CIM16 FAQ explicitly discusses transformer-model changes | Not verifiable | Not available | No decision possible |
| Generating units | Yes, conceptually; FAQ discusses BatteryGeneratingUnit | Not verifiable | Not available | No decision possible |
| Loads | Yes; FAQ identifies load modeling as an affected area | Not verifiable | Not available | No decision possible |
| Switches / breakers | Expected in an operations CIM model, but artifact presence was not inspected | Not verifiable | Not available | No decision possible |
| Geographic locations | Not established by the public schema pages as a complete coordinate layer | Not verifiable | Not available | No decision possible |
| Coordinates / PositionPoint | Schema-level possibility is not evidence of populated coordinates | Not verifiable | Not available | No decision possible |
| Nominal voltage | Schema/documentation-level concept | Not verifiable | Not available | No decision possible |
| Impedance (`R`, `X`, `B`) | Schema/modeling concept may support electrical parameters | Not verifiable | Not available | No decision possible |
| Thermal/emergency ratings | ERCOT FAQ explicitly identifies ratings as an affected model area | Not verifiable | Not available | No decision possible |
| Generation capacity | Conceptually expected in resource modeling | Not verifiable | Not available | No decision possible |
| Load magnitude/profile | Conceptually expected, but public protocols also discuss redaction of private-use network load information | Not verifiable | Not available | No decision possible |

## 8. Topology reconstruction feasibility

The desired reconstruction is a relationship chain equivalent to:

```text
Connectivity node A
  -> terminal
  -> conducting equipment
  -> terminal
  -> connectivity node B
```

The public ERCOT documentation makes this type of model plausible, but the secure access boundary prevents testing whether the redacted artifact retains the required relationships. Therefore the following values are **unknown**, not zero:

| Graph diagnostic | Result |
|---|---:|
| Electrical node count | Not verifiable |
| Branch/AC-line count | Not verifiable |
| Transformer count | Not verifiable |
| Switch/breaker count | Not verifiable |
| Connected-component count | Not verifiable |
| Largest-component size | Not verifiable |
| Isolated-node count | Not verifiable |
| Bus-branch reduction rule | Not defined; must not be invented before artifact access and CIM review |

Even if a future authorized researcher obtains a redacted file, a parser must first distinguish raw CIM connectivity from a bus-branch reduction. Switches, breakers, topology islands, transformer terminals, voltage levels, and open/closed equipment states may make the raw graph materially different from the simplified graph expected by the current game.

## 9. Geographic-coordinate feasibility

No coordinate data was inspected. The public sources reviewed do not establish that the redacted preview contains a complete geographic layer. In particular:

- the CIM schema supports the idea of location objects, but schema support is not populated-data evidence;
- no latitude/longitude, projected coordinate system, `Location`, or `PositionPoint` values were observed;
- no names were fuzzy-matched to restricted HIFLD substations;
- no coordinates were invented from facility names.

If a future authorized artifact lacks coordinates, legitimate enrichment would need to use only an independently public, authorized source with a documented join. A name-only fuzzy join would not establish that a CIM connectivity node and a public GIS substation are the same object.

## 10. Electrical-parameter feasibility

No usable electrical values were observed because the artifact was not accessible. The public documentation indicates that the ERCOT model includes or concerns ratings, transformer modeling, loads, and other electrical-model areas, but those statements cannot be used to fill the redacted model.

For this project, the following must remain **unverified** until a lawful artifact is available:

- nominal kV;
- series resistance, reactance, and shunt susceptance;
- thermal and emergency ratings;
- transformer tap/impedance/ratings;
- generator capacity and operating limits;
- load magnitude, distribution, and profiles.

The current game’s headroom, profiles, prices, generator costs, curtailment parameters, `K`, and `μ` remain instructional/evaluator inputs regardless of whether a future public CIM artifact is found.

## 11. Documentation comparison

| Attribute | Public ERCOT documentation says it exists or is modeled | Redacted public artifact contains it | Usable in this app now |
|---|---|---|---|
| Electrical nodes / buses | Yes, through Network Operations Model and protocol language | Not verifiable; secure artifact not obtained | No |
| Topology / terminals | CIM-based network model concept supports it | Not verifiable | No |
| Substations / equipment | Network model and modeling documents describe network equipment | Not verifiable | No |
| AC lines | Transmission facilities are part of the model concept | Not verifiable | No |
| Transformers | Yes; CIM16 FAQ discusses transformer representation changes | Not verifiable | No |
| Generators | Yes; CIM16 FAQ discusses generating-unit classes and ESR representation | Not verifiable | No |
| Loads | Yes; load modeling is explicitly identified in the FAQ and protocols | Not verifiable; some private-use load information is subject to redaction | No |
| Voltage | Expected as part of electrical modeling | Not verifiable | No |
| Impedance | Expected in a power-system model, but not confirmed in the redacted artifact | Not verifiable | No |
| Ratings | Explicitly identified as a model area | Not verifiable | No |
| Coordinates | Not established as complete by reviewed public documentation | Not verifiable | No |

## 12. Comparison with the Gate 1 fallback

| Criterion | Redacted CIM preview | EIA/HIFLD-style public-data fallback |
|---|---|---|
| ERCOT provenance | Potentially excellent | Mixed: EIA/HIFLD plus ERCOT reports |
| Ordinary public access | Not established; official metadata indicates secure/digital-certificate access | EIA plant/generator data is public; each HIFLD layer must be checked individually |
| Topology | Potentially strong, but untested | Geographic connectivity only unless independently derived |
| Coordinates | Unknown | EIA plant coordinates available; line/substation coverage depends on source |
| Electrical parameters | Potentially strong, but untested | Generally incomplete for a full power-flow model |
| Reproducible acquisition now | No, without restricted access | Yes for genuinely public sources after Gate 2 source/terms audit |
| Compliance risk | High if access controls are bypassed | Manageable with per-source terms/provenance checks |
| Suitable immediate Gate 2 foundation | No | Yes, with explicit uncertainty and a separate teaching model |

## 13. Recommendation for Gate 2

Choose **Path C — redacted CIM is unavailable or unusable for this project**.

Gate 2 should proceed with:

```text
public geographic transmission/resource explorer
+
separate reduced teaching/evaluation model
```

The redacted CIM remains useful as public documentation and as a possible future research avenue if the course team later receives legitimate authorization. It should not be used as an application dependency, importer input, or implied source of field completeness now.

The resulting public-data layer should use accurate terminology such as:

- **ERCOT Public-Data Network**;
- **Public Geographic ERCOT Network Approximation**;
- **ERCOT Public-Data Network Explorer**.

It should not be called “the full ERCOT network” unless a future lawful artifact and completeness audit support that claim.

## 14. Reproducibility notes

- Audit date: 2026-09-30.
- Sources were limited to official ERCOT pages and official ERCOT-hosted documents.
- No MIS login was performed.
- No digital certificate was used.
- No secure endpoint was scraped.
- No cookies, tokens, or authenticated browser state were reused.
- No full model or ECEII file was downloaded.
- No parser or object-count script was written because no lawful artifact was available to inspect.
- The access conclusion is based on ERCOT’s public data-product metadata and Market Notice link structure, not on an assumption that “redacted” means public.

## 15. Official sources

- [ERCOT CIM16 + SCR813 FAQ](https://www.ercot.com/files/docs/2025/08/18/CIM16-FAQ-Questions.pdf)
- [ERCOT Modeling page](https://www.ercot.com/gridinfo/modeling)
- [ERCOT Market Notice M-071725-03](https://www.ercot.com/services/comm/mkt_notices/M-071725-03)
- [ERCOT Market Notice M-A073025-01](https://www.ercot.com/services/comm/mkt_notices/M-A073025-01)
- [ERCOT Redacted CIM Network Model and Difference Report data-product record](https://www.ercot.com/mp/data-products/data-product-details?id=NP3-450-SG)
- [ERCOT 2024 Nodal Protocols](https://www.ercot.com/files/docs/2024/04/25/May%201%2C%202024%20Nodal%20Protocols.pdf)
- [ERCOT Nodal Protocol Revision Requests](https://www.ercot.com/mktrules/issues/reports/nprr)

