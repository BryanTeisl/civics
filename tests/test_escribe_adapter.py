"""Offline unit tests for the CivicPulse eSCRIBE adapter."""
from __future__ import annotations

import json
from pathlib import Path

from civicpulse.adapters.escribe import (
    parse_escribe_calendar_json,
    parse_escribe_html_fallback,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_escribe_calendar_json_extracts_minutes_and_skips_advisory():
    payload = json.loads((FIXTURES / "aurora_escribe_calendar.json").read_text(encoding="utf-8"))
    docs = parse_escribe_calendar_json(
        payload,
        base_url="https://pub-auroraco.escribemeetings.com",
        jurisdiction_id="ocd-division/country:us/state:co/place:aurora",
        year=2026,
    )
    assert len(docs) == 2
    by_type = {d.doc_type: d for d in docs}
    assert "minutes" in by_type
    assert "agenda" in by_type
    assert by_type["minutes"].meeting_date == "2026-11-16"
    assert "PostMinutes" in by_type["minutes"].source_url
    assert all("Art in Public" not in d.title for d in docs)


def test_parse_escribe_html_fallback_extracts_meeting_links():
    html = """
    <html><body>
      <a href="/Meeting.aspx?Id=11111111-2222-3333-4444-555555555555&Agenda=PostMinutes&lang=English">
        November 10, 2026 Board of County Commissioners Business Meeting - Minutes
      </a>
      <a href="/Meeting.aspx?Id=11111111-2222-3333-4444-555555555555&Agenda=Agenda&lang=English">
        November 10, 2026 Board of County Commissioners Business Meeting - Agenda
      </a>
    </body></html>
    """
    docs = parse_escribe_html_fallback(
        html,
        base_url="https://pub-bouldercounty.escribemeetings.com",
        jurisdiction_id="ocd-division/country:us/state:co/county:boulder",
        year=2026,
    )
    assert len(docs) == 2
    assert docs[0].meeting_date == "2026-11-10"
    assert {d.doc_type for d in docs} == {"minutes", "agenda"}
