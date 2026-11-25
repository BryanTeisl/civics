"""Unit tests for data normalization, topic taxonomy, committee denominators,
AI QA validation, versioned scoring formula, RSS feeds, and export schema validation.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

from civicpulse.pipeline.export_enhancements import run_export_enhancements
from civicpulse.pipeline.feeds import build_rss_xml
from civicpulse.pipeline.normalize import (
    classify_topic,
    detect_body_type,
    normalize_level,
    normalize_outcome,
    validate_extracted_event,
)
from civicpulse.pipeline.scoring_spec import (
    FORMULA_VERSION,
    build_scoring_methodology_payload,
    calculate_auditable_impact,
    compute_formula_hash,
    render_scoring_methodology_markdown,
)
from scripts.validate_exports import validate_data_dir


def test_level_normalization_fixes_mixed_labels():
    assert normalize_level("municipal") == "city"
    assert normalize_level("City") == "city"
    assert normalize_level("school_board") == "school_district"
    assert normalize_level("", "ocd-division/country:us/state:co/county:larimer") == "county"


def test_outcome_normalization_cleans_duplicate_tallies_and_consent():
    r1 = normalize_outcome("Adopted 7-0 (7-0)", yes_count=0, no_count=0)
    assert r1.status == "Passed"
    assert r1.tally == "7-0"
    assert r1.yes_count == 7 and r1.no_count == 0

    r2 = normalize_outcome("Approved by Consent", yes_count=7, no_count=0)
    assert r2.status == "Passed"
    assert r2.passage_method == "Consent"
    assert r2.tally == "7-0"

    r3 = normalize_outcome("Motion Failed 3-4")
    assert r3.status == "Failed"
    assert r3.tally == "3-4"


def test_topic_classification_replaces_vague_general_with_specific_labels():
    assert classify_topic("Ordinance rezoning 12 acres for multifamily housing PUD", "", "General") == "Zoning & Land Use"
    assert classify_topic("Resolution approving 2027 water rate and stormwater fee schedule", "", "General") == "Taxes, Fees & Utilities"
    assert classify_topic("Approval of on-call engineering vendor contract amendment", "", "General") == "Contracts & Procurement"
    assert classify_topic("Supplemental budget appropriation for capital improvements", "", "General") == "Budget & Finance"


def test_committee_attendance_denominator_does_not_penalize_against_full_council():
    assert detect_body_type("Rezoning Item", "Land Use, Transportation & Infrastructure Committee", 4, 13) == "committee"

    committee_score = calculate_auditable_impact(
        "ordinance", yes_count=4, no_count=0, expected_body_size=4, body_type="committee"
    )
    full_score = calculate_auditable_impact(
        "ordinance", yes_count=13, no_count=0, expected_body_size=13, body_type="full_body"
    )
    # Committee gets full 10/10 committee turnout points (not 4/13 penalty), while full council gets 20/20
    assert committee_score.turnout == 10.0
    assert full_score.turnout == 20.0
    assert full_score.score > committee_score.score


def test_ai_qa_validation_catches_bad_roster_and_vote_math():
    ok = validate_extracted_event(
        outcome_status="Passed",
        yes_count=2,
        no_count=1,
        abstain_count=0,
        absent_count=0,
        matched_votes=[
            {"entity_id": "p1", "value": "Yes"},
            {"entity_id": "p2", "value": "Yes"},
            {"entity_id": "p3", "value": "No"},
        ],
        unmatched_voter_names=[],
        roster_size=7,
    )
    assert ok.qa_status == "verified"

    bad_math = validate_extracted_event(
        outcome_status="Passed",
        yes_count=6,
        no_count=1,
        abstain_count=0,
        absent_count=0,
        matched_votes=[{"entity_id": "p1", "value": "Yes"}],
        unmatched_voter_names=["Fake Councilor"],
        roster_size=7,
    )
    assert bad_math.qa_status == "needs_review"
    assert len(bad_math.issues) >= 2

    impossible = validate_extracted_event(
        outcome_status="Passed",
        yes_count=2,
        no_count=5,
        abstain_count=0,
        absent_count=0,
        matched_votes=[],
        unmatched_voter_names=[],
        roster_size=5,
    )
    assert impossible.qa_status == "flagged"


def test_scoring_methodology_is_versioned_hashed_and_downloadable():
    payload = build_scoring_methodology_payload()
    assert payload["formula_version"] == FORMULA_VERSION
    assert len(payload["formula_hash"]) == 12
    assert payload["formula_hash"] == compute_formula_hash()
    assert len(payload["changelog"]) >= 2

    md = render_scoring_methodology_markdown()
    assert f"v{FORMULA_VERSION}" in md
    assert payload["formula_hash"] in md
    assert "Formula Changelog" in md


def test_rss_feed_xml_is_well_formed():
    xml_str = build_rss_xml(
        title="CivicPulse Test Feed",
        link="https://civics-d03.pages.dev",
        description="Test",
        items=[
            {
                "event_id": "ev_123",
                "jurisdiction_name": "Fort Collins City Council",
                "meeting_date": "2026-11-17",
                "title": "Ordinance Updating Water Rates",
                "topic": "Taxes, Fees & Utilities",
                "outcome_status": "Passed",
                "tally": "6-1",
                "impact_score": 66.4,
                "plain_summary": "Updates residential and commercial water tiers.",
                "source_url": "https://fortcollinsco.portal.civicclerk.com/event/1",
            }
        ],
    )
    root = ET.fromstring(xml_str)
    assert root.tag == "rss"
    items = root.findall("./channel/item")
    assert len(items) == 1
    assert "Fort Collins City Council" in items[0].find("title").text


def test_end_to_end_export_enhancements_and_schema_validation(tmp_path: Path):
    db_file = tmp_path / "test.db"
    public_dir = tmp_path / "public"
    (public_dir / "data").mkdir(parents=True)

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
        CREATE TABLE entity_actions (
            event_id TEXT, entity_id TEXT, value TEXT
        );
        INSERT INTO jurisdictions VALUES (
            'ocd-division/country:us/state:co/place:fort_collins',
            'Fort Collins City Council', 'municipal', 'civicclerk',
            'https://fortcollinsco.portal.civicclerk.com/', 'active'
        );
        INSERT INTO entities VALUES ('p1', 'ocd-division/country:us/state:co/place:fort_collins', 'Emily Francis', 1);
        INSERT INTO documents VALUES (
            1, 'ocd-division/country:us/state:co/place:fort_collins',
            '2026-12-01', 'agenda', 'Regular Council Meeting', 'https://example.gov/agenda'
        );
        INSERT INTO events VALUES (
            'ev_1', 'ocd-division/country:us/state:co/place:fort_collins', 1,
            '2026-11-17', 'Ordinance approving stormwater fee schedule', 'ordinance',
            'General', 'Adopted 7-0 (7-0)', 7, 0, 0, 'Updates stormwater fees.',
            'https://example.gov/minutes', 'verified'
        );
    """)
    conn.commit()
    conn.close()

    # Seed a directory.json with mixed level label to confirm enhancement normalizes it
    (public_dir / "data" / "directory.json").write_text(
        json.dumps({
            "jurisdictions": [
                {
                    "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
                    "name": "Fort Collins City Council",
                    "level": "municipal",
                    "status": "active",
                }
            ]
        }),
        encoding="utf-8",
    )

    out = run_export_enhancements(str(db_file), public_dir)
    assert out["normalized_events"] == 1
    assert out["upcoming_count"] == 1
    assert (public_dir / "docs" / "civicpulse_impact_formula.md").exists()
    assert (public_dir / "docs" / "civicpulse_impact_formula.json").exists()
    assert (public_dir / "feeds" / "all.xml").exists()
    assert (public_dir / "data" / "search_chunks" / "manifest.json").exists()

    # Run export schema & hygiene validator
    errs = validate_data_dir(public_dir / "data")
    assert errs == []
