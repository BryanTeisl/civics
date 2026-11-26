"""Offline unit tests for Westminster Vote Tracking PDFs and County/School GovWeb adapter."""
from __future__ import annotations

from pathlib import Path

from civicpulse.adapters.gov_web import extract_date_from_text, parse_gov_page_links

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_date_from_text_handles_all_common_gov_formats():
    assert extract_date_from_text("2026-11-17-bocc-minutes.pdf") == "2026-11-17"
    assert extract_date_from_text("11/23/2026 Vote Tracking (PDF)") == "2026-11-23"
    assert extract_date_from_text("November 17, 2026 — Board Meeting") == "2026-11-17"
    assert extract_date_from_text("11232026-Vote-Tracking-PDF") == "2026-11-23"


def test_parse_westminster_vote_tracking_pdfs_from_saved_fixture():
    html = (FIXTURES / "westminster_agendas_sample.html").read_text(encoding="utf-8")
    docs = parse_gov_page_links(
        html,
        base_url="https://www.westminsterco.gov/129/Meeting-Agendas",
        jurisdiction_id="ocd-division/country:us/state:co/place:westminster",
        year=2026,
    )
    minutes_docs = [d for d in docs if d.doc_type == "minutes"]
    agenda_docs = [d for d in docs if d.doc_type == "agenda"]

    assert len(minutes_docs) == 3
    assert len(agenda_docs) == 1
    assert minutes_docs[0].meeting_date == "2026-11-23"
    assert minutes_docs[0].source_url == "https://www.westminsterco.gov/DocumentCenter/View/7919/11232026-Vote-Tracking-PDF"


def test_parse_larimer_county_bocc_agendas_and_minutes_from_fixture():
    html = (FIXTURES / "larimer_bocc_sample.html").read_text(encoding="utf-8")
    docs = parse_gov_page_links(
        html,
        base_url="https://www.larimer.gov/bocc/commissioners-meetings",
        jurisdiction_id="ocd-division/country:us/state:co/county:larimer",
        year=2026,
    )
    assert len(docs) == 3
    by_type = {}
    for d in docs:
        by_type.setdefault(d.doc_type, []).append(d)
    assert len(by_type["minutes"]) == 1
    assert by_type["minutes"][0].meeting_date == "2026-11-17"
    assert len(by_type["agenda"]) == 2
