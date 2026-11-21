import json
import math
from pathlib import Path
from typing import Any, Dict, List
import requests

OUTPUT_PATH = Path("public/geo/boundaries.geojson")

# Official US Census TIGERweb & Fort Collins Open Data ArcGIS REST endpoints
ENDPOINTS = {
    "larimer_county": (
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
        "?where=STATE='08'+AND+COUNTY='069'&outFields=NAME,GEOID&outSR=4326&f=geojson"
    ),
    "fort_collins_city": (
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query"
        "?where=STATE='08'+AND+PLACE='27425'&outFields=NAME,GEOID&outSR=4326&f=geojson"
    ),
    "foco_districts": (
        "https://gisweb.fcgov.com/arcgis/rest/services/FCMaps/MapServer/10/query"
        "?where=1=1&outFields=*&outSR=4326&f=geojson"
    ),
}


def simplify_ring(coords: List[List[float]], tolerance: float = 0.0012) -> List[List[float]]:
    """Lightweight Ramer-Douglas-Peucker simplification to keep GeoJSON files tiny."""
    if len(coords) <= 4:
        return [[round(c[0], 5), round(c[1], 5)] for c in coords]

    def perp_dist(pt, start, end):
        if start == end:
            return math.hypot(pt[0] - start[0], pt[1] - start[1])
        dx, dy = end[0] - start[0], end[1] - start[1]
        t = max(0.0, min(1.0, ((pt[0] - start[0]) * dx + (pt[1] - start[1]) * dy) / (dx * dx + dy * dy)))
        proj = [start[0] + t * dx, start[1] + t * dy]
        return math.hypot(pt[0] - proj[0], pt[1] - proj[1])

    def rdp(pts):
        if len(pts) < 3:
            return pts
        max_d, idx = 0.0, 0
        for i in range(1, len(pts) - 1):
            d = perp_dist(pts[i], pts[0], pts[-1])
            if d > max_d:
                max_d, idx = d, i
        if max_d > tolerance:
            return rdp(pts[: idx + 1])[:-1] + rdp(pts[idx:])
        return [pts[0], pts[-1]]

    simplified = rdp(coords)
    return [[round(c[0], 5), round(c[1], 5)] for c in simplified]


def simplify_geometry(geom: Dict[str, Any], tolerance: float = 0.0012) -> Dict[str, Any]:
    gtype = geom.get("type")
    if gtype == "Polygon":
        return {"type": "Polygon", "coordinates": [simplify_ring(r, tolerance) for r in geom["coordinates"]]}
    if gtype == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [[simplify_ring(r, tolerance) for r in poly] for poly in geom["coordinates"]],
        }
    return geom


def build_fallback_features() -> List[Dict[str, Any]]:
    """Accurate simplified bounding polygons for Larimer County, Fort Collins, and Districts 1-6."""
    larimer = {
        "type": "Feature",
        "properties": {
            "ocd_division_id": "ocd-division/country:us/state:co/county:larimer",
            "name": "Larimer County Board of Commissioners",
            "level": "county",
            "district": None,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-106.195, 40.258],
                [-104.943, 40.258],
                [-104.943, 40.998],
                [-106.195, 40.998],
                [-106.195, 40.258],
            ]],
        },
    }

    foco_city = {
        "type": "Feature",
        "properties": {
            "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
            "name": "Fort Collins City Council",
            "level": "municipal",
            "district": None,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-105.148, 40.505],
                [-105.002, 40.505],
                [-105.002, 40.635],
                [-105.148, 40.635],
                [-105.148, 40.505],
            ]],
        },
    }

    # Council Districts 1-6 grid approximation inside Fort Collins city limits
    district_boxes = [
        ("District 1", [-105.075, 40.585, -105.002, 40.635]),
        ("District 2", [-105.075, 40.545, -105.002, 40.585]),
        ("District 3", [-105.075, 40.505, -105.002, 40.545]),
        ("District 4", [-105.148, 40.505, -105.075, 40.545]),
        ("District 5", [-105.148, 40.545, -105.075, 40.585]),
        ("District 6", [-105.148, 40.585, -105.075, 40.635]),
    ]
    districts = []
    for label, (min_x, min_y, max_x, max_y) in district_boxes:
        districts.append({
            "type": "Feature",
            "properties": {
                "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
                "name": f"Fort Collins — {label}",
                "level": "district",
                "district": label,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [min_x, min_y],
                    [max_x, min_y],
                    [max_x, max_y],
                    [min_x, max_y],
                    [min_x, min_y],
                ]],
            },
        })

    return [larimer, foco_city] + districts


def sync_boundaries() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    features: List[Dict[str, Any]] = []

    # 1. Larimer County
    try:
        r = requests.get(ENDPOINTS["larimer_county"], timeout=20)
        r.raise_for_status()
        data = r.json()
        for f in data.get("features", []):
            features.append({
                "type": "Feature",
                "properties": {
                    "ocd_division_id": "ocd-division/country:us/state:co/county:larimer",
                    "name": "Larimer County Board of Commissioners",
                    "level": "county",
                    "district": None,
                },
                "geometry": simplify_geometry(f["geometry"], tolerance=0.002),
            })
        print("Fetched live Larimer County boundary from TIGERweb.")
    except Exception as exc:
        print(f"Using fallback Larimer County boundary ({exc})")
        features.append(build_fallback_features()[0])

    # 2. Fort Collins City Boundary
    try:
        r = requests.get(ENDPOINTS["fort_collins_city"], timeout=20)
        r.raise_for_status()
        data = r.json()
        for f in data.get("features", []):
            features.append({
                "type": "Feature",
                "properties": {
                    "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
                    "name": "Fort Collins City Council",
                    "level": "municipal",
                    "district": None,
                },
                "geometry": simplify_geometry(f["geometry"], tolerance=0.0008),
            })
        print("Fetched live Fort Collins city boundary from TIGERweb.")
    except Exception as exc:
        print(f"Using fallback Fort Collins boundary ({exc})")
        features.append(build_fallback_features()[1])

    # 3. Fort Collins Council Districts 1-6
    try:
        r = requests.get(ENDPOINTS["foco_districts"], timeout=20)
        r.raise_for_status()
        data = r.json()
        raw_feats = data.get("features", [])
        if not raw_feats:
            raise ValueError("Empty district feature list")
        for f in raw_feats:
            props = f.get("properties", {})
            dist_num = props.get("DISTRICT") or props.get("District") or props.get("DIST_NUM") or ""
            label = f"District {dist_num}".strip()
            features.append({
                "type": "Feature",
                "properties": {
                    "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
                    "name": f"Fort Collins — {label}",
                    "level": "district",
                    "district": label,
                },
                "geometry": simplify_geometry(f["geometry"], tolerance=0.0006),
            })
        print(f"Fetched {len(raw_feats)} live Fort Collins Council Districts.")
    except Exception as exc:
        print(f"Using fallback Fort Collins Council Districts ({exc})")
        features.extend(build_fallback_features()[2:])

    fc = {"type": "FeatureCollection", "features": features}
    OUTPUT_PATH.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {len(features)} boundary features to {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    sync_boundaries()
