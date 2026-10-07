"""Fetch the public HIFLD transmission-line subset used by Gate 2.

This is explicit and opt-in. It contacts only the public ArcGIS FeatureServer
listed in the provenance report; it never contacts ERCOT MIS or restricted
endpoints.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

SERVICE = "https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0/query"


def fetch(output: Path, page_size: int = 2000) -> None:
    features = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "geometry": "-106.65,25.83,-93.50,36.50",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
            "f": "geojson",
        }
        url = SERVICE + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=120) as response:
            page = json.load(response)
        page_features = page.get("features", [])
        features.extend(page_features)
        if len(page_features) < page_size:
            break
        offset += len(page_features)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"type": "FeatureCollection", "features": features}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"features": len(features), "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/raw/hifld_transmission_lines_texas.geojson"))
    args = parser.parse_args()
    fetch(args.output)
