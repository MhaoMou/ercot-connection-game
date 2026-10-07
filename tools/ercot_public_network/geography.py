"""Geographic inclusion and conservative endpoint handling."""

from __future__ import annotations

from math import isfinite

# Public-data approximation: ERCOT-balancing-authority plants plus the Texas
# bounding box for HIFLD line geometry. This is intentionally not named "ERCOT
# footprint" because the public line layer has no ERCOT membership field.
TEXAS_BBOX = (-106.65, 25.83, -93.50, 36.50)


def in_texas_bbox(lon: float, lat: float) -> bool:
    west, south, east, north = TEXAS_BBOX
    return west <= lon <= east and south <= lat <= north


def clean_line_coordinates(raw_geometry: dict) -> list[list[float]]:
    if raw_geometry.get("type") == "LineString":
        paths = [raw_geometry.get("coordinates") or []]
    elif raw_geometry.get("type") == "MultiLineString":
        paths = raw_geometry.get("coordinates") or []
    else:
        paths = raw_geometry.get("paths") or []
    points: list[list[float]] = []
    for path in paths:
        for pair in path:
            if len(pair) < 2:
                continue
            lon, lat = float(pair[0]), float(pair[1])
            if not (isfinite(lon) and isfinite(lat)):
                continue
            point = [lon, lat]
            if not points or point != points[-1]:
                points.append(point)
    return points


def geometry_crosses_bbox(points: list[list[float]]) -> bool:
    if not points:
        return False
    inside = [in_texas_bbox(p[0], p[1]) for p in points]
    return any(inside) and not all(inside)
