"""Offline unit tests for v3.1 Planning & Zoning Early Warning and Growth Configurator."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from civicpulse.pipeline.early_warning import build_planning_early_warning, is_planning_commission_meeting
from scripts.configure_growth import inject_cloudflare_analytics, update_payment_links


def test_planning_commission_detector_matches_land_use_bodies_only():
    assert is_planning_commission_meeting("Planning & Zoning Commission Regular Meeting") is True
    assert is_planning_commission_meeting("Board of Adjustment Public Hearing") is True
    assert is_planning_commission_meeting("City Council Regular Meeting") is False
    assert is_planning_commission_meeting("Parks and Recreation Advisory Board") is False


def test_build_planning_early_warning_offline_from_sqlite(tmp_path: Path):
    db = tmp_path / "ew.db"
    pub = tmp_path / "public"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE jurisdictions (ocd_division_id TEXT PRIMARY KEY, name TEXT, adapter_type TEXT, portal_url TEXT, status TEXT);
        CREATE TABLE documents (doc_id INTEGER PRIMARY KEY, jurisdiction_id TEXT, meeting_date TEXT, title TEXT, source_url TEXT);
        INSERT INTO jurisdictions VALUES ('j1', 'Fort Collins City Council', 'civicclerk', 'https://fortcollinsco.portal.civicclerk.com/', 'active');
        INSERT INTO documents VALUES (1, 'j1', '2026-12-03', 'Planning and Zoning Commission Hearing', 'https://example.gov/pz');
        INSERT INTO documents VALUES (2, 'j1', '2026-12-01', 'City Council Regular Meeting', 'https://example.gov/cc');
    """)
    conn.commit()
    conn.close()

    res = build_planning_early_warning(str(db), pub, lookback_days=60, live_poll=False)
    assert res["total"] == 1
    out = json.loads((pub / "data" / "planning_early_warning.json").read_text(encoding="utf-8"))
    assert out["hearings"][0]["title"] == "Planning and Zoning Commission Hearing"


def test_cloudflare_analytics_and_payment_links_configurator(tmp_path: Path):
    html_f = tmp_path / "index.html"
    html_f.write_text("<html><body><h1>CivicPulse</h1></body></html>", encoding="utf-8")
    assert inject_cloudflare_analytics(html_f, "abc123token") is True
    txt = html_f.read_text(encoding="utf-8")
    assert "static.cloudflareinsights.com/beacon.min.js" in txt
    assert "abc123token" in txt

    # Idempotent re-injection replaces cleanly without duplicating
    assert inject_cloudflare_analytics(html_f, "newtoken456") is True
    txt2 = html_f.read_text(encoding="utf-8")
    assert txt2.count("beacon.min.js") == 1
    assert "newtoken456" in txt2

    cfg_f = tmp_path / "patrons.json"
    data = update_payment_links(cfg_f, {"individual_15": "https://ko-fi.com/civicpulse", "business_patron_monthly": "https://buy.stripe.com/test"})
    assert data["checkout_links"]["individual_15"] == "https://ko-fi.com/civicpulse"
    assert data["checkout_links"]["business_patron_monthly"] == "https://buy.stripe.com/test"
