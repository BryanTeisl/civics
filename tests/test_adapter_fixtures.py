"""Fixture-backed portal parser contract tests (offline, safe for GitHub Actions CI)."""
from __future__ import annotations

import json
from pathlib import Path

from civicpulse.pipeline.normalize import detect_body_type

FIXTURES = Path(__file__).parent / "fixtures"


def test_legistar_fixture_separates_full_council_and_committee():
    events = json.loads((FIXTURES / "legistar_events_sample.json").read_text(encoding="utf-8"))
    assert len(events) == 2
    assert detect_body_type("Ordinance 1", events[0]["EventBodyName"]) == "full_body"
    assert detect_body_type("Rezoning 2", events[1]["EventBodyName"]) == "committee"


def test_civicclerk_fixture_identifies_minutes_over_agenda_and_filters_advisory():
    payload = json.loads((FIXTURES / "civicclerk_events_sample.json").read_text(encoding="utf-8"))
    council_events = [e for e in payload["value"] if "Council" in e["eventName"]]
    assert len(council_events) == 1
    files = council_events[0]["publishedFiles"]
    minutes = [f for f in files if "minute" in f["type"].lower()]
    assert len(minutes) == 1 and minutes[0]["fileId"] == 9002


def test_primegov_fixture_contains_compiled_minutes_document():
    meetings = json.loads((FIXTURES / "primegov_meetings_sample.json").read_text(encoding="utf-8"))
    docs = meetings[0]["documentList"]
    minutes_docs = [d for d in docs if "minute" in d["templateName"].lower()]
    assert len(minutes_docs) == 1 and minutes_docs[0]["id"] == 442
