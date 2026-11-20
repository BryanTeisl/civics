"""
Zero-maintenance SQLite Master Database wrapper for the Core Civic Aggregator.
Auto-initializes core_civic.db on first run and supports safe backups to OneDrive.
"""
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("CIVIC_DB_PATH", "core_civic.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # WAL mode allows watcher.py (CPU) and worker.py (GPU) to run safely together
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS jurisdictions (
        ocd_division_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        level TEXT NOT NULL, -- 'municipal', 'county', 'state', 'federal'
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        adapter_type TEXT NOT NULL, -- 'civicclerk', 'legistar', 'civicplus', 'primegov', 'openstates'
        portal_url TEXT NOT NULL,
        poll_tier TEXT DEFAULT 'fast', -- 'fast' (active) or 'slow' (weekly)
        last_polled_at TEXT
    );

    CREATE TABLE IF NOT EXISTS entities (
        ocd_person_id TEXT PRIMARY KEY,
        jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(ocd_division_id),
        name TEXT NOT NULL,
        entity_type TEXT DEFAULT 'legislator', -- 'legislator', 'candidate', 'appointed', 'executive'
        role TEXT,
        district TEXT,
        website_url TEXT,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS documents (
        doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(ocd_division_id),
        external_id TEXT,
        meeting_date TEXT,
        doc_type TEXT NOT NULL, -- 'agenda', 'minutes', 'transcript'
        title TEXT,
        source_url TEXT NOT NULL,
        content_hash TEXT UNIQUE,
        raw_text TEXT,
        status TEXT DEFAULT 'pending', -- 'pending', 'processed', 'failed', 'skipped'
        retry_count INTEGER DEFAULT 0,
        error_message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        processed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(ocd_division_id),
        doc_id INTEGER REFERENCES documents(doc_id),
        meeting_date TEXT NOT NULL,
        title TEXT NOT NULL,
        event_type TEXT DEFAULT 'ordinance', -- 'ordinance', 'resolution', 'budget', 'motion', 'consent'
        topic TEXT DEFAULT 'General',
        outcome TEXT, -- 'Passed', 'Failed', 'Tabled'
        yes_count INTEGER DEFAULT 0,
        no_count INTEGER DEFAULT 0,
        abstain_count INTEGER DEFAULT 0,
        absent_count INTEGER DEFAULT 0,
        vote_margin INTEGER DEFAULT 0,
        impact_score REAL DEFAULT 0.0,
        source_url TEXT
    );

    CREATE TABLE IF NOT EXISTS entity_actions (
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL REFERENCES events(event_id),
        entity_id TEXT NOT NULL REFERENCES entities(ocd_person_id),
        action_type TEXT NOT NULL, -- 'vote', 'motion', 'second', 'sponsor'
        value TEXT, -- 'Yes', 'No', 'Abstain', 'Absent'
        is_pivotal INTEGER DEFAULT 0, -- 1 if flipping this vote would have changed the outcome
        rationale_summary TEXT,
        verbatim_quote TEXT,
        timestamp TEXT,
        UNIQUE(event_id, entity_id, action_type)
    );
    """)

    conn.commit()
    conn.close()


def seed_fort_collins(db_path: str = DB_PATH) -> None:
    """Seeds the Fort Collins City Council pilot jurisdiction and 2026 roster."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    j_id = "ocd-division/country:us/state:co/place:fort_collins"
    cur.execute("""
        INSERT OR IGNORE INTO jurisdictions
        (ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        j_id,
        "Fort Collins City Council",
        "municipal",
        40.5853,
        -105.0844,
        "civicclerk",
        "https://fortcollinsco.api.civicclerk.com/v1",
        "fast",
    ))

    roster = [
        ("ocd-person/foco-emily-francis", "Emily Francis", "Mayor", "At-Large", "https://www.fortcollins.gov/Government/City-Council"),
        ("ocd-person/foco-chris-conway", "Chris Conway", "Councilmember", "District 1", "https://www.fortcollins.gov/Government/City-Council"),
        ("ocd-person/foco-julie-pignataro", "Julie Pignataro", "Mayor Pro Tem", "District 2", "https://www.fortcollins.gov/Government/City-Council"),
        ("ocd-person/foco-josh-fudge", "Josh Fudge", "Councilmember", "District 3", "https://www.fortcollins.gov/Government/City-Council"),
        ("ocd-person/foco-melanie-potyondy", "Melanie Potyondy", "Councilmember", "District 4", "https://www.fortcollins.gov/Government/City-Council"),
        ("ocd-person/foco-amy-hoeven", "Amy Hoeven", "Councilmember", "District 5", "https://www.fortcollins.gov/Government/City-Council"),
        ("ocd-person/foco-anne-nelsen", "Anne Nelsen", "Councilmember", "District 6", "https://www.fortcollins.gov/Government/City-Council"),
    ]

    for pid, name, role, district, url in roster:
        cur.execute("""
            INSERT OR IGNORE INTO entities
            (ocd_person_id, jurisdiction_id, name, entity_type, role, district, website_url)
            VALUES (?, ?, ?, 'legislator', ?, ?, ?)
        """, (pid, j_id, name, role, district, url))

    conn.commit()
    conn.close()


def queue_document(
    jurisdiction_id: str,
    external_id: str,
    meeting_date: str,
    doc_type: str,
    title: str,
    source_url: str,
    raw_text: str,
    db_path: str = DB_PATH,
) -> bool:
    """Hashes document text and inserts into queue only if new/changed."""
    content_hash = hashlib.sha256(f"{source_url}:{raw_text}".encode("utf-8")).hexdigest()
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO documents
            (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, raw_text, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, raw_text))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Already seen exact same content_hash
        return False
    finally:
        conn.close()


def backup_to_onedrive(backup_dir: Optional[str] = None, db_path: str = DB_PATH) -> Optional[str]:
    """
    Safely copies the SQLite DB to a OneDrive folder using SQLite's online backup API
    so OneDrive never locks or corrupts the active database file.
    """
    target_dir = backup_dir or os.environ.get("ONEDRIVE_BACKUP_DIR")
    if not target_dir:
        return None
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(target_dir, f"core_civic_backup_{stamp}.db")

    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    return dest


if __name__ == "__main__":
    init_db()
    seed_fort_collins()
    print(f"Initialized and seeded {DB_PATH}")
