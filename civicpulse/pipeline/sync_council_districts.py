"""Colorado Municipal Council District / Ward GeoJSON Sync (civicpulse/pipeline/sync_council_districts.py).

Pulls official public ArcGIS FeatureServer / Open Data council district polygons
for Colorado's districted active cities, simplifies vertex density for fast
client-side Turf.js checks, and merges them cleanly into `public/geo/boundaries.geojson`
without disturbing existing municipal, county, school district, or federal polygons.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

CITY_DISTRICT_SOURCES: Dict[str, Dict[str, Any]] = {
    "ocd-division/country:us/state:co/place:fort_collins": {
        "name": "Fort Collins City Council",
        "label_prefix": "District",
        "urls": [
            "https://gisweb.fcgov.com/arcgis/rest/services/FCMaps/CouncilDistricts/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
            "https://opendata.arcgis.com/datasets/fcgov::council-districts.geojson",
        ],
        "field_candidates": ["DISTRICT", "DIST", "DIST_NUM", "COUNCIL_DI", "NAME", "District"],
    },
    "ocd-division/country:us/state:co/place:denver": {
        "name": "Denver City Council",
        "label_prefix": "District",
        "urls": [
            "https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services/ODC_ADMN_COUNCIL_DISTRICTS_A/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
            "https://www.denvergov.org/media/gis/DataCatalog/council_districts/geojson/council_districts.geojson",
        ],
        "field_candidates": ["DIST_NUM", "DISTRICT", "COUNCIL_DIST", "NAME", "DIST_NAME"],
    },
    "ocd-division/country:us/state:co/place:colorado_springs": {
        "name": "Colorado Springs City Council",
        "label_prefix": "District",
        "urls": [
            "https://services1.arcgis.com/c1528228a21b40819c70f6f89614a0c1/arcgis/rest/services/City_Council_Districts/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
            "https://gis.coloradosprings.gov/arcgis/rest/services/CityCouncil/CityCouncilDistricts/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["DISTRICT", "DIST_NUM", "COUNCIL_DI", "NAME"],
    },
    "ocd-division/country:us/state:co/place:aurora": {
        "name": "Aurora City Council",
        "label_prefix": "Ward",
        "urls": [
            "https://services1.arcgis.com/1s5865a1b6424667b7f276f1c52a0a87/arcgis/rest/services/Wards/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
            "https://gis.auroragov.org/arcgis/rest/services/OpenData/Wards/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["WARD", "WARD_NUM", "DISTRICT", "NAME"],
    },
    "ocd-division/country:us/state:co/place:greeley": {
        "name": "Greeley City Council",
        "label_prefix": "Ward",
        "urls": [
            "https://gis.greeleygov.com/arcgis/rest/services/OpenData/CityCouncilWards/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["WARD", "WARD_NUM", "DISTRICT", "NAME"],
    },
    "ocd-division/country:us/state:co/place:thornton": {
        "name": "Thornton City Council",
        "label_prefix": "Ward",
        "urls": [
            "https://gis.thorntonco.gov/arcgis/rest/services/OpenData/CouncilWards/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["WARD", "WARD_NO", "DISTRICT", "NAME"],
    },
    "ocd-division/country:us/state:co/place:longmont": {
        "name": "Longmont City Council",
        "label_prefix": "Ward",
        "urls": [
            "https://gis.longmontcolorado.gov/arcgis/rest/services/OpenData/Wards/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["WARD", "WARD_NUM", "NAME"],
    },
    "ocd-division/country:us/state:co/place:arvada": {
        "name": "Arvada City Council",
        "label_prefix": "District",
        "urls": [
            "https://gis.arvada.org/arcgis/rest/services/OpenData/CouncilDistricts/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["DISTRICT", "DIST", "NAME"],
    },
    "ocd-division/country:us/state:co/place:pueblo": {
        "name": "Pueblo City Council",
        "label_prefix": "District",
        "urls": [
            "https://gis.pueblo.us/arcgis/rest/services/CouncilDistricts/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["DISTRICT", "DIST_NUM", "NAME"],
    },
    "ocd-division/country:us/state:co/place:grand_junction": {
        "name": "Grand Junction City Council",
        "label_prefix": "District",
        "urls": [
            "https://gis.gjcity.org/arcgis/rest/services/OpenData/CouncilDistricts/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326",
        ],
        "field_candidates": ["DISTRICT", "DIST", "NAME"],
    },
}


def _simplify_ring(ring: List[List[float]], max_points: int = 80) -> List[List[float]]:
    if len(ring) <= max_points:
        return [[round(float(pt[0]), 4), round(float(pt[1]), 4)] for pt in ring]
    step = max(1, len(ring) // max_points)
    out = [[round(float(ring[i][0]), 4), round(float(ring[i][1]), 4)] for i in range(0, len(ring) - 1, step)]
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out


def simplify_geometry(geom: Dict[str, Any], max_points: int = 80) -> Dict[str, Any]:
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        return {"type": "Polygon", "coordinates": [_simplify_ring(r, max_points) for r in coords]}
    if gtype == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [[_simplify_ring(r, max_points) for r in poly] for poly in coords],
        }
    return geom


def extract_district_label(props: Dict[str, Any], candidates: List[str], prefix: str) -> Optional[str]:
    for key in candidates:
        for pk, pv in props.items():
            if pk.lower() == key.lower() and pv is not None and str(pv).strip():
                raw = str(pv).strip()
                m = re.search(r"([0-9]+|[A-E]|I{1,3}|IV|V|VI)\b", raw, re.I)
                if m:
                    return f"{prefix} {m.group(1).upper()}"
                return raw
    return None


def normalize_district_features(
    parent_ocd_id: str,
    raw_geojson: Dict[str, Any],
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    features_out: List[Dict[str, Any]] = []
    for feat in raw_geojson.get("features") or []:
        geom = feat.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        props = feat.get("properties") or {}
        d_label = extract_district_label(props, cfg["field_candidates"], cfg["label_prefix"])
        if not d_label:
            continue
        slug_tok = re.sub(r"[^a-z0-9]+", "_", d_label.lower()).strip("_")
        features_out.append(
            {
                "type": "Feature",
                "properties": {
                    "ocd_division_id": f"{parent_ocd_id}/council_district:{slug_tok}",
                    "parent_division_id": parent_ocd_id,
                    "level": "district",
                    "name": f"{cfg['name']} — {d_label}",
                    "district": d_label,
                },
                "geometry": simplify_geometry(geom),
            }
        )
    return features_out


def merge_district_features_into_geojson(
    geojson_path: Path,
    new_features_by_parent: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if geojson_path.exists():
        doc = json.loads(geojson_path.read_text(encoding="utf-8"))
    else:
        doc = {"type": "FeatureCollection", "features": []}

    existing = doc.get("features") or []
    replaced_parents = {pid for pid, feats in new_features_by_parent.items() if feats}

    kept = []
    for feat in existing:
        p = feat.get("properties") or {}
        div_id = str(p.get("ocd_division_id") or "")
        is_dist = str(p.get("level") or "").lower() == "district" or "/council_district:" in div_id
        parent_id = p.get("parent_division_id") or re.sub(r"/(council_district|ward):[^/]+$", "", div_id)
        if is_dist and parent_id in replaced_parents:
            continue
        kept.append(feat)

    added_count = 0
    for _, feats in new_features_by_parent.items():
        kept.extend(feats)
        added_count += len(feats)

    doc["features"] = kept
    geojson_path.parent.mkdir(parents=True, exist_ok=True)
    geojson_path.write_text(json.dumps(doc), encoding="utf-8")
    return {
        "cities_updated": len(replaced_parents),
        "district_polygons_added": added_count,
        "total_features": len(kept),
        "file_kb": round(geojson_path.stat().st_size / 1024, 1),
    }


def sync_all_council_districts(
    geojson_path: Path = Path("public/geo/boundaries.geojson"),
    timeout: int = 12,
) -> Dict[str, Any]:
    hdrs = {"User-Agent": "CivicPulseBot/1.0 (https://civics-d03.pages.dev)"}
    fetched: Dict[str, List[Dict[str, Any]]] = {}
    status_by_city: Dict[str, str] = {}

    for parent_id, cfg in CITY_DISTRICT_SOURCES.items():
        city_slug = parent_id.split(":")[-1]
        feats: List[Dict[str, Any]] = []
        last_err = "no_endpoint_returned_features"
        for url in cfg["urls"]:
            try:
                r = requests.get(url, headers=hdrs, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    feats = normalize_district_features(parent_id, data, cfg)
                    if feats:
                        break
                else:
                    last_err = f"HTTP {r.status_code}"
            except Exception as exc:
                last_err = str(exc)[:80]
        if feats:
            fetched[parent_id] = feats
            status_by_city[city_slug] = f"OK ({len(feats)} districts)"
        else:
            status_by_city[city_slug] = f"SKIP ({last_err})"

    summary = merge_district_features_into_geojson(geojson_path, fetched)
    summary["cities"] = status_by_city
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync official Colorado municipal council district polygons")
    parser.add_argument("--geojson", default="public/geo/boundaries.geojson")
    args = parser.parse_args()
    res = sync_all_council_districts(Path(args.geojson))
    print("[COUNCIL-DISTRICTS]", json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
