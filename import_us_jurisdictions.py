import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

from db import get_connection, init_db

BOUNDARIES_PATH = Path("public/geo/boundaries.geojson")

# Built-in Colorado Front Range unclaimed cities (used if no external GeoJSON path is passed)
DEFAULT_CO_UNCLAIMED = [
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:loveland",
        "name": "Loveland City Council",
        "level": "municipal",
        "lat": 40.3978,
        "lng": -105.0750,
        "parent_division_id": "ocd-division/country:us/state:co/county:larimer",
        "portal_url": "https://cilovelandco.civicweb.net/Portal/",
        "bbox": [-105.135, 40.360, -105.015, 40.445],
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:greeley",
        "name": "Greeley City Council",
        "level": "municipal",
        "lat": 40.4233,
        "lng": -104.7091,
        "parent_division_id": None,
        "portal_url": "https://greeleyco.portal.civicclerk.com/",
        "bbox": [-104.810, 40.380, -104.650, 40.460],
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:longmont",
        "name": "Longmont City Council",
        "level": "municipal",
        "lat": 40.1672,
        "lng": -105.1019,
        "parent_division_id": None,
        "portal_url": "https://longmontco.portal.civicclerk.com/",
        "bbox": [-105.165, 40.130, -105.040, 40.205],
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:boulder",
        "name": "Boulder City Council",
        "level": "municipal",
        "lat": 40.0150,
        "lng": -105.2705,
        "parent_division_id": None,
        "portal_url": "https://bouldercolorado.gov/government/city-council",
        "bbox": [-105.310, 39.975, -105.210, 40.065],
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:windsor",
        "name": "Windsor Town Board",
        "level": "municipal",
        "lat": 40.4775,
        "lng": -104.9014,
        "parent_division_id": "ocd-division/country:us/state:co/county:larimer",
        "portal_url": "https://www.windsorgov.com/",
        "bbox": [-104.960, 40.445, -104.855, 40.515],
    },
]


def import_unclaimed(geojson_file: str = "") -> None:
    init_db()
    conn = get_connection()

    existing_geo = {"type": "FeatureCollection", "features": []}
    if BOUNDARIES_PATH.exists():
        try:
            existing_geo = json.loads(BOUNDARIES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing_div_ids = {
        f.get("properties", {}).get("ocd_division_id")
        for f in existing_geo.get("features", [])
        if f.get("properties", {}).get("level") != "district"
    }

    added_db = 0
    added_geo = 0

    if geojson_file and Path(geojson_file).exists():
        # Import from a state-filtered arthurgailes/us_jurisdictions GeoJSON export
        raw = json.loads(Path(geojson_file).read_text(encoding="utf-8"))
        for feat in raw.get("features", []):
            props = feat.get("properties", {})
            geoid = str(props.get("GEOID") or props.get("geoid") or "").strip()
            raw_name = str(props.get("NAME") or props.get("jurisdiction_name") or "").strip()
            if not geoid or not raw_name:
                continue

            slug = raw_name.lower().replace(" ", "_").replace("-", "_")
            div_id = f"ocd-division/country:us/state:co/place:{slug}"
            # Compute approximate centroid from first ring
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [[]])
            ring = coords[0][0] if geom.get("type") == "MultiPolygon" else coords[0]
            if not ring:
                continue
            lng = round(sum(p[0] for p in ring) / len(ring), 5)
            lat = round(sum(p[1] for p in ring) / len(ring), 5)

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO jurisdictions (
                    ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier, status
                ) VALUES (?, ?, 'municipal', ?, ?, 'unclaimed', '', 'slow', 'unclaimed')
                """,
                (div_id, f"{raw_name} City Council", lat, lng),
            )
            if cur.rowcount > 0:
                added_db += 1

            if div_id not in existing_div_ids:
                existing_geo["features"].append(
                    {
                        "type": "Feature",
                        "properties": {
                            "ocd_division_id": div_id,
                            "name": f"{raw_name} City Council",
                            "level": "municipal",
                            "district": None,
                        },
                        "geometry": geom,
                    }
                )
                existing_div_ids.add(div_id)
                added_geo += 1
    else:
        # Use lightweight built-in Colorado Front Range unclaimed cities
        for item in DEFAULT_CO_UNCLAIMED:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO jurisdictions (
                    ocd_division_id, name, level, lat, lng, adapter_type,
                    portal_url, poll_tier, parent_division_id, status
                ) VALUES (?, ?, ?, ?, ?, 'unclaimed', ?, 'slow', ?, 'unclaimed')
                """,
                (
                    item["ocd_division_id"],
                    item["name"],
                    item["level"],
                    item["lat"],
                    item["lng"],
                    item["portal_url"],
                    item["parent_division_id"],
                ),
            )
            if cur.rowcount > 0:
                added_db += 1

            if item["ocd_division_id"] not in existing_div_ids:
                min_x, min_y, max_x, max_y = item["bbox"]
                existing_geo["features"].append(
                    {
                        "type": "Feature",
                        "properties": {
                            "ocd_division_id": item["ocd_division_id"],
                            "name": item["name"],
                            "level": item["level"],
                            "district": None,
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
                    }
                )
                existing_div_ids.add(item["ocd_division_id"])
                added_geo += 1

    conn.commit()
    conn.close()

    BOUNDARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOUNDARIES_PATH.write_text(json.dumps(existing_geo, separators=(",", ":")), encoding="utf-8")
    print(f"Added {added_db} unclaimed jurisdiction(s) to DB and {added_geo} polygon(s) to {BOUNDARIES_PATH}.")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    import_unclaimed(arg)
