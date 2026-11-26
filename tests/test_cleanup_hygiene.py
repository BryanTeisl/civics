"""Offline unit tests for scripts/cleanup_hygiene.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.cleanup_hygiene import (
    dedupe_api_vs_pdf_events,
    prune_unclaimed_jurisdiction_jsons,
    skip_past_agendas,
)


def test_skip_past_agendas_preserves_upcoming_agendas(tmp_path: Path):
    db = tmp_path / "c.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE documents (doc_id INTEGER PRIMARY KEY, meeting_date TEXT, doc_type TEXT, status TEXT);
        INSERT INTO documents VALUES (1, '2026-01-10', 'agenda', 'pending');
        INSERT INTO documents VALUES (2, '2026-12-15', 'agenda', 'pending');
        INSERT INTO documents VALUES (3, '2026-01-10', 'minutes', 'pending');
    """)
    cnt = skip_past_agendas(conn, "2026-11-26", apply=True)
    conn.commit()
    assert cnt == 1
    statuses = dict(conn.execute("SELECT doc_id, status FROM documents").fetchall())
    conn.close()
    assert statuses == {1: "skipped", 2: "pending", 3: "pending"}


def test_dedupe_api_vs_pdf_events_keeps_structured_api_row(tmp_path: Path):
    db = tmp_path / "d.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE events (event_id TEXT PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT, title TEXT, doc_id INTEGER);
        CREATE TABLE entity_actions (action_id INTEGER PRIMARY KEY, event_id TEXT);
        INSERT INTO events VALUES ('ev_api', 'denver', '2026-11-17', 'For an ordinance amending Section 18-91 of the Denver Revised Municipal Code', NULL);
        INSERT INTO events VALUES ('ev_pdf', 'denver', '2026-11-17', 'Ordinance Amending Section 18-91 of the Denver Revised Municipal Code', 960);
        INSERT INTO events VALUES ('ev_other', 'denver', '2026-11-17', 'Contract with Parks Landscaping LLC', 960);
        INSERT INTO entity_actions VALUES (1, 'ev_api');
        INSERT INTO entity_actions VALUES (2, 'ev_pdf');
    """)
    dupes = dedupe_api_vs_pdf_events(conn, apply=True)
    conn.commit()
    assert len(dupes) == 1
    assert dupes[0]["removed_event_id"] == "ev_pdf"
    remaining = {r[0] for r in conn.execute("SELECT event_id FROM events").fetchall()}
    actions = {r[0] for r in conn.execute("SELECT event_id FROM entity_actions").fetchall()}
    conn.close()
    assert remaining == {"ev_api", "ev_other"}
    assert actions == {"ev_api"}


def test_prune_unclaimed_jsons_keeps_active_and_metadata_files(tmp_path: Path):
    db = tmp_path / "p.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (ocd_division_id TEXT PRIMARY KEY, status TEXT);
        INSERT INTO jurisdictions VALUES ('ocd-division/country:us/state:co/place:fort_collins', 'active');
        INSERT INTO jurisdictions VALUES ('ocd-division/country:us/state:co/place:grand_junction', 'unclaimed');
    """)
    conn.commit()
    conn.close()

    f_active = data_dir / "country_us__state_co__place_fort_collins.json"
    f_unclaimed = data_dir / "country_us__state_co__place_grand_junction.json"
    f_dir = data_dir / "directory.json"
    for f in (f_active, f_unclaimed, f_dir):
        f.write_text("{}", encoding="utf-8")

    res = prune_unclaimed_jurisdiction_jsons(db, data_dir, apply=True)
    assert res == {"pruned": 1, "kept_active": 1}
    assert f_active.exists()
    assert f_dir.exists()
    assert not f_unclaimed.exists()
