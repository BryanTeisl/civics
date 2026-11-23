import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from boarddocs_adapter import poll_boarddocs_jurisdiction
from db import DB_PATH, get_connection, init_db, queue_document
from granicus_adapter import poll_granicus_jurisdiction

try:
    from primegov_adapter import poll_primegov_jurisdiction
except ImportError:
    poll_primegov_jurisdiction = None


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CivicPulseBot/1.0; +https://civics-d03.pages.dev)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}


def fetch_active_jurisdictions(db_path: str = DB_PATH) -> List[sqlite3.Row]:
    conn = get_connection(db_path)
    try:
        return conn.execute(
            """
            SELECT *
            FROM jurisdictions
            WHERE (status IS NULL OR LOWER(status) = 'active')
              AND LOWER(COALESCE(adapter_type, '')) NOT IN ('', 'none', 'unclaimed')
            ORDER BY CASE WHEN poll_tier = 'fast' THEN 0 ELSE 1 END, name ASC
            """
        ).fetchall()
    finally:
        conn.close()


def mark_jurisdiction_polled(jurisdiction_id: str, db_path: str = DB_PATH) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE jurisdictions SET last_polled_at = ? WHERE ocd_division_id = ?",
            (now_iso, jurisdiction_id),
        )
        conn.commit()
    finally:
        conn.close()


def poll_civicclerk(jur: sqlite3.Row, max_events: int = 10) -> int:
    """Polls a CivicClerk OData Events feed and queues meeting summaries/agendas/minutes."""
    portal_url = (jur["portal_url"] or "").strip()
    slug = ""
    if "portal.civicclerk.com" in portal_url:
        host_part = portal_url.split("//", 1)[-1].split("/", 1)[0]
        slug = host_part.split(".portal.civicclerk.com")[0]
    if not slug:
        return 0

    api_url = f"https://{slug}.api.civicclerk.com/v1/Events?$top={max_events}&$orderby=startDateTime%20desc"
    resp = requests.get(api_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    events: List[Dict[str, Any]] = resp.json().get("value", [])

    queued = 0
    for ev in events:
        ev_id = str(ev.get("id") or "")
        ev_name = (ev.get("eventName") or "Council Meeting").strip()
        start_dt = str(ev.get("startDateTime") or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        files = ev.get("publishedFiles") or []
        summary_lines = [
            f"Meeting: {ev_name}",
            f"Date: {start_dt}",
            f"Jurisdiction: {jur['name']}",
        ]
        for f_item in files:
            f_name = f_item.get("name") or f_item.get("fileType") or "Document"
            f_id = f_item.get("fileId")
            summary_lines.append(f"Attachment: {f_name} (fileId={f_id})")

        raw_text = "\n".join(summary_lines)
        inserted = queue_document(
            jurisdiction_id=jur["ocd_division_id"],
            doc_type="agenda",
            title=f"{start_dt} — {ev_name}",
            source_url=portal_url,
            raw_text=raw_text,
            meeting_date=start_dt,
            external_id=f"civicclerk-{slug}-{ev_id}",
        )
        if inserted:
            queued += 1

    print(f"[WATCH] {jur['name']} (civicclerk) -> Found {len(events)} events, queued {queued} new.")
    return queued


def poll_legistar(jur: sqlite3.Row, max_events: int = 10) -> int:
    """Polls a Legistar REST API client and queues recent events for processing."""
    portal_url = (jur["portal_url"] or "").strip().lower()
    client = ""
    if "coloradosprings.legistar.com" in portal_url:
        client = "coloradosprings"
    elif "denver" in portal_url or "denver" in (jur["name"] or "").lower():
        client = "denver"
    else:
        for part in portal_url.replace("https://", "").replace("http://", "").split("/"):
            if ".legistar.com" in part:
                client = part.split(".legistar.com")[0]
                break
    if not client:
        return 0

    api_url = f"https://webapi.legistar.com/v1/{client}/events?$top={max_events}&$orderby=EventDate%20desc"
    resp = requests.get(api_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    items: List[Dict[str, Any]] = resp.json()

    queued = 0
    for item in items:
        ev_id = str(item.get("EventId") or "")
        body_name = (item.get("EventBodyName") or "Legislative Body").strip()
        ev_date = str(item.get("EventDate") or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        matter_text = (item.get("EventComment") or item.get("EventLocation") or body_name).strip()
        source_url = item.get("EventAgendaFile") or item.get("EventMinutesFile") or jur["portal_url"]

        raw_text = (
            f"Body: {body_name}\n"
            f"Date: {ev_date}\n"
            f"Details: {matter_text}\n"
            f"EventId: {ev_id}"
        )
        inserted = queue_document(
            jurisdiction_id=jur["ocd_division_id"],
            doc_type="minutes" if item.get("EventMinutesFile") else "agenda",
            title=f"{ev_date} {body_name}: {matter_text[:90]}",
            source_url=source_url,
            raw_text=raw_text,
            meeting_date=ev_date,
            external_id=f"legistar-{client}-{ev_id}",
        )
        if inserted:
            queued += 1

    print(f"[WATCH] {jur['name']} (legistar) -> Found {len(items)} events, queued {queued} new.")
    return queued


def run_watcher(db_path: str = DB_PATH) -> int:
    init_db(db_path)
    jurisdictions = fetch_active_jurisdictions(db_path)
    total_queued = 0

    for jur in jurisdictions:
        adapter = (jur["adapter_type"] or "").strip().lower()
        jur_id = jur["ocd_division_id"]
        name = jur["name"]
        portal_url = jur["portal_url"]

        try:
            if adapter == "civicclerk":
                total_queued += poll_civicclerk(jur)
            elif adapter == "legistar":
                total_queued += poll_legistar(jur)
            elif adapter == "primegov":
                if poll_primegov_jurisdiction:
                    print(f"[WATCH] {name} (primegov)...")
                    total_queued += poll_primegov_jurisdiction(
                        jurisdiction_id=jur_id,
                        name=name,
                        portal_url=portal_url,
                    )
                else:
                    print(f"  ! primegov_adapter.py not found; skipping {name}")
            elif adapter == "boarddocs":
                print(f"[WATCH] {name} (boarddocs)...")
                total_queued += poll_boarddocs_jurisdiction(
                    jurisdiction_id=jur_id,
                    name=name,
                    portal_url=portal_url,
                )
            elif adapter == "granicus":
                print(f"[WATCH] {name} (granicus)...")
                total_queued += poll_granicus_jurisdiction(
                    jurisdiction_id=jur_id,
                    name=name,
                    portal_url=portal_url,
                )
            else:
                print(f"  ! Unsupported adapter '{adapter}' for {name}; skipping.")
                continue

            mark_jurisdiction_polled(jur_id, db_path)
        except Exception as exc:
            print(f"  ! Error polling {name} ({adapter}): {exc}")

    print(f"Watcher complete. Queued PDFs/Docs: {total_queued} | Structured Vote Events: 0")
    return total_queued


if __name__ == "__main__":
    run_watcher()
