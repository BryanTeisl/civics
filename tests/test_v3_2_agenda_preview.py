"""Offline unit tests for zero-pollution 14-day Upcoming Agenda Previews."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from civicpulse.pipeline.agenda_preview import (
    build_agenda_previews,
    extract_agenda_highlights_deterministic,
)


def test_deterministic_agenda_parser_skips_procedural_noise():
    sample = """
    1. Call to Order
    2. Roll Call
    Item 1: Ordinance No. 2026-44 Amending Liquor and Business Licensing Rules
    Item 2: Resolution No. 2026-19 Approving Water Rate Schedule for 2027
    8. Adjournment
    """
    items = extract_agenda_highlights_deterministic(sample)
    assert len(items) == 2
    assert "Business Licensing" in items[0]["title"]
    assert items[0]["topic"] == "Permits & Licensing"
    assert items[1]["topic"] == "Taxes, Fees & Utilities"


def test_build_agenda_previews_quarantines_from_events_and_retires_completed_dates(tmp_path: Path):
    db = tmp_path / "prev.db"
    pub = tmp_path / "public"
    today = datetime.now(timezone.utc)
    d_future = (today + timedelta(days=5)).strftime("%Y-%m-%d")
    d_done = (today + timedelta(days=2)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(db)
    conn.executescript(f"""
        CREATE TABLE jurisdictions (ocd_division_id TEXT PRIMARY KEY, name TEXT, portal_url TEXT, status TEXT);
        CREATE TABLE documents (doc_id INTEGER PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT, doc_type TEXT, title TEXT, source_url TEXT, raw_text TEXT);
        CREATE TABLE events (event_id TEXT PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT, title TEXT);

        INSERT INTO jurisdictions VALUES ('j1', 'Fort Collins City Council', 'https://fortcollinsco.portal.civicclerk.com/', 'active');

        INSERT INTO documents VALUES (
            1, 'j1', '{d_future}', 'agenda', 'Regular Council Agenda', 'https://fcgov.com/ag1.pdf',
            'Item 1: Ordinance No. 2026-50 Rezoning Commercial Corridor along College Avenue'
        );

        INSERT INTO documents VALUES (
            2, 'j1', '{d_done}', 'agenda', 'Earlier Agenda', 'https://fcgov.com/ag0.pdf',
            'Item 1: Ordinance No. 2026-49 Budget Supplemental'
        );
        INSERT INTO events VALUES ('ev1', 'j1', '{d_done}', 'Budget Supplemental');
    """)
    conn.commit()
    conn.close()

    res = build_agenda_previews(str(db), pub, horizon_days=14, use_ollama=False)
    assert res["count"] == 1

    out = json.loads((pub / "data" / "agenda_previews.json").read_text(encoding="utf-8"))
    assert out["count"] == 1
    assert out["previews"][0]["meeting_date"] == d_future
    assert out["previews"][0]["capture_method"] == "agenda_preview"
    assert len(out["previews"][0]["items"]) == 1

    conn = sqlite3.connect(db)
    ev_cnt = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    assert ev_cnt == 1
