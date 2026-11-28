"""Offline unit tests for CivicPulse v5.1 Feature Parity, Procedural Dedupe, District Merge & Previews."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from civicpulse.pipeline.dedupe_procedural import run_dedupe_and_procedural_cleanup
from civicpulse.pipeline.parity_audit import audit_feature_parity
from civicpulse.pipeline.scale_agenda_previews import generate_scaled_agenda_previews
from civicpulse.pipeline.sync_council_districts import (
    CITY_DISTRICT_SOURCES,
    merge_district_features_into_geojson,
    normalize_district_features,
)


def _seed_test_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (
            ocd_division_id TEXT PRIMARY KEY,
            name TEXT,
            level TEXT,
            status TEXT,
            adapter_type TEXT,
            portal_url TEXT
        );
        CREATE TABLE entities (
            ocd_person_id TEXT PRIMARY KEY,
            jurisdiction_id TEXT,
            name TEXT,
            role TEXT,
            district TEXT,
            website_url TEXT,
            bio_summary TEXT,
            email TEXT,
            photo_url TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            jurisdiction_id TEXT,
            meeting_date TEXT,
            doc_type TEXT,
            title TEXT,
            source_url TEXT,
            raw_text TEXT,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            jurisdiction_id TEXT,
            meeting_date TEXT,
            title TEXT,
            event_type TEXT,
            topic TEXT,
            outcome TEXT,
            impact_score REAL DEFAULT 50.0
        );
        CREATE TABLE entity_actions (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            entity_id TEXT,
            action_type TEXT,
            value TEXT,
            UNIQUE(event_id, entity_id, action_type)
        );

        INSERT INTO jurisdictions VALUES
            ('ocd-division/country:us/state:co/place:fort_collins', 'Fort Collins City Council', 'city', 'active', 'civicclerk', 'https://fortcollins.portal.civicclerk.com/'),
            ('ocd-division/country:us/state:co/place:longmont', 'Longmont City Council', 'city', 'active', 'primegov', 'https://longmont.primegov.com/'),
            ('ocd-division/country:us/state:co/place:boulder', 'Boulder City Council', 'city', 'active', 'primegov', 'https://bouldercolorado.primegov.com/');

        INSERT INTO entities VALUES
            ('rep-fc-1', 'ocd-division/country:us/state:co/place:fort_collins', 'Emily Francis', 'Mayor', 'At-Large', 'https://fcgov.com', 'Emily Francis serves as Mayor with 18 recorded votes.', 'efrancis@fcgov.com', '', 1),
            ('rep-lm-1', 'ocd-division/country:us/state:co/place:longmont', 'Susie Hidalgo-Fahring', 'Mayor', 'At-Large', 'https://longmontcolorado.gov', 'Susie Hidalgo-Fahring serves as Mayor for Longmont.', '', '', 1),
            ('rep-bo-1', 'ocd-division/country:us/state:co/place:boulder', 'Aaron Brockett', 'Mayor', 'At-Large', 'https://bouldercolorado.gov', 'Aaron Brockett serves as Mayor for Boulder.', '', '', 1);

        INSERT INTO events VALUES
            ('ev-1', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-24', 'Consideration of a motion to go into Executive Session for Annual Evaluations', 'motion', 'General', 'Passed', 48.0),
            ('ev-2', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-24', 'Motion to go into Executive Session for Annual Evaluations', 'motion', 'General', 'Passed', 48.0),
            ('ev-3', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-24', 'Ordinance No. 142 Adopting the 2027 Municipal Budget', 'ordinance', 'Budget & Finance', 'Passed', 82.0),
            ('ev-lm-1', 'ocd-division/country:us/state:co/place:longmont', '2026-11-18', 'Ordinance Approving Main Street Rezoning', 'ordinance', 'Zoning & Land Use', 'Passed', 74.0);

        INSERT INTO entity_actions (event_id, entity_id, action_type, value) VALUES
            ('ev-2', 'rep-fc-1', 'vote', 'Yes'),
            ('ev-3', 'rep-fc-1', 'vote', 'Yes');

        INSERT INTO documents (jurisdiction_id, meeting_date, doc_type, title, source_url, raw_text, status) VALUES
            ('ocd-division/country:us/state:co/place:fort_collins', '2026-12-01', 'agenda', 'Regular City Council Meeting', 'https://fcgov.com/agenda', 'Call to Order\nItem 4. Second Reading of Ordinance No. 155 Updating Transit-Oriented Housing Zoning Standards\nItem 5. Resolution Approving Water Utility Rate Adjustment for 2027\nAdjournment', 'pending');
    """)
    conn.commit()
    conn.close()


def test_procedural_dedupe_merges_and_caps(tmp_path: Path):
    db = tmp_path / "test.db"
    _seed_test_db(db)

    res = run_dedupe_and_procedural_cleanup(db_path=db, apply=True)
    assert res["duplicates_merged"] == 1
    assert res["procedural_capped"] == 1

    conn = sqlite3.connect(db)
    ev_rows = conn.execute("SELECT event_id, impact_score, is_procedural FROM events ORDER BY event_id").fetchall()
    conn.close()
    by_id = {r[0]: (r[1], r[2]) for r in ev_rows}
    assert len(by_id) == 3
    assert by_id["ev-3"] == (82.0, 0)
    surviving_exec = by_id.get("ev-2") or by_id.get("ev-1")
    assert surviving_exec == (15.0, 1)


def test_council_district_merge_and_parity_exemptions(tmp_path: Path):
    db = tmp_path / "test.db"
    pub = tmp_path / "public"
    (pub / "geo").mkdir(parents=True)
    (pub / "data").mkdir(parents=True)
    _seed_test_db(db)

    raw_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"DISTRICT": "3"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-105.05, 40.50], [-105.01, 40.50], [-105.01, 40.54], [-105.05, 40.54], [-105.05, 40.50]]],
                },
            }
        ],
    }
    fc_id = "ocd-division/country:us/state:co/place:fort_collins"
    feats = normalize_district_features(fc_id, raw_fc, CITY_DISTRICT_SOURCES[fc_id])
    assert len(feats) == 1
    assert feats[0]["properties"]["district"] == "District 3"

    geo_path = pub / "geo" / "boundaries.geojson"
    merge_res = merge_district_features_into_geojson(geo_path, {fc_id: feats})
    assert merge_res["district_polygons_added"] == 1

    prev_res = generate_scaled_agenda_previews(db_path=db, out_path=pub / "data" / "agenda_previews.json")
    assert prev_res["previews_written"] == 1
    assert prev_res["with_substantive_items"] == 1

    rep = audit_feature_parity(db_path=db, public_dir=pub)
    by_name = {r["name"]: r for r in rep["jurisdictions"]}
    assert by_name["Fort Collins City Council"]["status"] == "at_parity"
    assert by_name["Boulder City Council"]["is_at_large"] is True
    assert by_name["Boulder City Council"]["status"] == "at_parity"
    assert by_name["Longmont City Council"]["voice_vote_only"] is True
    assert by_name["Longmont City Council"]["checks"]["roll_call_votes"] == "exempt"
