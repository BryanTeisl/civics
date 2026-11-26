"""Complete Statewide Colorado Map & Territories Sync (U.S. Census TIGERweb 2026).

Downloads simplified GeoJSON boundaries for ALL 4 overlapping Colorado government layers
using the official, keyless U.S. Census Bureau TIGERweb ArcGIS REST API:
  1. Counties (all 64 Colorado counties)
  2. Incorporated Places (all ~272 Colorado cities & towns, e.g. Grand Junction, Pueblo, Durango)
  3. Unified School Districts (all ~178 Colorado K-12 districts, e.g. Denver Public Schools, Jeffco, D51)
  4. 119th Congressional Districts (Colorado CD 1–8)

Writes:
  - public/geo/boundaries.geojson (unified simplified GeoJSON used by Turf.js point-in-polygon)
  - public/geo/colorado_territories_manifest.json (feature counts & byte sizes per layer)

Optionally seeds every Colorado county, municipality, and school district into core_civic.db
as `status = 'unclaimed'` (never overwriting existing `active` jurisdictions), so clicking
ANY square mile in Colorado resolves all 4 overlapping tiers on the map.

Usage:
  # 1. Sync full Colorado boundary GeoJSON only (safe, no DB writes)
  python scripts/sync_colorado_territories.py

  # 2. Sync boundaries AND seed all missing Colorado territories into core_civic.db as unclaimed
  python scripts/sync_colorado_territories.py --seed-db --db core_civic.db

  # 3. Also seed only major/curated school districts + all 64 counties + all cities (lighter directory)
  python scripts/sync_colorado_territories.py --seed-db --major-schools-only
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"User-Agent": "CivicPulseBot/3.1 (+https://civics-d03.pages.dev)"}

# Official U.S. Census Bureau TIGERweb REST Endpoints (2026 Vintage, STATE='08' = Colorado)
TIGERWEB_LAYERS: Dict[str, Dict[str, Any]] = {
    "county": {
        "url": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query",
        "out_fields": "GEOID,NAME,BASENAME,CENTLAT,CENTLON",
        "max_allowable_offset": 0.004,
    },
    "city": {
        "url": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query",
        "out_fields": "GEOID,NAME,BASENAME,CENTLAT,CENTLON",
        "max_allowable_offset": 0.002,
    },
    "school_district": {
        "url": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/School/MapServer/0/query",
        "out_fields": "GEOID,NAME,BASENAME,CENTLAT,CENTLON",
        "max_allowable_offset": 0.004,
    },
    "federal": {
        "url": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Legislative/MapServer/8/query",
        "out_fields": "GEOID,NAME,BASENAME,INTPTLAT,INTPTLON",
        "max_allowable_offset": 0.005,
    },
}


def slugify_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def load_curated_aliases(config_path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    p = config_path or (REPO_ROOT / "config" / "jurisdictions" / "colorado_major_groups.json")
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k.lower().strip(): v for k, v in (data.get("aliases_by_census_name") or {}).items()}


def normalize_tiger_feature(
    raw_feature: Dict[str, Any],
    level: str,
    aliases: Dict[str, Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Converts a raw Census TIGERweb GeoJSON feature into a canonical CivicPulse boundary feature."""
    props = raw_feature.get("properties") or {}
    geom = raw_feature.get("geometry")
    if not geom:
        return None

    census_name = (props.get("NAME") or props.get("BASENAME") or "").strip()
    basename = (props.get("BASENAME") or census_name).strip()
    geoid = str(props.get("GEOID") or "").strip()

    lat_raw = props.get("CENTLAT") or props.get("INTPTLAT") or ""
    lon_raw = props.get("CENTLON") or props.get("INTPTLON") or ""
    try:
        lat = round(float(lat_raw), 5) if lat_raw else None
        lon = round(float(lon_raw), 5) if lon_raw else None
    except ValueError:
        lat, lon = None, None

    alias = aliases.get(census_name.lower()) or aliases.get(basename.lower())

    if alias:
        ocd_id = alias["ocd_division_id"]
        display_name = alias["name"]
        portal_url = alias.get("portal_url", "")
        roster_url = alias.get("roster_url", "")
        adapter_type = alias.get("adapter_type", "unclaimed")
    elif level == "county":
        slug = slugify_name(basename)
        ocd_id = f"ocd-division/country:us/state:co/county:{slug}"
        display_name = f"{basename} County Board of Commissioners"
        portal_url, roster_url, adapter_type = "", "", "unclaimed"
    elif level == "city":
        slug = slugify_name(basename)
        ocd_id = f"ocd-division/country:us/state:co/place:{slug}"
        suffix = "Town Council" if "town" in census_name.lower() else "City Council"
        display_name = f"{basename} {suffix}"
        portal_url, roster_url, adapter_type = "", "", "unclaimed"
    elif level == "school_district":
        slug = slugify_name(basename)
        ocd_id = f"ocd-division/country:us/state:co/school_district:{slug}"
        display_name = f"{basename} Board of Education" if "board" not in basename.lower() else basename
        portal_url, roster_url, adapter_type = "", "", "unclaimed"
    elif level == "federal":
        cd_num = re.sub(r"\D", "", basename) or geoid[-2:].lstrip("0") or "1"
        ocd_id = f"ocd-division/country:us/state:co/cd:{int(cd_num)}"
        display_name = f"U.S. House — Colorado District {int(cd_num)}"
        portal_url, roster_url, adapter_type = "https://www.congress.gov/", "", "federal"
    else:
        return None

    return {
        "type": "Feature",
        "properties": {
            "ocd_division_id": ocd_id,
            "division_id": ocd_id,
            "name": display_name,
            "census_name": census_name,
            "geoid": geoid,
            "level": level,
            "latitude": lat,
            "longitude": lon,
            "portal_url": portal_url,
            "roster_url": roster_url,
            "adapter_type": adapter_type,
        },
        "geometry": geom,
    }


def fetch_tigerweb_layer(level: str, timeout: int = 45) -> List[Dict[str, Any]]:
    """Queries TIGERweb for all Colorado (STATE='08') features in a given layer."""
    cfg = TIGERWEB_LAYERS[level]
    params = {
        "where": "STATE='08'",
        "outFields": cfg["out_fields"],
        "outSR": "4326",
        "f": "geojson",
        "geometryPrecision": 4,
        "maxAllowableOffset": cfg["max_allowable_offset"],
    }
    resp = requests.get(cfg["url"], params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("features") or []


def preserve_custom_district_polygons(existing_geo_path: Path) -> List[Dict[str, Any]]:
    """Preserves existing local council-district polygons (e.g., Fort Collins Districts 1–6)."""
    if not existing_geo_path.exists():
        return []
    try:
        old = json.loads(existing_geo_path.read_text(encoding="utf-8"))
        return [
            f
            for f in (old.get("features") or [])
            if (f.get("properties") or {}).get("level") == "district"
        ]
    except Exception:
        return []


def seed_territories_into_db(
    db_path: Path,
    features: List[Dict[str, Any]],
    major_schools_only: bool = False,
    curated_ids: Optional[set] = None,
) -> Dict[str, int]:
    """Inserts missing Colorado territories into core_civic.db as `unclaimed` (never overwrites active)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    existing_ids = {
        r[0] for r in conn.execute("SELECT ocd_division_id FROM jurisdictions").fetchall()
    }

    stats = {"inserted": 0, "skipped_existing": 0, "skipped_federal": 0}
    try:
        for feat in features:
            p = feat.get("properties") or {}
            lvl = p.get("level")
            jid = p.get("ocd_division_id")
            if not jid or lvl in ("federal", "district"):
                stats["skipped_federal"] += 1
                continue
            if major_schools_only and lvl == "school_district" and curated_ids and jid not in curated_ids:
                continue
            if jid in existing_ids:
                stats["skipped_existing"] += 1
                continue

            cols = ["ocd_division_id", "name", "level", "adapter_type", "portal_url", "status"]
            vals = [
                jid,
                p["name"],
                lvl,
                p.get("adapter_type") or "unclaimed",
                p.get("portal_url") or "",
                "unclaimed",
            ]
            if "roster_url" in jur_cols:
                cols.append("roster_url")
                vals.append(p.get("roster_url") or "")
            if "latitude" in jur_cols and "longitude" in jur_cols:
                cols.extend(["latitude", "longitude"])
                vals.extend([p.get("latitude"), p.get("longitude")])

            placeholders = ", ".join("?" for _ in cols)
            conn.execute(
                f"INSERT OR IGNORE INTO jurisdictions ({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            existing_ids.add(jid)
            stats["inserted"] += 1

        conn.commit()
        return stats
    finally:
        conn.close()


def sync_all_colorado_territories(
    geo_dir: Path = REPO_ROOT / "public" / "geo",
    db_path: Optional[Path] = None,
    seed_db: bool = False,
    major_schools_only: bool = False,
) -> Dict[str, Any]:
    geo_dir.mkdir(parents=True, exist_ok=True)
    out_geo = geo_dir / "boundaries.geojson"
    aliases = load_curated_aliases()
    curated_ids = {v["ocd_division_id"] for v in aliases.values()}

    all_features: List[Dict[str, Any]] = preserve_custom_district_polygons(out_geo)
    layer_counts: Dict[str, int] = {"district_preserved": len(all_features)}

    for level in ("county", "city", "school_district", "federal"):
        print(f"[TIGERweb] Fetching Colorado {level} boundaries...")
        raw_feats = fetch_tigerweb_layer(level)
        norm_feats = []
        for rf in raw_feats:
            nf = normalize_tiger_feature(rf, level, aliases)
            if nf:
                norm_feats.append(nf)
        all_features.extend(norm_feats)
        layer_counts[level] = len(norm_feats)
        print(f"  -> Loaded {len(norm_feats)} {level} polygon(s).")

    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "state": "CO",
            "source": "U.S. Census Bureau TIGERweb 2026",
            "layer_counts": layer_counts,
        },
        "features": all_features,
    }
    serialized = json.dumps(fc, separators=(",", ":"))
    out_geo.write_text(serialized, encoding="utf-8")

    manifest = {
        "file": "geo/boundaries.geojson",
        "total_features": len(all_features),
        "bytes": out_geo.stat().st_size,
        "layer_counts": layer_counts,
    }
    (geo_dir / "colorado_territories_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    if seed_db and db_path and db_path.exists():
        manifest["db_seed"] = seed_territories_into_db(
            db_path, all_features, major_schools_only=major_schools_only, curated_ids=curated_ids
        )

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync complete Colorado map & territories from Census TIGERweb.")
    parser.add_argument("--geo-dir", default="public/geo")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--seed-db", action="store_true", help="Insert missing Colorado territories into SQLite as unclaimed")
    parser.add_argument("--major-schools-only", action="store_true", help="When seeding DB, only insert curated major school districts (all 178 still appear on the map)")
    args = parser.parse_args()

    res = sync_all_colorado_territories(
        geo_dir=Path(args.geo_dir),
        db_path=Path(args.db),
        seed_db=args.seed_db,
        major_schools_only=args.major_schools_only,
    )
    print("\n[TERRITORIES] Complete:", json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
