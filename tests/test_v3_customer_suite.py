"""Offline unit tests for CivicPulse v3 Customer Suite (v3_intelligence.py)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from civicpulse.pipeline.v3_intelligence import run_v3_intelligence


def test_v3_intelligence_generates_digest_alignment_and_contacts(tmp_path: Path):
    db = tmp_path / "v3.db"
    pub = tmp_path / "public"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (ocd_division_id TEXT PRIMARY KEY, name TEXT, portal_url TEXT, status TEXT);
        CREATE TABLE entities (ocd_person_id TEXT PRIMARY KEY, jurisdiction_id TEXT, name TEXT, role TEXT, district TEXT, email TEXT, phone TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT, title TEXT,
            topic TEXT, outcome TEXT, yes_count INTEGER, no_count INTEGER,
            impact_score INTEGER, plain_summary TEXT, source_url TEXT, qa_status TEXT
        );
        CREATE TABLE entity_actions (action_id INTEGER PRIMARY KEY, event_id TEXT, entity_id TEXT, action_type TEXT);

        INSERT INTO jurisdictions VALUES ('ocd-division/country:us/state:co/place:fort_collins', 'Fort Collins City Council', 'https://fortcollinsco.portal.civicclerk.com/', 'active');
        INSERT INTO entities VALUES ('p1', 'ocd-division/country:us/state:co/place:fort_collins', 'Rep Alpha', 'Mayor', 'At-Large', 'alpha@fcgov.com', '', 1);
        INSERT INTO entities VALUES ('p2', 'ocd-division/country:us/state:co/place:fort_collins', 'Rep Beta', 'Councilmember', 'D1', '', '', 1);
        INSERT INTO entities VALUES ('p3', 'ocd-division/country:us/state:co/place:fort_collins', 'Rep Gamma', 'Councilmember', 'D2', '', '', 1);

        INSERT INTO events VALUES ('e1', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-10', 'Ordinance 44 Zoning Update', 'Zoning & Land Use', 'Passed', 2, 1, 78, 'Updates zoning.', 'https://fcgov.com/1', 'verified');
        INSERT INTO events VALUES ('e2', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-12', 'Budget Supplemental', 'Budget & Finance', 'Passed', 3, 0, 55, 'Adds funding.', 'https://fcgov.com/2', 'verified');

        INSERT INTO entity_actions VALUES (1, 'e1', 'p1', 'yes');
        INSERT INTO entity_actions VALUES (2, 'e1', 'p2', 'yes');
        INSERT INTO entity_actions VALUES (3, 'e1', 'p3', 'no');
        INSERT INTO entity_actions VALUES (4, 'e2', 'p1', 'yes');
        INSERT INTO entity_actions VALUES (5, 'e2', 'p2', 'yes');
        INSERT INTO entity_actions VALUES (6, 'e2', 'p3', 'yes');
    """)
    conn.commit()
    conn.close()

    res = run_v3_intelligence(str(db), pub)
    assert res["executive_digest_events"] == 2
    assert res["split_votes"] == 1
    assert res["alignment_jurisdictions"] == 1

    digest = json.loads((pub / "data" / "executive_digest.json").read_text(encoding="utf-8"))
    assert digest["stats"]["split_vote_pct"] == 50.0
    assert len(digest["business_regulatory_alerts"]) == 2

    align = json.loads((pub / "data" / "alignment_explorer.json").read_text(encoding="utf-8"))
    fc = align["by_jurisdiction"]["ocd-division/country:us/state:co/place:fort_collins"]
    assert fc["split_events"] == 1
    assert fc["dissent_leaderboard"][0]["name"] == "Rep Gamma"
    assert fc["dissent_leaderboard"][0]["dissent_rate_pct"] == 50.0

    contacts = json.loads((pub / "data" / "official_contacts.json").read_text(encoding="utf-8"))
    assert contacts["by_jurisdiction"]["ocd-division/country:us/state:co/place:fort_collins"]["council_comment_email"] == "cityleaders@fcgov.com"
