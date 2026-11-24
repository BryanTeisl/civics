import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

from db import DB_PATH, get_connection, init_db

OUTPUT_GUIDES_PATH = Path("public/data/engagement_guides.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CivicPulseBot/1.0; +https://civics-d03.pages.dev)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}


def _fetch_upcoming_primegov(portal_url: str, limit: int = 5) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if not portal_url or "primegov.com" not in portal_url:
        return items
    try:
        host = portal_url.split("//", 1)[-1].split("/", 1)[0]
        sub = host.split(".primegov.com")[0]
        url = f"https://{sub}.primegov.com/api/v2/PublicPortal/ListUpcomingMeetings"
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code == 200 and isinstance(r.json(), list):
            for mtg in r.json()[:limit]:
                items.append({
                    "title": (mtg.get("title") or "Upcoming Public Meeting").strip(),
                    "date": str(mtg.get("dateTime") or mtg.get("date") or "")[:16],
                    "portal_url": portal_url,
                })
    except Exception:
        pass
    return items


def build_engagement_guide_for_jurisdiction(conn: sqlite3.Connection, jur: sqlite3.Row) -> Dict[str, Any]:
    div_id = jur["ocd_division_id"]
    reps = conn.execute(
        """
        SELECT ocd_person_id, name, role, district, email, phone, website_url
        FROM entities
        WHERE jurisdiction_id = ? AND active = 1
        ORDER BY district ASC, name ASC
        """,
        (div_id,),
    ).fetchall()

    recent_docs = conn.execute(
        """
        SELECT doc_id, meeting_date, doc_type, title, source_url
        FROM documents
        WHERE jurisdiction_id = ?
        ORDER BY meeting_date DESC, doc_id DESC
        LIMIT 5
        """,
        (div_id,),
    ).fetchall()

    upcoming = _fetch_upcoming_primegov(jur["portal_url"] or "")

    rep_contacts = [
        {
            "ocd_person_id": r["ocd_person_id"],
            "name": r["name"],
            "role": r["role"] or "Representative",
            "district": r["district"] or "At-Large",
            "email": r["email"] or "",
            "phone": r["phone"] or "",
            "website_url": r["website_url"] or jur["portal_url"] or "",
        }
        for r in reps
    ]

    recent_items = [
        {
            "meeting_date": d["meeting_date"] or "",
            "doc_type": d["doc_type"] or "agenda",
            "title": d["title"] or "Meeting Record",
            "source_url": d["source_url"] or jur["portal_url"] or "",
        }
        for d in recent_docs
    ]

    checklist = [
        "Review the posted meeting agenda and staff memo before the session to identify ordinances, budgets, or zoning items affecting your neighborhood.",
        "Check the official portal for public comment sign-up rules, speaker time limits, or written correspondence deadlines.",
        "Share concise, factual points—such as how a proposal affects housing, traffic, school/county services, or local budgets—with your district and at-large representatives.",
        "Follow up after the vote to check the final roll call, ordinance number, and implementation timeline.",
    ]

    return {
        "ocd_division_id": div_id,
        "jurisdiction_name": jur["name"],
        "level": jur["level"],
        "portal_url": jur["portal_url"] or "",
        "checklist": checklist,
        "upcoming_meetings": upcoming,
        "recent_agendas_and_docs": recent_items,
        "representatives": rep_contacts,
        "disclaimer": "Verify exact hearing dates, comment registration deadlines, and contact details on the official government portal before attending.",
    }


def run_agent_3_engagement_guides(db_path: str = DB_PATH, output_path: Path = OUTPUT_GUIDES_PATH) -> Dict[str, Any]:
    init_db(db_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        jurs = conn.execute(
            """
            SELECT * FROM jurisdictions
            WHERE (status IS NULL OR LOWER(status) = 'active')
            ORDER BY name ASC
            """
        ).fetchall()

        guides: Dict[str, Any] = {}
        for jur in jurs:
            guide = build_engagement_guide_for_jurisdiction(conn, jur)
            guides[jur["ocd_division_id"]] = guide

        payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "guide_count": len(guides),
            "guides": guides,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[Agent 3 - Civic Literacy & How to Engage] Exported {len(guides)} guide(s) to {output_path}")
        return payload
    finally:
        conn.close()


if __name__ == "__main__":
    run_agent_3_engagement_guides()
