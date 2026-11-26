"""Offline unit tests for statewide Colorado TIGERweb territory normalization & DB seeding."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.sync_colorado_territories import (
    load_curated_aliases,
    normalize_tiger_feature,
    seed_territories_into_db,
)


def test_normalize_tiger_feature_maps_denver_public_schools_and_grand_junction():
    aliases = load_curated_aliases()

    dps_raw = {
        "type": "Feature",
        "properties": {
            "GEOID": "0803360",
            "NAME": "Denver County School District 1",
            "BASENAME": "Denver County School District 1",
            "CENTLAT": "+39.7392",
            "CENTLON": "-104.9903",
        },
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    }
    dps = normalize_tiger_feature(dps_raw, "school_district", aliases)
    assert dps["properties"]["ocd_division_id"] == "ocd-division/country:us/state:co/school_district:denver_public_schools"
    assert dps["properties"]["name"] == "Denver Public Schools Board of Education"
    assert dps["properties"]["portal_url"] == "https://www.dpsk12.org/page/board-meetings"

    gj_raw = {
        "type": "Feature",
        "properties": {
            "GEOID": "0831660",
            "NAME": "Grand Junction city",
            "BASENAME": "Grand Junction",
            "CENTLAT": "+39.0639",
            "CENTLON": "-108.5506",
        },
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    }
    gj = normalize_tiger_feature(gj_raw, "city", aliases)
    assert gj["properties"]["ocd_division_id"] == "ocd-division/country:us/state:co/place:grand_junction"
    assert gj["properties"]["name"] == "Grand Junction City Council"
    assert gj["properties"]["adapter_type"] == "civicclerk"


def test_seed_territories_never_overwrites_active_jurisdictions(tmp_path: Path):
    db = tmp_path / "co.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (
            ocd_division_id TEXT PRIMARY KEY, name TEXT, level TEXT,
            adapter_type TEXT, portal_url TEXT, roster_url TEXT,
            status TEXT, latitude REAL, longitude REAL
        );
        INSERT INTO jurisdictions VALUES (
            'ocd-division/country:us/state:co/place:fort_collins',
            'Fort Collins City Council', 'city', 'civicclerk',
            'https://fortcollinsco.portal.civicclerk.com/', '', 'active', 40.58, -105.08
        );
    """)
    conn.commit()
    conn.close()

    features = [
        {
            "type": "Feature",
            "properties": {
                "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
                "name": "Fort Collins City Council",
                "level": "city",
                "adapter_type": "unclaimed",
                "portal_url": "",
            },
            "geometry": {},
        },
        {
            "type": "Feature",
            "properties": {
                "ocd_division_id": "ocd-division/country:us/state:co/school_district:denver_public_schools",
                "name": "Denver Public Schools Board of Education",
                "level": "school_district",
                "adapter_type": "unclaimed",
                "portal_url": "https://www.dpsk12.org/page/board-meetings",
            },
            "geometry": {},
        },
    ]

    stats = seed_territories_into_db(db, features)
    assert stats["inserted"] == 1
    assert stats["skipped_existing"] == 1

    conn = sqlite3.connect(db)
    fc_status = conn.execute(
        "SELECT status FROM jurisdictions WHERE ocd_division_id='ocd-division/country:us/state:co/place:fort_collins'"
    ).fetchone()[0]
    dps_status = conn.execute(
        "SELECT status FROM jurisdictions WHERE ocd_division_id='ocd-division/country:us/state:co/school_district:denver_public_schools'"
    ).fetchone()[0]
    conn.close()
    assert fc_status == "active"
    assert dps_status == "unclaimed"
