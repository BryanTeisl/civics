import sqlite3

from civicpulse.db import get_connection, init_db


def test_migrations_are_idempotent(tmp_path):
    db_file = str(tmp_path / "mig.db")
    first = init_db(db_file)
    assert len(first) == 3

    second = init_db(db_file)
    assert second == []


def test_legacy_v1_schema_upgrades_cleanly(tmp_path):
    db_file = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE jurisdictions (
            ocd_division_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            level TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            adapter_type TEXT NOT NULL,
            portal_url TEXT NOT NULL
        );
        CREATE TABLE entities (
            ocd_person_id TEXT PRIMARY KEY,
            jurisdiction_id TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            jurisdiction_id TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            source_url TEXT NOT NULL
        );
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            jurisdiction_id TEXT NOT NULL,
            meeting_date TEXT NOT NULL,
            title TEXT NOT NULL
        );
        CREATE TABLE entity_actions (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action_type TEXT NOT NULL
        );
        """
    )
    conn.close()

    init_db(db_file)
    c = get_connection(db_file)
    try:
        j_cols = {r["name"] for r in c.execute("PRAGMA table_info(jurisdictions)").fetchall()}
        e_cols = {r["name"] for r in c.execute("PRAGMA table_info(events)").fetchall()}
        assert {"status", "parent_division_id"}.issubset(j_cols)
        assert {"plain_summary", "diff_summary", "qa_status"}.issubset(e_cols)
    finally:
        c.close()
