"""Offline unit tests for the Hands-Off Autonomous Jurisdiction Onboarding Agent."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from civicpulse.pipeline.autonomous_onboarder import (
    enqueue_local_request,
    parse_github_issue_request,
    process_pending_onboarding_requests,
)


def test_parse_github_issue_extracts_ocd_id_and_portal_url():
    issue = {
        "number": 42,
        "title": "[Request] Durango City Council",
        "body": (
            "### Jurisdiction Tracking Request\n"
            "- **Jurisdiction:** Durango City Council\n"
            "- **OCD Division ID:** ocd-division/country:us/state:co/place:durango\n"
            "- **Portal URL:** https://durangoco.portal.civicclerk.com/\n"
        ),
    }
    parsed = parse_github_issue_request(issue)
    assert parsed is not None
    assert parsed["source_key"] == "gh_issue_42"
    assert parsed["ocd_division_id"] == "ocd-division/country:us/state:co/place:durango"
    assert parsed["submitted_portal_url"] == "https://durangoco.portal.civicclerk.com/"


def test_autonomous_onboarder_activates_open_portal_and_parks_waf_blocked(tmp_path: Path):
    db = tmp_path / "auto.db"
    pub = tmp_path / "public"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (
            ocd_division_id TEXT PRIMARY KEY,
            name TEXT,
            level TEXT,
            adapter_type TEXT,
            portal_url TEXT,
            status TEXT,
            lat REAL NOT NULL DEFAULT 0.0,
            lng REAL NOT NULL DEFAULT 0.0
        );
        INSERT INTO jurisdictions VALUES (
            'ocd-division/country:us/state:co/place:durango',
            'Durango City Council', 'city', 'unclaimed', '', 'unclaimed', 37.2753, -107.8801
        );
        INSERT INTO jurisdictions VALUES (
            'ocd-division/country:us/state:co/place:loveland',
            'Loveland City Council', 'city', 'unclaimed', '', 'unclaimed', 40.3978, -105.0750
        );
    """)
    conn.commit()
    conn.close()

    enqueue_local_request(db, "Durango City Council", portal_url="https://durangoco.portal.civicclerk.com/")
    enqueue_local_request(db, "Loveland City Council", portal_url="https://www.lovgov.org/AgendaCenter")

    def fake_probe(jur_name: str, state_abbr: str = "CO", submitted_url: str = "", year=None):
        if "Durango" in jur_name:
            return {
                "status": "supported",
                "adapter_type": "civicclerk",
                "portal_url": "https://durangoco.portal.civicclerk.com/",
                "sample_count": 5,
            }
        return {
            "status": "blocked_waf",
            "adapter_type": "unclaimed",
            "portal_url": submitted_url,
            "sample_count": 0,
            "reason": "HTTP 403 WAF",
        }

    with (
        patch("civicpulse.pipeline.autonomous_onboarder.sync_github_issue_requests", return_value=0),
        patch("civicpulse.pipeline.autonomous_onboarder.probe_portal_candidates", side_effect=fake_probe),
        patch(
            "civicpulse.pipeline.autonomous_onboarder.discover_gov_roster_and_email",
            return_value=("https://www.durangogov.org/council", "council@durangogov.org"),
        ),
    ):
        res = process_pending_onboarding_requests(
            db_path=db,
            public_dir=pub,
            max_per_run=5,
            run_initial_watch=False,
        )

    assert res["processed_count"] == 2
    assert res["activated_count"] == 1

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT ocd_division_id, status FROM jurisdictions").fetchall())
    conn.close()
    assert rows["ocd-division/country:us/state:co/place:durango"] == "active"
    assert rows["ocd-division/country:us/state:co/place:loveland"] == "unclaimed"

    status_json = json.loads((pub / "data" / "onboarding_status.json").read_text(encoding="utf-8"))
    assert len(status_json["requests"]) == 2
