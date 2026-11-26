"""Offline unit tests for CivicPulse v3.5 QA Trust Calibration & Tabbed Home UX."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.calibrate_qa_trust import calibrate_database_qa, evaluate_event_qa


def test_evaluate_event_qa_accepts_committee_and_consent_votes():
    # 4-0 Denver committee vote (out of 13 councilmembers) with 4 named votes -> verified
    st, reasons = evaluate_event_qa(
        meeting_date="2026-11-18",
        title="Contract with AtkinsRealis USA Inc. for Bridge Inspection",
        outcome="Passed",
        yes_count=4,
        no_count=0,
        named_yes=4,
        named_no=0,
        roster_size=13,
    )
    assert st == "verified"
    assert reasons == []

    # Longmont voice/consent vote (0 named roll-call rows, recorded 7-0 tally) -> verified
    st2, reasons2 = evaluate_event_qa(
        meeting_date="2026-10-14",
        title="Ordinance 2026-41 Approving Water Utility Easement",
        outcome="Passed (Consent)",
        yes_count=7,
        no_count=0,
        named_yes=0,
        named_no=0,
        roster_size=7,
    )
    assert st2 == "verified"
    assert reasons2 == []


def test_evaluate_event_qa_flags_real_anomalies():
    # Outcome-only junk title -> needs_review
    st1, r1 = evaluate_event_qa("2026-11-20", "Adopted 7-0", "Passed", 9, 0, 9, 0, 9)
    assert st1 == "needs_review"
    assert "junk_or_empty_title" in r1

    # Contradictory named votes (5 named No votes when recorded no_count is 0) -> needs_review
    st2, r2 = evaluate_event_qa("2026-11-20", "Ordinance 2026-99 Zoning Change", "Passed", 7, 0, 2, 5, 7)
    assert st2 == "needs_review"
    assert "named_votes_exceed_tally" in r2

    # Missing ISO date -> needs_review
    st3, r3 = evaluate_event_qa("", "Ordinance 2026-99 Zoning Change", "Passed", 7, 0, 0, 0, 7)
    assert st3 == "needs_review"
    assert "invalid_or_missing_date" in r3


def test_calibrate_database_qa_upgrades_valid_rows_and_keeps_bad_rows_flagged(tmp_path: Path):
    db = tmp_path / "qa.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE entities (ocd_person_id TEXT PRIMARY KEY, jurisdiction_id TEXT, active INTEGER);
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT,
            title TEXT, outcome TEXT, yes_count INTEGER, no_count INTEGER, qa_status TEXT
        );
        CREATE TABLE entity_actions (action_id INTEGER PRIMARY KEY, event_id TEXT, entity_id TEXT, action_type TEXT);

        INSERT INTO entities VALUES ('p1', 'denver', 1), ('p2', 'denver', 1), ('p3', 'denver', 1), ('p4', 'denver', 1);
        INSERT INTO events VALUES ('ev_good', 'denver', '2026-11-18', 'Amends Transit Maintenance Contract', 'Passed', 4, 0, 'needs_review');
        INSERT INTO events VALUES ('ev_bad', 'denver', '2026-11-18', 'Adopted 4-0', 'Passed', 4, 0, 'verified');
    """)
    conn.commit()
    conn.close()

    res = calibrate_database_qa(db, apply=True)
    assert res["changed"] == 2
    assert res["after"] == {"verified": 1, "needs_review": 1}
