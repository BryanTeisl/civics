"""Offline unit tests for CivicPulse v4 Representative Bios & UX data enrichment."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from civicpulse.pipeline.rep_bios import generate_all_rep_bios


def test_generate_rep_bios_synthesizes_from_votes_and_quotes(tmp_path: Path):
    db = tmp_path / "test_v4.db"
    pub = tmp_path / "public"
    (pub / "data").mkdir(parents=True)

    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (
            ocd_division_id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT
        );
        CREATE TABLE entities (
            ocd_person_id TEXT PRIMARY KEY,
            jurisdiction_id TEXT,
            name TEXT,
            role TEXT,
            district TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY,
            jurisdiction_id TEXT,
            title TEXT,
            topic TEXT,
            meeting_date TEXT,
            outcome TEXT
        );
        CREATE TABLE entity_actions (
            action_id INTEGER PRIMARY KEY,
            event_id INTEGER,
            entity_id TEXT,
            action_type TEXT,
            is_pivotal INTEGER DEFAULT 0,
            quote TEXT,
            rationale_summary TEXT
        );
        INSERT INTO jurisdictions VALUES ('ocd-division/country:us/state:co/place:fort_collins', 'Fort Collins City Council', 'active');
        INSERT INTO entities VALUES ('ocd-person/co-fort-collins-emily-francis', 'ocd-division/country:us/state:co/place:fort_collins', 'Emily Francis', 'Mayor Pro Tem', 'District 6', 1);
        INSERT INTO events VALUES (1, 'ocd-division/country:us/state:co/place:fort_collins', 'Land Use Code Housing Update', 'Housing & Land Use', '2026-10-15', 'Passed 5-2');
        INSERT INTO entity_actions VALUES (1, 1, 'ocd-person/co-fort-collins-emily-francis', 'Yes', 1, 'We need transit-oriented housing near existing bus corridors.', 'Supported housing density near transit.');
    """)
    conn.commit()
    conn.close()

    shard = pub / "data" / "country_us__state_co__place_fort_collins.json"
    shard.write_text(json.dumps({
        "jurisdiction": {"ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins", "name": "Fort Collins City Council"},
        "entities": [{"id": "ocd-person/co-fort-collins-emily-francis", "name": "Emily Francis"}],
    }), encoding="utf-8")

    res = generate_all_rep_bios(db_path=db, public_dir=pub, use_ollama=False)
    assert res["updated_entities"] == 1
    assert res["enriched_json_files"] == 1

    enriched = json.loads(shard.read_text(encoding="utf-8"))
    bio = enriched["entities"][0]["bio_summary"]
    assert "Emily Francis" in bio
    assert "Housing & Land Use" in bio
    assert "transit-oriented housing" in bio
