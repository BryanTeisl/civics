import hashlib
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

        _add_column_if_missing(conn, "jurisdictions", "parent_division_id", "TEXT")
        _add_column_if_missing(conn, "jurisdictions", "status", "TEXT DEFAULT 'active'")
        _add_column_if_missing(conn, "entities", "elected_date", "TEXT")
        _add_column_if_missing(conn, "entities", "portal_url", "TEXT")
        _add_column_if_missing(conn, "entities", "party", "TEXT")
        _add_column_if_missing(conn, "entities", "phone", "TEXT")
        _add_column_if_missing(conn, "entities", "email", "TEXT")
        _add_column_if_missing(conn, "entities", "social_links_json", "TEXT DEFAULT '{}'")
        _add_column_if_missing(conn, "entities", "bio_extra_json", "TEXT DEFAULT '{}'")

        conn.commit()
    finally:
        conn.close()


def queue_document(
    jurisdiction_id: str,
    doc_type: str,
    title: str,
    source_url: str,
    raw_text: str,
    meeting_date: Optional[str] = None,
    external_id: Optional[str] = None,
    content_hash: Optional[str] = None,
    db_path: str = DB_PATH,
) -> Optional[int]:
    if not content_hash:
        digest_source = f"{jurisdiction_id}|{doc_type}|{source_url}|{raw_text or ''}"
        content_hash = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO documents (
                jurisdiction_id, external_id, meeting_date, doc_type,
                title, source_url, content_hash, raw_text, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                jurisdiction_id,
                external_id,
                meeting_date,
                doc_type,
                title,
                source_url,
                content_hash,
                raw_text,
            ),
        )
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    finally:
        conn.close()


def seed_fort_collins(db_path: str = DB_PATH) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        foco_div = "ocd-division/country:us/state:co/place:fort_collins"
        conn.execute(
            """
            INSERT OR IGNORE INTO jurisdictions (
                ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier, parent_division_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                foco_div,
                "Fort Collins City Council",
                "municipal",
                40.5853,
                -105.0844,
                "civicclerk",
                "https://fortcollinsco.portal.civicclerk.com/",
                "fast",
                "ocd-division/country:us/state:co/county:larimer",
            ),
        )

        council = [
            ("ocd-person/foco-emily-francis", "Emily Francis", "Mayor", "At-Large", "Nov 2023"),
            ("ocd-person/foco-chris-conway", "Chris Conway", "Councilmember", "District 1", "Nov 2025"),
            ("ocd-person/foco-julie-pignataro", "Julie Pignataro", "Mayor Pro Tem", "District 2", "Nov 2023"),
            ("ocd-person/foco-josh-fudge", "Josh Fudge", "Councilmember", "District 3", "Nov 2025"),
            ("ocd-person/foco-melanie-potyondy", "Melanie Potyondy", "Councilmember", "District 4", "Nov 2023"),
            ("ocd-person/foco-amy-hoeven", "Amy Hoeven", "Councilmember", "District 5", "Nov 2025"),
            ("ocd-person/foco-anne-nelsen", "Anne Nelsen", "Councilmember", "District 6", "Nov 2025"),
        ]

        for pid, name, role, district, edate in council:
            conn.execute(
                """
                INSERT OR IGNORE INTO entities (
                    ocd_person_id, jurisdiction_id, name, entity_type, role, district, elected_date, website_url
                ) VALUES (?, ?, ?, 'legislator', ?, ?, ?, 'https://www.fcgov.com/council/')
                """,
                (pid, foco_div, name, role, district, edate),
            )

        conn.commit()
    finally:
        conn.close()


def seed_public_profiles(db_path: str = DB_PATH) -> None:
    init_db(db_path)
    seed_fort_collins(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO jurisdictions (
                ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
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

        foco_profiles = [
            ("ocd-person/foco-emily-francis", "Nonpartisan", "(970) 221-6505", "efrancis@fcgov.com", "Nov 2023"),
            ("ocd-person/foco-chris-conway", "Nonpartisan", "(970) 221-6505", "cconway@fcgov.com", "Nov 2025"),
            ("ocd-person/foco-julie-pignataro", "Nonpartisan", "(970) 221-6505", "jpignataro@fcgov.com", "Nov 2023"),
            ("ocd-person/foco-josh-fudge", "Nonpartisan", "(970) 221-6505", "jfudge@fcgov.com", "Nov 2025"),
            ("ocd-person/foco-melanie-potyondy", "Nonpartisan", "(970) 221-6505", "mpotyondy@fcgov.com", "Nov 2023"),
            ("ocd-person/foco-amy-hoeven", "Nonpartisan", "(970) 221-6505", "ahoeven@fcgov.com", "Nov 2025"),
            ("ocd-person/foco-anne-nelsen", "Nonpartisan", "(970) 221-6505", "anelsen@fcgov.com", "Nov 2025"),
        ]
        for pid, party, phone, email, edate in foco_profiles:
            conn.execute(
                """
                UPDATE entities
                SET party = COALESCE(NULLIF(party, ''), ?),
                    phone = COALESCE(NULLIF(phone, ''), ?),
                    email = COALESCE(NULLIF(email, ''), ?),
                    elected_date = COALESCE(NULLIF(elected_date, ''), ?),
                    portal_url = COALESCE(NULLIF(portal_url, ''), 'https://www.fcgov.com/council/')
                WHERE ocd_person_id = ?
                """,
                (party, phone, email, edate, pid),
            )

        conn.execute(
            """
            UPDATE entities
            SET party = COALESCE(NULLIF(party, ''), 'Nonpartisan'),
                phone = COALESCE(NULLIF(phone, ''), '(720) 337-2000'),
                elected_date = COALESCE(NULLIF(elected_date, ''), 'Jul 2023'),
                portal_url = COALESCE(NULLIF(portal_url, ''), 'https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Denver-City-Council')
            WHERE jurisdiction_id = 'ocd-division/country:us/state:co/place:denver'
            """
        )

        larimer_commissioners = [
            ("ocd-person/larimer-john-kefalas", "John Kefalas", "District 1", "jkefalas@larimer.org", "Nov 2022"),
            ("ocd-person/larimer-kristin-stephens", "Kristin Stephens", "District 2", "kstephens@larimer.org", "Nov 2024"),
            ("ocd-person/larimer-jody-shadduck-mcnally", "Jody Shadduck-McNally", "District 3", "jshadduckmcnally@larimer.org", "Nov 2024"),
        ]
        for pid, name, dist, email, edate in larimer_commissioners:
            conn.execute(
                """
                INSERT OR IGNORE INTO entities (
                    ocd_person_id, jurisdiction_id, name, entity_type, role,
                    district, elected_date, website_url, portal_url, party, phone, email
                ) VALUES (?, 'ocd-division/country:us/state:co/county:larimer', ?, 'legislator', 'Commissioner', ?, ?, 'https://www.larimer.gov/bocc', 'https://www.larimer.gov/bocc', 'Democratic', '(970) 498-7010', ?)
                """,
                (pid, name, dist, edate, email),
            )
            conn.execute(
                """
                UPDATE entities
                SET elected_date = COALESCE(NULLIF(elected_date, ''), ?)
                WHERE ocd_person_id = ?
                """,
                (edate, pid),
            )


        # --- EXPANSION: Colorado Springs (Legistar) & Greeley (CivicClerk) ---
        cos_div = "ocd-division/country:us/state:co/place:colorado_springs"
        greeley_div = "ocd-division/country:us/state:co/place:greeley"
        elpaso_div = "ocd-division/country:us/state:co/county:el_paso"
        weld_div = "ocd-division/country:us/state:co/county:weld"

        conn.execute(
            """
            INSERT OR IGNORE INTO jurisdictions (
                ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier, parent_division_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                cos_div,
                "Colorado Springs City Council",
                "municipal",
                38.8339,
                -104.8214,
                "legistar",
                "https://coloradosprings.legistar.com/",
                "fast",
                elpaso_div,
            ),
        )
        # Ensure Colorado Springs is marked active even if an older legacy row existed
        conn.execute(
            """
            UPDATE jurisdictions
            SET status = 'active', adapter_type = 'legistar', portal_url = 'https://coloradosprings.legistar.com/', parent_division_id = ?
            WHERE ocd_division_id = ?
            """,
            (elpaso_div, cos_div),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO jurisdictions (
                ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier, parent_division_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                greeley_div,
                "Greeley City Council",
                "municipal",
                40.4233,
                -104.7091,
                "civicclerk",
                "https://greeleyco.portal.civicclerk.com/",
                "fast",
                weld_div,
            ),
        )
        conn.execute(
            """
            UPDATE jurisdictions
            SET status = 'active', adapter_type = 'civicclerk', portal_url = 'https://greeleyco.portal.civicclerk.com/', parent_division_id = ?
            WHERE ocd_division_id = ?
            """,
            (weld_div, greeley_div),
        )

        # Parent counties as unclaimed demand-capture targets until ingested
        for c_div, c_name, c_lat, c_lng, c_portal in [
            (elpaso_div, "El Paso County Board of Commissioners", 38.8322, -104.5256, "https://www.agendasuite.org/iip/elpaso"),
            (weld_div, "Weld County Board of Commissioners", 40.5547, -104.3924, "https://www.weld.gov/Government/Departments/Commissioners"),
        ]:
            conn.execute(
                """
                INSERT OR IGNORE INTO jurisdictions (
                    ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier, status
                ) VALUES (?, ?, 'county', ?, ?, 'unclaimed', ?, 'slow', 'unclaimed')
                """,
                (c_div, c_name, c_lat, c_lng, c_portal),
            )

        # Colorado Springs 9-member City Council (6 Districts + 3 At-Large)
        cos_council = [
            ("ocd-person/cos-dave-donelson", "Dave Donelson", "Councilmember", "District 1", "Apr 2021"),
            ("ocd-person/cos-ken-casey", "Ken Casey", "Councilmember", "District 2", "Apr 2026"),
            ("ocd-person/cos-brandy-williams", "Brandy Williams", "Councilmember", "District 3", "Apr 2025"),
            ("ocd-person/cos-kimberly-gold", "Kimberly Gold", "Councilmember", "District 4", "Apr 2025"),
            ("ocd-person/cos-nancy-henjum", "Nancy Henjum", "Councilmember", "District 5", "Apr 2021"),
            ("ocd-person/cos-roland-rainey", "Roland Rainey Jr.", "Councilmember", "District 6", "Apr 2025"),
            ("ocd-person/cos-lynette-crow-iverson", "Lynette Crow-Iverson", "Council President", "At-Large", "Apr 2021"),
            ("ocd-person/cos-brian-risley", "Brian Risley", "President Pro Tem", "At-Large", "Apr 2023"),
            ("ocd-person/cos-david-leinweber", "David Leinweber", "Councilmember", "At-Large", "Apr 2023"),
        ]
        for pid, name, role, dist, edate in cos_council:
            conn.execute(
                """
                INSERT OR IGNORE INTO entities (
                    ocd_person_id, jurisdiction_id, name, entity_type, role, district, elected_date, website_url, portal_url, party
                ) VALUES (?, ?, ?, 'legislator', ?, ?, ?, 'https://coloradosprings.gov/city-council', 'https://coloradosprings.legistar.com/', 'Nonpartisan')
                """,
                (pid, cos_div, name, role, dist, edate),
            )

        # Greeley 7-member City Council (Mayor + 4 Wards + 2 At-Large)
        greeley_council = [
            ("ocd-person/greeley-dale-hall", "Dale Hall", "Mayor", "At-Large", "Nov 2025", "970-657-0310", "Dale.Hall@greeleygov.com"),
            ("ocd-person/greeley-craig-huddleston", "Craig Huddleston", "Councilmember", "Ward I", "May 2026", "970-381-7918", "Craig.Huddleston@greeleygov.com"),
            ("ocd-person/greeley-deb-deboutez", "Deb DeBoutez", "Councilmember", "Ward II", "Nov 2025", "970-336-4296", "Deb.Deboutez@greeleygov.com"),
            ("ocd-person/greeley-johnny-olson", "Johnny Olson", "Councilmember", "Ward III", "Nov 2025", "970-336-4293", "Johnny.Olson@greeleygov.com"),
            ("ocd-person/greeley-brian-rudy", "Brian Rudy", "Councilmember", "Ward IV", "Nov 2025", "970-888-1885", "Brian.Rudy@greeleygov.com"),
            ("ocd-person/greeley-ryan-roth", "Ryan Roth", "Councilmember", "At-Large", "Nov 2025", "970-888-1191", "Ryan.Roth@greeleygov.com"),
            ("ocd-person/greeley-melissa-mcdonald", "Melissa McDonald", "Councilmember", "At-Large", "Nov 2023", "970-657-7821", "Melissa.McDonald@Greeleygov.com"),
        ]
        for pid, name, role, ward, edate, phone, email in greeley_council:
            conn.execute(
                """
                INSERT OR IGNORE INTO entities (
                    ocd_person_id, jurisdiction_id, name, entity_type, role, district, elected_date, website_url, portal_url, party, phone, email
                ) VALUES (?, ?, ?, 'legislator', ?, ?, ?, 'https://greeleyco.gov/city-council/', 'https://greeleyco.portal.civicclerk.com/', 'Nonpartisan', ?, ?)
                """,
                (pid, greeley_div, name, role, ward, edate, phone, email),
            )

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    seed_public_profiles()
    print(f"Database initialized and enriched at {DB_PATH}")
