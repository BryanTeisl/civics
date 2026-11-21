import json
import os
import sqlite3
from typing import Optional

DB_PATH = os.environ.get("CIVIC_DB_PATH", "core_civic.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def};")


def init_db(db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jurisdictions (
                ocd_division_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                level TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                adapter_type TEXT NOT NULL,
                portal_url TEXT NOT NULL,
                poll_tier TEXT DEFAULT 'fast',
                last_polled_at TEXT,
                parent_division_id TEXT
            );

            CREATE TABLE IF NOT EXISTS entities (
                ocd_person_id TEXT PRIMARY KEY,
                jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(ocd_division_id),
                name TEXT NOT NULL,
                entity_type TEXT DEFAULT 'legislator',
                role TEXT,
                district TEXT,
                website_url TEXT,
                portal_url TEXT,
                party TEXT,
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

        # Safe non-destructive migrations for existing databases
        _add_column_if_missing(conn, "jurisdictions", "parent_division_id", "TEXT")
        _add_column_if_missing(conn, "entities", "portal_url", "TEXT")
        _add_column_if_missing(conn, "entities", "party", "TEXT")
        _add_column_if_missing(conn, "entities", "phone", "TEXT")
        _add_column_if_missing(conn, "entities", "email", "TEXT")
        _add_column_if_missing(conn, "entities", "social_links_json", "TEXT DEFAULT '{}'")
        _add_column_if_missing(conn, "entities", "bio_extra_json", "TEXT DEFAULT '{}'")

        conn.commit()
    finally:
        conn.close()


def seed_public_profiles(db_path: str = DB_PATH) -> None:
    """Populate public contact info, official portals, and hierarchy links for existing rosters."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        # Ensure Larimer County exists as parent jurisdiction for Fort Collins
        conn.execute(
            """
            INSERT OR IGNORE INTO jurisdictions (
                ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ocd-division/country:us/state:co/county:larimer",
                "Larimer County Board of Commissioners",
                "county",
                40.6662,
                -105.4606,
                "civicclerk",
                "https://larimerco.portal.civicclerk.com/",
                "slow",
            ),
        )

        conn.execute(
            """
            UPDATE jurisdictions
            SET parent_division_id = 'ocd-division/country:us/state:co/county:larimer'
            WHERE ocd_division_id = 'ocd-division/country:us/state:co/place:fort_collins'
            """
        )

        # Public municipal contact profiles for Fort Collins City Council (Nonpartisan)
        foco_profiles = [
            {
                "id": "ocd-person/foco-emily-francis",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "efrancis@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {"website": "https://www.fcgov.com/council/"},
                "extra": {"office": "Mayor", "term_type": "2-Year At-Large"},
            },
            {
                "id": "ocd-person/foco-chris-conway",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "cconway@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {},
                "extra": {"office": "Councilmember", "area": "Northeast Fort Collins"},
            },
            {
                "id": "ocd-person/foco-julie-pignataro",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "jpignataro@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {},
                "extra": {"office": "Mayor Pro Tem", "area": "East Central Fort Collins"},
            },
            {
                "id": "ocd-person/foco-josh-fudge",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "jfudge@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {},
                "extra": {"office": "Councilmember", "area": "Southeast Fort Collins"},
            },
            {
                "id": "ocd-person/foco-melanie-potyondy",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "mpotyondy@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {},
                "extra": {"office": "Councilmember", "area": "Southwest Fort Collins"},
            },
            {
                "id": "ocd-person/foco-amy-hoeven",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "ahoeven@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {},
                "extra": {"office": "Councilmember", "area": "West Central Fort Collins"},
            },
            {
                "id": "ocd-person/foco-anne-nelsen",
                "party": "Nonpartisan",
                "phone": "(970) 221-6505",
                "email": "anelsen@fcgov.com",
                "portal_url": "https://www.fcgov.com/council/",
                "socials": {},
                "extra": {"office": "Councilmember", "area": "Northwest Fort Collins"},
            },
        ]

        for p in foco_profiles:
            conn.execute(
                """
                UPDATE entities
                SET party = COALESCE(NULLIF(party, ''), ?),
                    phone = COALESCE(NULLIF(phone, ''), ?),
                    email = COALESCE(NULLIF(email, ''), ?),
                    portal_url = COALESCE(NULLIF(portal_url, ''), ?),
                    social_links_json = CASE
                        WHEN social_links_json IS NULL OR social_links_json = '{}' THEN ?
                        ELSE social_links_json
                    END,
                    bio_extra_json = CASE
                        WHEN bio_extra_json IS NULL OR bio_extra_json = '{}' THEN ?
                        ELSE bio_extra_json
                    END
                WHERE ocd_person_id = ?
                """,
                (
                    p["party"],
                    p["phone"],
                    p["email"],
                    p["portal_url"],
                    json.dumps(p["socials"]),
                    json.dumps(p["extra"]),
                    p["id"],
                ),
            )

        # Mark Denver City Council entities as Nonpartisan & set official council portal
        conn.execute(
            """
            UPDATE entities
            SET party = COALESCE(NULLIF(party, ''), 'Nonpartisan'),
                phone = COALESCE(NULLIF(phone, ''), '(720) 337-2000'),
                portal_url = COALESCE(NULLIF(portal_url, ''), 'https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Denver-City-Council')
            WHERE jurisdiction_id = 'ocd-division/country:us/state:co/place:denver'
            """
        )

        # Seed public Larimer County Commissioners so overlapping map selection works immediately
        larimer_commissioners = [
            (
                "ocd-person/larimer-john-kefalas",
                "ocd-division/country:us/state:co/county:larimer",
                "John Kefalas",
                "legislator",
                "Commissioner",
                "District 1",
                "https://www.larimer.gov/bocc",
                "https://www.larimer.gov/bocc",
                "Democratic",
                "(970) 498-7010",
                "jkefalas@larimer.org",
            ),
            (
                "ocd-person/larimer-kristin-stephens",
                "ocd-division/country:us/state:co/county:larimer",
                "Kristin Stephens",
                "legislator",
                "Commissioner",
                "District 2",
                "https://www.larimer.gov/bocc",
                "https://www.larimer.gov/bocc",
                "Democratic",
                "(970) 498-7010",
                "kstephens@larimer.org",
            ),
            (
                "ocd-person/larimer-jody-shadduck-mcnally",
                "ocd-division/country:us/state:co/county:larimer",
                "Jody Shadduck-McNally",
                "legislator",
                "Commissioner",
                "District 3",
                "https://www.larimer.gov/bocc",
                "https://www.larimer.gov/bocc",
                "Democratic",
                "(970) 498-7010",
                "jshadduckmcnally@larimer.org",
            ),
        ]

        for row in larimer_commissioners:
            conn.execute(
                """
                INSERT OR IGNORE INTO entities (
                    ocd_person_id, jurisdiction_id, name, entity_type, role,
                    district, website_url, portal_url, party, phone, email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    seed_public_profiles()
    print(f"Database initialized and enriched at {DB_PATH}")