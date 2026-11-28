"""Scaled Before-the-Vote Agenda Preview Generator (civicpulse/pipeline/scale_agenda_previews.py).

Scans upcoming and recent `agenda` documents across ALL active jurisdictions in
`core_civic.db`, extracts top 3-4 substantive policy items deterministically with
optional Ollama plain-English enrichment (`--use-ollama`), and writes
`public/data/agenda_previews.json`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

SUBSTANTIVE_HINTS = re.compile(
    r"\b(ordinance|resolution|zoning|rezon|budget|tax|fee|utility|housing|development|"
    r"annexation|contract|agreement|appropriation|capital|transit|water|park|amendment|public\s+hearing)\b",
    re.IGNORECASE,
)
SKIP_LINE_RE = re.compile(
    r"^\s*(call to order|roll call|pledge|adjourn|approval of minutes|executive session|"
    r"page\s+\d+|council\s+member|mayor|city\s+clerk|public\s+comment|announcements)\b",
    re.IGNORECASE,
)


def extract_substantive_items_from_text(raw_text: str, max_items: int = 4) -> List[Dict[str, str]]:
    if not raw_text:
        return []
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw_text.splitlines()]
    items: List[Dict[str, str]] = []
    seen = set()

    for ln in lines:
        if len(ln) < 28 or len(ln) > 260:
            continue
        if SKIP_LINE_RE.search(ln):
            continue
        if not SUBSTANTIVE_HINTS.search(ln):
            continue
        clean = re.sub(r"^\s*(?:[0-9]+[A-Za-z]?\.|[A-Z]\.|Item\s+[0-9A-Za-z.-]+:?)\s*", "", ln).strip(" -:")
        key = re.sub(r"[^a-z0-9]+", " ", clean.lower()).strip()[:48]
        if len(clean) < 22 or key in seen:
            continue
        seen.add(key)
        items.append({"title": clean[:180], "plain_summary": ""})
        if len(items) >= max_items:
            break
    return items


def polish_item_summary_ollama(jur_name: str, item_title: str) -> str:
    prompt = (
        f"In 1 short neutral plain-English sentence (under 25 words), explain what this upcoming "
        f"{jur_name} agenda item is about for a local resident:\n{item_title}"
    )
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 60},
            },
            timeout=25,
        )
        if r.status_code == 200:
            txt = re.sub(r"\s+", " ", (r.json().get("response") or "")).strip()
            if 15 <= len(txt) <= 220:
                return txt
    except Exception:
        pass
    return ""


def generate_scaled_agenda_previews(
    db_path: Path = Path("core_civic.db"),
    out_path: Path = Path("public/data/agenda_previews.json"),
    days_back: int = 7,
    days_ahead: int = 45,
    use_ollama: bool = False,
) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    today = dt.date.today()
    start_iso = (today - dt.timedelta(days=days_back)).isoformat()
    end_iso = (today + dt.timedelta(days=days_ahead)).isoformat()

    rows = conn.execute(
        """
        SELECT d.doc_id, d.jurisdiction_id, j.name AS jurisdiction_name,
               d.meeting_date, d.title, d.source_url, d.raw_text, j.portal_url
        FROM documents d
        JOIN jurisdictions j ON j.ocd_division_id = d.jurisdiction_id
        WHERE j.status = 'active'
          AND LOWER(d.doc_type) = 'agenda'
          AND d.meeting_date IS NOT NULL
          AND d.meeting_date >= ?
          AND d.meeting_date <= ?
        ORDER BY d.meeting_date ASC, d.doc_id DESC
        """,
        (start_iso, end_iso),
    ).fetchall()
    conn.close()

    previews: List[Dict[str, Any]] = []
    seen_meetings = set()
    jurs_covered = set()

    for r in rows:
        mkey = (r["jurisdiction_id"], str(r["meeting_date"])[:10], (r["title"] or "")[:40].lower())
        if mkey in seen_meetings:
            continue
        seen_meetings.add(mkey)

        items = extract_substantive_items_from_text(r["raw_text"] or "", max_items=4)
        if use_ollama:
            for it in items[:3]:
                it["plain_summary"] = polish_item_summary_ollama(r["jurisdiction_name"], it["title"])

        previews.append(
            {
                "doc_id": r["doc_id"],
                "jurisdiction_id": r["jurisdiction_id"],
                "jurisdiction_name": r["jurisdiction_name"],
                "meeting_date": str(r["meeting_date"])[:10],
                "meeting_title": r["title"] or "Scheduled Council / Board Meeting",
                "source_url": r["source_url"] or r["portal_url"] or "",
                "items": items,
                "has_extracted_items": len(items) > 0,
            }
        )
        jurs_covered.add(r["jurisdiction_id"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(previews, indent=2) + "\n", encoding="utf-8")
    return {
        "previews_written": len(previews),
        "with_substantive_items": sum(1 for p in previews if p["has_extracted_items"]),
        "jurisdictions_covered": len(jurs_covered),
        "path": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scale Before-the-Vote agenda previews across all active jurisdictions")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--out", default="public/data/agenda_previews.json")
    parser.add_argument("--use-ollama", action="store_true")
    args = parser.parse_args()
    res = generate_scaled_agenda_previews(Path(args.db), Path(args.out), use_ollama=args.use_ollama)
    print("[AGENDA-PREVIEWS-SCALED]", json.dumps(res))


if __name__ == "__main__":
    main()
