"""Zero-Pollution 14-Day Upcoming Agenda Preview Engine (CivicPulse v3.2).

Extracts plain-English previews of upcoming council agendas (next 14 days) into
`public/data/agenda_previews.json` WITHOUT touching `events` or `entity_actions`.

Strict Isolation & Trust Guardrails:
  1. Never writes to `events` or `entity_actions` — attendance %, roll-call tallies,
     and Impact Scores remain 100% anchored to post-meeting official records.
  2. Automatically retires any preview once post-meeting `events` exist for that
     jurisdiction and meeting_date.
  3. Supports zero-CPU deterministic agenda-item parsing by default, with optional
     local Ollama (`qwen2.5:3b`) plain-English summarization via `--use-ollama`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from civicpulse.pipeline.normalize import classify_topic, is_business_relevant

ITEM_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:Item\s+#?\d+[A-Za-z]?|Ordinance\s+No\.?\s*[\w-]+|Resolution\s+No\.?\s*[\w-]+|"
    r"Public\s+Hearing\s+#?\d*|[A-Z0-9]{1,4}\.\s+[A-Z])[^\n]{12,180}",
    re.MULTILINE,
)

NOISE_LINE_RE = re.compile(
    r"\b(call\s+to\s+order|pledge\s+of\s+allegiance|roll\s+call|adjournment|executive\s+session\s+procedures|"
    r"public\s+comment\s+guidelines|approval\s+of\s+minutes)\b",
    re.IGNORECASE,
)


def extract_agenda_highlights_deterministic(raw_text: str, max_items: int = 6) -> List[Dict[str, Any]]:
    """Extracts substantive agenda items from raw agenda text with zero LLM calls."""
    text = (raw_text or "").strip()
    if len(text) < 40:
        return []

    seen = set()
    items: List[Dict[str, Any]] = []
    for m in ITEM_HEADING_RE.finditer(text):
        line = re.sub(r"\s+", " ", m.group(0)).strip(" :-•\t\r\n")
        if len(line) < 16 or NOISE_LINE_RE.search(line):
            continue
        key = line[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        topic = classify_topic(line, "", None)
        items.append({
            "title": line[:180],
            "topic": topic,
            "business_relevant": is_business_relevant(topic),
            "plain_summary": "Scheduled for upcoming consideration — review the official agenda packet for staff memo and public comment instructions.",
        })
        if len(items) >= max_items:
            break
    return items


def summarize_agenda_with_ollama(
    raw_text: str,
    jurisdiction_name: str,
    meeting_date: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: int = 120,
) -> List[Dict[str, Any]]:
    """Optional local Ollama summarizer for a single upcoming agenda (strictly neutral, max 5 items)."""
    mdl = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    url = (base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/") + "/api/generate"
    snippet = (raw_text or "")[:14000]
    prompt = (
        f"You are summarizing an UPCOMING draft agenda for {jurisdiction_name} on {meeting_date}.\n"
        "Extract up to 5 substantive ordinances, resolutions, budgets, contracts, or zoning hearings.\n"
        "Rules:\n"
        "- Skip procedural items (Call to Order, Pledge, Roll Call, Adjournment).\n"
        "- Do NOT state that any item passed or failed; it has not been voted on yet.\n"
        "- Keep plain_summary neutral, factual, and under 35 words.\n"
        'Return ONLY valid JSON: {"items": [{"title": "...", "plain_summary": "..."}]}\n\n'
        f"AGENDA TEXT:\n{snippet}"
    )
    try:
        r = requests.post(
            url,
            json={
                "model": mdl,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024},
            },
            timeout=timeout,
        )
        if not r.ok:
            return extract_agenda_highlights_deterministic(raw_text)
        data = json.loads(r.json().get("response") or "{}")
        out = []
        for it in (data.get("items") or [])[:5]:
            t = re.sub(r"\s+", " ", str(it.get("title") or "")).strip()
            s = re.sub(r"\s+", " ", str(it.get("plain_summary") or "")).strip()
            if len(t) < 10 or NOISE_LINE_RE.search(t):
                continue
            topic = classify_topic(t, s, None)
            out.append({
                "title": t[:180],
                "topic": topic,
                "business_relevant": is_business_relevant(topic),
                "plain_summary": s[:240] or "Scheduled for upcoming consideration.",
            })
        return out or extract_agenda_highlights_deterministic(raw_text)
    except Exception:
        return extract_agenda_highlights_deterministic(raw_text)


def build_agenda_previews(
    db_path: str = "core_civic.db",
    public_dir: Path = Path("public"),
    horizon_days: int = 14,
    use_ollama: bool = False,
    max_docs: int = 12,
) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    today_iso = now_utc.strftime("%Y-%m-%d")
    cutoff_iso = (now_utc + timedelta(days=horizon_days)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    previews: List[Dict[str, Any]] = []

    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "documents" not in tables:
            return {"count": 0, "previews": []}

        completed_dates = {
            (r["jurisdiction_id"], r["meeting_date"])
            for r in conn.execute("SELECT DISTINCT jurisdiction_id, meeting_date FROM events").fetchall()
        }

        rows = conn.execute(
            """
            SELECT d.doc_id, d.jurisdiction_id, d.meeting_date, d.title, d.source_url,
                   COALESCE(d.raw_text, '') AS raw_text,
                   j.name AS jurisdiction_name,
                   COALESCE(j.portal_url, '') AS portal_url
            FROM documents d
            JOIN jurisdictions j ON j.ocd_division_id = d.jurisdiction_id
            WHERE LOWER(d.doc_type) = 'agenda'
              AND COALESCE(j.status, 'active') = 'active'
              AND d.meeting_date >= ?
              AND d.meeting_date <= ?
            ORDER BY d.meeting_date ASC, j.name ASC
            LIMIT ?
            """,
            (today_iso, cutoff_iso, max_docs),
        ).fetchall()

        seen_meetings = set()
        for r in rows:
            key = (r["jurisdiction_id"], r["meeting_date"])
            if key in completed_dates or key in seen_meetings:
                continue
            seen_meetings.add(key)

            raw = r["raw_text"]
            if use_ollama and len(raw.strip()) >= 120:
                items = summarize_agenda_with_ollama(raw, r["jurisdiction_name"], r["meeting_date"])
                mode = "ollama_preview"
            else:
                items = extract_agenda_highlights_deterministic(raw)
                mode = "agenda_metadata"

            previews.append({
                "doc_id": r["doc_id"],
                "jurisdiction_id": r["jurisdiction_id"],
                "jurisdiction_name": r["jurisdiction_name"],
                "meeting_date": r["meeting_date"],
                "meeting_title": r["title"] or "Upcoming Regular Meeting",
                "agenda_url": r["source_url"] or r["portal_url"],
                "portal_url": r["portal_url"],
                "capture_method": "agenda_preview",
                "preview_mode": mode,
                "status_label": "Draft Agenda Preview — Not Yet Voted On",
                "items": items,
            })
    finally:
        conn.close()

    payload = {
        "schema_version": "3.2",
        "as_of_date": today_iso,
        "horizon_days": horizon_days,
        "disclaimer": (
            "Draft Agenda Previews summarize scheduled items before a vote occurs. "
            "Items may be amended, continued, or pulled at the meeting. Verify official packets."
        ),
        "count": len(previews),
        "previews": previews,
    }
    out_path = public_dir / "data" / "agenda_previews.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"count": len(previews), "path": str(out_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build zero-pollution 14-day Upcoming Agenda Previews.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--public-dir", default="public")
    parser.add_argument("--horizon-days", type=int, default=14)
    parser.add_argument("--use-ollama", action="store_true", help="Use local Ollama for plain-English summaries")
    parser.add_argument("--max-docs", type=int, default=12)
    args = parser.parse_args()
    res = build_agenda_previews(
        db_path=args.db,
        public_dir=Path(args.public_dir),
        horizon_days=args.horizon_days,
        use_ollama=args.use_ollama,
        max_docs=args.max_docs,
    )
    print("[AGENDA-PREVIEW]", json.dumps(res))


if __name__ == "__main__":
    main()
