# Gate 2 — ERCOT Public Network Provenance

## Provenance chain

```text
Public source
    ↓
Raw artifact + checksum
    ↓
Normalization
    ↓
ERCOT-oriented geographic inclusion approximation
    ↓
Conservative geographic endpoint construction
    ↓
Validation and diagnostics
    ↓
Canonical public network
    ↓
Browser-oriented artifact
```

## Source 1: HIFLD/DHS transmission lines

**Public catalogue:** [Data.gov — Electric Power Transmission Lines](https://catalog.data.gov/dataset/electric-power-transmission-lines)  
**Service:** [HIFLD ArcGIS FeatureServer layer](https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0)  
**Publisher:** Homeland Infrastructure Foundation-Level Data / U.S. Department of Homeland Security  
**Catalogue update shown:** October 24, 2022  
**Retrieved:** 2026-09-30  
**Format:** GeoJSON from public ArcGIS REST query  
**Raw artifact:** `data/raw/hifld_transmission_lines_texas.geojson`  
**Checksum:** `f624a6512fd24690341175c90824b552c3ffdfb2eb809d6af8658b4cba0fde53`

Query parameters are captured by `tools/ercot_public_network/fetch_hifld.py`:

- `where=1=1`;
- envelope `-106.65,25.83,-93.50,36.50` in WGS84;
- `esriGeometryEnvelope` / `esriSpatialRelIntersects`;
- all public fields;
- geometry returned in WGS84;
- pages of up to 2,000 records.

The layer’s public metadata describes high-voltage transmission lines and warns that the product is approximate/informational rather than an official survey. The pipeline therefore uses its geometry as geographic evidence only.

## Source 2: EIA Form 860

**Public catalogue:** [EIA Form 860 detailed data](https://www.eia.gov/electricity/data/eia860/index.php)  
**Publisher:** U.S. Energy Information Administration  
**Version:** 2025  
**Retrieved:** 2026-09-30  
**Format:** ZIP containing XLSX schedules  
**Raw artifact:** `data/raw/eia8602025.zip`  
**Checksum:** `2b27929d26cc1da9ad6a530da1cac6718cd8496098ee560c4d47cfffd96d08ba`

The build reads:

- `2___Plant_Y2025.xlsx` for plant ID/name, state, county, latitude, longitude, and balancing-authority code;
- `3_1_Generator_Y2025.xlsx` for generator ID, technology, prime mover, and nameplate capacity.

The inclusion rule is `State == TX` and `Balancing Authority Code == ERCO`. Plant and generator records remain separate from the geographic endpoint graph because EIA does not establish a connection to a particular public transmission endpoint.

## Normalization

`normalize.py`:

- preserves source IDs in field-level `source_refs`;
- creates stable SHA-256-derived IDs;
- removes consecutive duplicate geometry points;
- drops malformed geometries with fewer than two valid coordinates;
- treats nonpositive/sentinel voltage values as missing;
- preserves public source properties useful for audit;
- flags line geometries that cross the inclusion bounding box.

## Geographic inclusion

The public HIFLD line source has no ERCOT membership field. The pipeline therefore uses a documented Texas bounding-box approximation for line features. This is not silently labeled as an ERCOT footprint. It may include non-ERCOT Texas infrastructure and may omit cross-boundary infrastructure outside the box.

EIA plants use the stronger public balancing-authority filter `ERCO` in addition to `TX`.

## Topology construction

`topology.py` creates two geographic `derived_endpoint` nodes per normalized line and connects only each line’s own endpoints. It does not:

- convert endpoints into electrical buses;
- merge endpoints spatially;
- connect visually crossing lines;
- infer substation identity;
- clip line geometry into invented boundary nodes.

Every endpoint-based branch is labeled `topology_confidence = source_endpoint`, meaning only that the endpoint came from the source line geometry. It does not mean that HIFLD supplied an electrical bus relationship.

## Validation

`validate.py` checks:

- unique node, branch, plant, and generator IDs;
- branch endpoint references;
- plant-generator references;
- finite geographic coordinates;
- valid longitude/latitude ranges;
- minimum two-point geometry;
- positive/finite voltage values when present.

The test fixture suite separately verifies malformed geometry, duplicate source records, outside-boundary filtering, deterministic IDs, provenance retention, unresolved connectivity, and crossing-without-connectivity.

## Outputs

- `data/processed/ercot_public_network.json`: canonical artifact with full normalized metadata, provenance, geometry, and diagnostics.
- `web/data/ercot-public-network.json`: browser-oriented artifact with the same canonical IDs and geometry, but reduced branch properties. It is not loaded by the current application during Gate 2.

The build sorts records and uses stable IDs, stable JSON serialization, source checksums, and an explicit `--build-date` value. Rebuilding from identical raw artifacts with the same build date is deterministic.

## Reproduction

From the repository root:

```bash
python3 tools/ercot_public_network/fetch_hifld.py \
  --output data/raw/hifld_transmission_lines_texas.geojson

python3 tools/ercot_public_network/build.py \
  --build-date 2026-09-30
```

The EIA ZIP is acquired separately using the command in `data/raw/README.md`. The build fails clearly if either required raw input is absent. No command contacts ERCOT MIS, ECEII, or any restricted endpoint.
