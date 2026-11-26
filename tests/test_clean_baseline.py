"""Offline tests for v2 Clean Baseline: 1-hop GovWeb discovery, contact enrichment,
archived-jurisdiction purge, and QA action normalization.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from civicpulse.adapters.gov_web import discover_meeting_subpages, parse_gov_page_links
from civicpulse.pipeline.export_enhancements import run_export_enhancements
from scripts.enrich_contacts import match_contacts_from_html
from scripts.reconcile_qa import reconcile_qa


def test_gov_web_discovers_same_domain_meeting_subpages_only():
    html = """
    <html><body>
      <a href="/government/board-of-county-commissioners/public-hearings/">Public Hearings &amp; Agendas</a>
      <a href="/government/board-of-county-commissioners/minutes-archive/">Minutes Archive</a>
      <a href="https://facebook.com/bouldercounty">Facebook</a>
      <a href="https://external-site.org/agendas">External</a>
    </body></html>
    """
    subs = discover_meeting_subpages(
        html, "https://bouldercounty.gov/government/board-of-county-commissioners/", max_subpages=3
    )
    assert len(subs) == 2
    assert all(u.startswith("https://bouldercounty.gov/") for u in subs)


def test_contact_enrichment_matches_official_emails_and_phones_ignoring_generic():
    html = """
    <div class="member">
      <h3>Mayor Emily Francis</h3>
      <a href="mailto:efrancis@fcgov.com">efrancis@fcgov.com</a>
      <a href="tel:970-221-6505">(970) 221-6505</a>
    </div>
    <div class="member">
      <h3>Councilmember Josh Fudge</h3>
      <p>Email: jfudge@fcgov.com | Phone: 970.555.1212</p>
    </div>
    <footer><a href="mailto:webmaster@fcgov.com">Contact Webmaster</a></footer>
    """
    entities = [
        {"ocd_person_id": "p1", "name": "Emily Francis"},
        {"ocd_person_id": "p2", "name": "Josh Fudge"},
        {"ocd_person_id": "p3", "name": "Unlisted Member"},
    ]
    matched = match_contacts_from_html(html, entities)
    assert matched["p1"]["email"] == "efrancis@fcgov.com"
    assert matched["p1"]["phone"] == "(970) 221-6505"
    assert matched["p2"]["email"] == "jfudge@fcgov.com"
    assert matched["p2"]["phone"] == "(970) 555-1212"
    assert "p3" not in matched


def test_export_enhancements_purges_archived_files_and_syncs_per_jurisdiction_json(tmp_path: Path):
    db_file = tmp_path / "base.db"
    public_dir = tmp_path / "public"
    data_dir = public_dir / "data"
    data_dir.mkdir(parents=True)

    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE jurisdictions (
            ocd_division_id TEXT PRIMARY KEY, name TEXT, level TEXT,
            adapter_type TEXT, portal_url TEXT, status TEXT
        );
        CREATE TABLE entities (
            ocd_person_id TEXT PRIMARY KEY, jurisdiction_id TEXT, name TEXT, active INTEGER DEFAULT 1
        );
        CREATE TABLE documents (
            doc_id INTEGER PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT,
            doc_type TEXT, title TEXT, source_url TEXT
        );
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, jurisdiction_id TEXT, doc_id INTEGER,
            meeting_date TEXT, title TEXT, event_type TEXT, topic TEXT,
            outcome TEXT, yes_count INTEGER, no_count INTEGER, abstain_count INTEGER,
            plain_summary TEXT, source_url TEXT, qa_status TEXT
        );
        CREATE TABLE entity_actions (event_id TEXT, entity_id TEXT, value TEXT);

        INSERT INTO jurisdictions VALUES
            ('ocd-division/country:us/state:co/place:denver', 'Denver City Council', 'municipal', 'legistar', 'https://denver.legistar.com/', 'active'),
            ('ocd-division/country:us/state:ca/place:san_jose', 'San Jose City Council', 'city', 'primegov', '', 'archived');
        INSERT INTO entities VALUES ('p1', 'ocd-division/country:us/state:co/place:denver', 'Jane Doe', 1);
        INSERT INTO events VALUES
            ('ev_1', 'ocd-division/country:us/state:co/place:denver', NULL, '2026-11-16',
             'Ordinance rezoning commercial corridor', 'ordinance', 'General',
             'Adopted 1-0 (1-0)', 1, 0, 0, 'Rezones corridor.', 'https://denver.legistar.com/1', 'verified');
        INSERT INTO entity_actions VALUES ('ev_1', 'p1', 'Yes');
    """)
    conn.commit()
    conn.close()

    # Pre-seed stale archived San Jose file + un-normalized Denver file + directory.json
    sj_file = data_dir / "country_us__state_ca__place_san_jose.json"
    sj_file.write_text('{"jurisdiction":{"ocd_division_id":"ocd-division/country:us/state:ca/place:san_jose"}}', encoding="utf-8")

    den_file = data_dir / "country_us__state_co__place_denver.json"
    den_file.write_text(
        json.dumps({
            "jurisdiction": {
                "ocd_division_id": "ocd-division/country:us/state:co/place:denver",
                "level": "municipal",
                "status": "active",
            },
            "events": [{"event_id": "ev_1", "topic": "General", "outcome": "Adopted 1-0 (1-0)"}],
        }),
        encoding="utf-8",
    )

    (data_dir / "directory.json").write_text(
        json.dumps({
            "jurisdictions": [
                {"ocd_division_id": "ocd-division/country:us/state:co/place:denver", "level": "municipal", "status": "active"},
                {"ocd_division_id": "ocd-division/country:us/state:ca/place:san_jose", "level": "city", "status": "archived"},
            ]
        }),
        encoding="utf-8",
    )

    res = run_export_enhancements(str(db_file), public_dir)
    assert res["archived_files_removed"] == 1
    assert not sj_file.exists()

    dir_out = json.loads((data_dir / "directory.json").read_text(encoding="utf-8"))
    assert len(dir_out["jurisdictions"]) == 1
    assert dir_out["jurisdictions"][0]["level"] == "city"

    den_out = json.loads(den_file.read_text(encoding="utf-8"))
    assert den_out["jurisdiction"]["level"] == "city"
    assert den_out["events"][0]["topic"] == "Zoning & Land Use"
    assert den_out["events"][0]["outcome"] == "Passed"
    assert den_out["events"][0]["tally"] == "1-0"


def test_reconcile_qa_normalizes_abstain_and_aye_variants(tmp_path: Path):
    db_file = tmp_path / "qa.db"
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE jurisdictions (ocd_division_id TEXT PRIMARY KEY, name TEXT, status TEXT);
        CREATE TABLE entities (ocd_person_id TEXT PRIMARY KEY, jurisdiction_id TEXT, name TEXT, active INTEGER);
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, jurisdiction_id TEXT, doc_id INTEGER,
            outcome TEXT, yes_count INTEGER, no_count INTEGER,
            abstain_count INTEGER, absent_count INTEGER,
            qa_status TEXT, qa_notes TEXT
        );
        CREATE TABLE entity_actions (event_id TEXT, entity_id TEXT, value TEXT);

        INSERT INTO jurisdictions VALUES ('j1', 'Test City', 'active');
        INSERT INTO entities VALUES ('p1', 'j1', 'A', 1), ('p2', 'j1', 'B', 0);
        INSERT INTO events VALUES ('e1', 'j1', 1, 'Passed', 1, 0, 1, 0, 'needs_review', 'old');
        INSERT INTO entity_actions VALUES ('e1', 'p1', 'Aye'), ('e1', 'p2', 'Recused');
    """)
    conn.commit()
    conn.close()

    res = reconcile_qa(str(db_file), apply=True)
    assert res["action_values_normalized"] == 2
    assert res["verified"] == 1
