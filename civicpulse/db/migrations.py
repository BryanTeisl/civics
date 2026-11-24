from __future__ import annotations

import sqlite3
from typing import Callable, List, Optional, Tuple

from .connection import get_connection


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jurisdictions (
            ocd_division_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            level TEXT NOT NULL,
            lat REAL DEFAULT 0.0,
            lng REAL DEFAULT 0.0,
            adapter_type TEXT NOT NULL DEFAULT 'unclaimed',
            portal_url TEXT NOT NULL DEFAULT '',
            poll_tier TEXT DEFAULT 'standard',
            last_polled_at TEXT,
            parent_division_id TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS entities (
            ocd_person_id TEXT PRIMARY KEY,
            jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(ocd_division_id),
            name TEXT NOT NULL,
            entity_type TEXT DEFAULT 'legislator',
            role TEXT,
            district TEXT,
            elected_date TEXT,
            website_url TEXT,
            portal_url TEXT,
            party TEXT DEFAULT 'Nonpartisan',
            phone TEXT,
            email TEXT,
            social_links_json TEXT DEFAULT '{}',
            bio_extra_json TEXT DEFAULT '{}',
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(ocd_division_id),
            external_id TEXT,
            meeting_date TEXT,
            doc_type TEXT NOT NULL,
            title TEXT,
            source_url TEXT NOT NULL,
            content_hash TEXT UNIQUE,
            raw_text TEXT,
            status TEXT DEFAULT 'pending',
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
            plain_summary TEXT DEFAULT '',
            diff_summary TEXT DEFAULT '',
            qa_status TEXT DEFAULT 'verified',
            event_type TEXT DEFAULT 'ordinance',
            topic TEXT DEFAULT 'General',
            outcome TEXT,
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
            action_type TEXT NOT NULL,
            value TEXT,
            is_pivotal INTEGER DEFAULT 0,
            rationale_summary TEXT,
            verbatim_quote TEXT,
            timestamp TEXT,
            UNIQUE(event_id, entity_id, action_type)
        );
        """
    )


def _migration_002_ensure_extended_columns(conn: sqlite3.Connection) -> None:
    """Idempotently upgrades legacy v1 core_civic.db schemas without one-off fix scripts."""
    _add_column_if_missing(conn, "jurisdictions", "parent_division_id", "TEXT")
    _add_column_if_missing(conn, "jurisdictions", "status", "TEXT DEFAULT 'active'")

    _add_column_if_missing(conn, "entities", "active", "INTEGER DEFAULT 1")
    _add_column_if_missing(conn, "entities", "elected_date", "TEXT")
    _add_column_if_missing(conn, "documents", "status", "TEXT DEFAULT 'pending'")
    _add_column_if_missing(conn, "documents", "retry_count", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "documents", "error_message", "TEXT")
    _add_column_if_missing(conn, "entities", "portal_url", "TEXT")
    _add_column_if_missing(conn, "entities", "party", "TEXT DEFAULT 'Nonpartisan'")
    _add_column_if_missing(conn, "entities", "phone", "TEXT")
    _add_column_if_missing(conn, "entities", "email", "TEXT")
    _add_column_if_missing(conn, "entities", "social_links_json", "TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "entities", "bio_extra_json", "TEXT DEFAULT '{}'")

    _add_column_if_missing(conn, "events", "plain_summary", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "events", "diff_summary", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "events", "qa_status", "TEXT DEFAULT 'verified'")


def _migration_003_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_jur_status ON documents(jurisdiction_id, status);
        CREATE INDEX IF NOT EXISTS idx_events_jur_date ON events(jurisdiction_id, meeting_date DESC);
        CREATE INDEX IF NOT EXISTS idx_actions_event_id ON entity_actions(event_id);
        CREATE INDEX IF NOT EXISTS idx_actions_entity_id ON entity_actions(entity_id);
        CREATE INDEX IF NOT EXISTS idx_entities_jur_active ON entities(jurisdiction_id, active);
        """
    )

def _m_add_jurisdiction_roster_url(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "jurisdictions", "roster_url", "TEXT")

MIGRATIONS: List[Tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("001_initial_schema", _migration_001_initial_schema),
    ("002_ensure_extended_columns", _migration_002_ensure_extended_columns),
    ("003_indexes", _migration_003_indexes),
    ("add_jurisdiction_roster_url", _m_add_jurisdiction_roster_url),
]


def init_db(db_path: Optional[str] = None) -> List[str]:
    """Applies all pending SQL migrations and returns the list of newly applied migration IDs."""
    conn = get_connection(db_path)
    applied_now: List[str] = []
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        already = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version, fn in MIGRATIONS:
            if version in already:
                continue
            fn(conn)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            applied_now.append(version)
        conn.commit()
        return applied_now
    finally:
        conn.close()
