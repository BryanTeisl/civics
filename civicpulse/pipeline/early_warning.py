"""Metadata-only Planning & Zoning Early Warning feed for CivicPulse v3.1.

Captures upcoming & recent Planning Commission, Zoning Board of Adjustment, and
Land Use hearing agendas directly from active Legistar, CivicClerk, and PrimeGov
portals WITHOUT running local Ollama LLM vote extraction (zero CPU/GPU cost).

Exports: public/data/planning_early_warning.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

HEADERS = {
    "User-Agent": "CivicPulseBot/3.1 (+https://civics-d03.pages.dev)",
    "Accept": "application/json",
}

PLANNING_RE = re.compile(
    r"\b("
    r"planning\s*(?:and|&)?\s*zoning|planning\s+commission|zoning\s+board|"
    r"board\s+of\s+adjustment|land\s+use|development\s+review|"
    r"planning\s+board|urban\s+renewal|annexation|historic\s+preservation"
    r")\b",
    re.IGNORECASE,
)


def is_planning_commission_meeting(title: str) -> bool:
    """Returns True for Planning, Zoning, Land Use, or Board of Adjustment hearings."""
    return bool(PLANNING_RE.search(title or ""))


def _fetch_legistar_planning(jid: str, name: str, portal_url: str, cutoff_iso: str, timeout: int = 15) -> List[Dict[str, Any]]:
    host = urlparse(portal_url or "").netloc.lower()
    if ".legistar.com" not in host:
        return []
    client = host.split(".legistar.com")[0]
    url = f"https://webapi.legistar.com/v1/{client}/Events"
    try:
        r = requests.get(
            url,
            params={"$top": 50, "$orderby": "EventDate desc", "$filter": f"EventDate ge datetime'{cutoff_iso}'"},
            headers=HEADERS,
            timeout=timeout,
        )
        if not r.ok:
            return []
        items = []
        for ev in r.json() if isinstance(r.json(), list) else []:
            body = (ev.get("EventBodyName") or "").strip()
            if not is_planning_commission_meeting(body):
                continue
            dt = str(ev.get("EventDate") or "")[:10]
            agenda_url = ev.get("EventAgendaFile") or ev.get("EventInSiteURL") or portal_url
            items.append({
                "jurisdiction_id": jid,
                "jurisdiction_name": name,
                "body_name": body,
                "meeting_date": dt,
                "title": f"{body} — {dt}",
                "agenda_url": agenda_url,
                "platform": "legistar",
            })
        return items
    except Exception:
        return []


def _fetch_civicclerk_planning(jid: str, name: str, portal_url: str, cutoff_iso: str, timeout: int = 15) -> List[Dict[str, Any]]:
    host = urlparse(portal_url or "").netloc.lower()
    m = re.match(r"^([a-z0-9-]+)\.(?:portal|api)\.civicclerk\.com$", host)
    if not m:
        return []
    tenant = m.group(1)
    url = f"https://{tenant}.api.civicclerk.com/v1/Events"
    try:
        r = requests.get(
            url,
            params={"$top": 60, "$orderby": "startDateTime desc"},
            headers=HEADERS,
            timeout=timeout,
        )
        if not r.ok:
            return []
        items = []
        for ev in (r.json().get("value") or []):
            ename = (ev.get("eventName") or "").strip()
            dt = str(ev.get("startDateTime") or "")[:10]
            if not dt or dt < cutoff_iso or not is_planning_commission_meeting(ename):
                continue
            ev_id = ev.get("id")
            agenda_url = f"https://{tenant}.portal.civicclerk.com/event/{ev_id}/files" if ev_id else portal_url
            items.append({
                "jurisdiction_id": jid,
                "jurisdiction_name": name,
                "body_name": ename,
                "meeting_date": dt,
                "title": ename,
                "agenda_url": agenda_url,
                "platform": "civicclerk",
            })
        return items
    except Exception:
        return []


def _fetch_primegov_planning(jid: str, name: str, portal_url: str, cutoff_iso: str, year: int, timeout: int = 15) -> List[Dict[str, Any]]:
    host = urlparse(portal_url or "").netloc.lower()
    if ".primegov.com" not in host:
        return []
    items = []
    for ep in (f"ListUpcomingMeetings", f"ListArchivedMeetings?year={year}"):
        url = f"https://{host}/api/v2/PublicPortal/{ep}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if not r.ok:
                continue
            for m in r.json() if isinstance(r.json(), list) else []:
                title = (m.get("title") or "").strip()
                dt = str(m.get("dateTime") or "")[:10]
                if not dt or dt < cutoff_iso or not is_planning_commission_meeting(title):
                    continue
                docs = m.get("documentList") or []
                agenda_url = f"https://{host}/public/portal"
                if docs and docs[0].get("id"):
                    agenda_url = f"https://{host}/Portal/Meeting?meetingTemplateId={docs[0]['id']}"
                items.append({
                    "jurisdiction_id": jid,
                    "jurisdiction_name": name,
                    "body_name": title,
                    "meeting_date": dt,
                    "title": title,
                    "agenda_url": agenda_url,
                    "platform": "primegov",
                })
        except Exception:
            continue
    return items


def build_planning_early_warning(
    db_path: str = "core_civic.db",
    public_dir: Path = Path("public"),
    lookback_days: int = 30,
    live_poll: bool = True,
) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    today_iso = now_utc.strftime("%Y-%m-%d")
    cutoff_iso = (now_utc - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    year = now_utc.year

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    collected: List[Dict[str, Any]] = []

    try:
        # 1. Include any already-cached Planning/Zoning docs from SQLite documents table
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "documents" in tables:
            for r in conn.execute(
                """
                SELECT d.jurisdiction_id, d.meeting_date, d.title, d.source_url,
                       j.name AS jurisdiction_name, COALESCE(j.adapter_type, '') AS adapter_type
                FROM documents d
                JOIN jurisdictions j ON j.ocd_division_id = d.jurisdiction_id
                WHERE COALESCE(j.status, 'active') = 'active'
                  AND d.meeting_date >= ?
                ORDER BY d.meeting_date DESC
                """,
                (cutoff_iso,),
            ).fetchall():
                if is_planning_commission_meeting(r["title"]):
                    collected.append({
                        "jurisdiction_id": r["jurisdiction_id"],
                        "jurisdiction_name": r["jurisdiction_name"],
                        "body_name": r["title"],
                        "meeting_date": r["meeting_date"],
                        "title": r["title"],
                        "agenda_url": r["source_url"] or "",
                        "platform": r["adapter_type"] or "cached",
                    })

        # 2. Live metadata-only poll from active structured portals
        if live_poll:
            jurs = conn.execute(
                """
                SELECT ocd_division_id, name, adapter_type, portal_url
                FROM jurisdictions
                WHERE COALESCE(status, 'active') = 'active'
                ORDER BY name ASC
                """
            ).fetchall()
            for j in jurs:
                adp = (j["adapter_type"] or "").lower()
                if adp == "legistar":
                    collected.extend(_fetch_legistar_planning(j["ocd_division_id"], j["name"], j["portal_url"], cutoff_iso))
                elif adp == "civicclerk":
                    collected.extend(_fetch_civicclerk_planning(j["ocd_division_id"], j["name"], j["portal_url"], cutoff_iso))
                elif adp == "primegov":
                    collected.extend(_fetch_primegov_planning(j["ocd_division_id"], j["name"], j["portal_url"], cutoff_iso, year))
    finally:
        conn.close()

    # Deduplicate & sort (upcoming first, then most recent past)
    dedup: Dict[tuple, Dict[str, Any]] = {}
    for item in collected:
        key = (item["jurisdiction_id"], item["meeting_date"], item["title"][:60].lower())
        if key not in dedup:
            item["is_upcoming"] = (item["meeting_date"] or "") >= today_iso
            dedup[key] = item

    final_items = sorted(
        dedup.values(),
        key=lambda x: (not x["is_upcoming"], x["meeting_date"] if x["is_upcoming"] else "", x["jurisdiction_name"]),
    )
    # Reverse past items so most recent past appears first after upcoming
    upcoming = [x for x in final_items if x["is_upcoming"]]
    recent_past = sorted([x for x in final_items if not x["is_upcoming"]], key=lambda x: x["meeting_date"], reverse=True)
    ordered = (upcoming + recent_past)[:80]

    payload = {
        "schema_version": "3.1",
        "as_of_date": today_iso,
        "lookback_days": lookback_days,
        "upcoming_count": len(upcoming),
        "total_count": len(ordered),
        "hearings": ordered,
    }
    out_path = public_dir / "data" / "planning_early_warning.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"upcoming": len(upcoming), "total": len(ordered), "path": str(out_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export metadata-only Planning & Zoning Early Warning feed.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--public-dir", default="public")
    parser.add_argument("--no-live-poll", action="store_true", help="Only read cached SQLite documents")
    args = parser.parse_args()
    res = build_planning_early_warning(args.db, Path(args.public_dir), live_poll=not args.no_live_poll)
    print("[EARLY-WARNING]", json.dumps(res))


if __name__ == "__main__":
    main()
