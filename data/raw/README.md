# Gate 2 raw public-data artifacts

These files are immutable inputs for the Gate 2 public-data network build. They are public-source artifacts; they are not ERCOT MIS/ECEII/CIM/NOM files.

## 1. HIFLD / DHS transmission lines

- Publisher: Homeland Infrastructure Foundation-Level Data (HIFLD), U.S. Department of Homeland Security.
- Catalogue: https://catalog.data.gov/dataset/electric-power-transmission-lines
- Public service used: `https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0`
- Artifact: `hifld_transmission_lines_texas.geojson`
- Query: public ArcGIS FeatureServer, WGS84 output, envelope `-106.65,25.83,-93.50,36.50`, `resultRecordCount=2000` pagination.
- Retrieval date: 2026-09-30.
- Raw feature count returned: 8,190.
- SHA-256: `f624a6512fd24690341175c90824b552c3ffdfb2eb809d6af8658b4cba0fde53`.
- Service metadata snapshot: `hifld_transmission_lines_metadata.json`.
- Metadata SHA-256: `fd3d6803ed1571fac5e55eba3cf813f2e985bf66d847b0ed137ac8a9c35a4157`.
- Access: public according to the Data.gov catalogue. The HIFLD substation layer is not used; Gate 1 identified it as restricted public.
- Use: transmission-line geometry and public attributes only. HIFLD geometry is informational and does not establish ERCOT bus identity, electrical endpoints, impedance, or ratings.

Acquisition command:

```bash
python3 tools/ercot_public_network/fetch_hifld.py \
  --output data/raw/hifld_transmission_lines_texas.geojson
```

The script contacts only the public HIFLD ArcGIS service. It never contacts ERCOT MIS or restricted endpoints.

## 2. EIA Form 860

- Publisher: U.S. Energy Information Administration.
- Catalogue: https://www.eia.gov/electricity/data/eia860/index.php
- Artifact: `eia8602025.zip`.
- Retrieval date: 2026-09-30.
- File format: ZIP containing XLSX schedules, including plant and generator schedules.
- SHA-256: `2b27929d26cc1da9ad6a530da1cac6718cd8496098ee560c4d47cfffd96d08ba`.
- Access: public EIA bulk download.
- Use: plant coordinates and generator/resource attributes. The pipeline filters plants to Texas (`State=TX`) and EIA balancing-authority code `ERCO`; generators remain separate from geographic network nodes.

Acquisition command:

```bash
curl -L --fail \
  https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip \
  -o data/raw/eia8602025.zip
```

## 3. Raw-data policy

Raw files are not edited by the build. The canonical artifact stores their checksums and source references. If redistribution of a future source version is not appropriate, remove the raw file from distribution and retain the acquisition instructions/checksum instead; the build must then fail clearly when the required input is absent.
