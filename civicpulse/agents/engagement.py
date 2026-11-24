from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from civicpulse.config import SETTINGS
from civicpulse.db import get_connection, init_db


def normalize_human_portal_url(url: str) -> str:
    raw = (url or "").strip()
    if ".api.civicclerk.com" in raw.lower():
        host = raw.split("//", 1)[-1].split("/", 1)[0]
        slug = host.split(".")[0]
        return f"https://{slug}.portal.civicclerk.com/"
    return raw


def clean_doc_title(title: str, meeting_date: str) -> str:
    t = (title or "").strip()
    if not t or re.match(r"^https?://", t, re.IGNORECASE) or "GetMeetingFileStream" in t:
        return f"{meeting_date or 'Meeting'} Council Agenda & Packet"
    return t


def build_engagement_guides(
    db_path: Optional[str] = None, out_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """Generates public/data/engagement_guides.json with normalized links and full rep contacts."""
    init_db(db_path)
    target_dir = out_dir or SETTINGS.public_data_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = get_connection(db_path)
    guides: Dict[str, Any] = {}
    try:
        jurs = conn.execute(
            "SELECT * FROM jurisdictions WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY name ASC"
        ).fetchall()

        for j in jurs:
            div_id = j["ocd_division_id"]
            portal_url = normalize_human_portal_url(j["portal_url"] or "")

            docs = conn.execute(
                """
                SELECT meeting_date, doc_type, title, source_url
                FROM documents
                WHERE jurisdiction_id = ?
                ORDER BY meeting_date DESC, doc_id DESC
                LIMIT 10
                """,
                (div_id,),
            ).fetchall()

            upcoming: List[Dict[str, str]] = []
            recent: List[Dict[str, str]] = []
            for d in docs:
                mdate = (d["meeting_date"] or "")[:10]
                item = {
                    "meeting_date": mdate,
                    "doc_type": d["doc_type"] or "agenda",
                    "title": clean_doc_title(d["title"] or "", mdate),
                    "source_url": normalize_human_portal_url(d["source_url"] or portal_url),
                }
                if mdate >= today_str:
                    upcoming.append({"date": mdate, "title": item["title"], "portal_url": item["source_url"]})
                else:
                    recent.append(item)

            reps = conn.execute(
                """
                SELECT name, role, district, email, phone, website_url
                FROM entities
                WHERE jurisdiction_id = ? AND active = 1
                ORDER BY district ASC, name ASC
                """,
                (div_id,),
            ).fetchall()

            guides[div_id] = {
                "jurisdiction_id": div_id,
                "name": j["name"],
                "portal_url": portal_url,
                "checklist": [
                    "Review the posted meeting agenda before the session to identify ordinances, budgets, or zoning items affecting your neighborhood.",
                    "Check the official portal for public comment sign-up rules, speaker time limits, or written correspondence deadlines.",
                    "Share concise, factual points with your district and at-large representatives.",
                    "Follow up after the vote to check the final roll call and implementation timeline.",
                ],
                "upcoming_meetings": upcoming[:5],
                "recent_agendas_and_docs": recent[:5],
                "representatives": [dict(r) for r in reps],
            }

        payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "guides": guides,
        }
        (target_dir / "engagement_guides.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    finally:
        conn.close()
