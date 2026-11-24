from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from civicpulse.config import SETTINGS
from civicpulse.db import get_connection, init_db
from civicpulse.pipeline.metrics import compute_impact_score


def _call_ollama_extract(raw_text: str, title: str) -> List[Dict[str, Any]]:
    prompt = (
        "You are a neutral, nonpartisan civic records extractor. "
        "Given the meeting document text below, extract any formal votes, ordinances, resolutions, or motions.\n"
        "Return ONLY valid JSON with key 'events' containing a list of objects with keys: "
        "title, event_type (ordinance|resolution|budget|motion|consent), topic, outcome (Passed|Failed|Tabled), "
        "yes_count (int), no_count (int), abstain_count (int), absent_count (int), plain_summary, diff_summary.\n"
        f"DOCUMENT TITLE: {title}\n"
        f"TEXT:\n{raw_text[:7000]}"
    )
    resp = requests.post(
        SETTINGS.ollama_url,
        json={"model": SETTINGS.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
        timeout=90,
    )
    resp.raise_for_status()
    payload = json.loads(resp.json().get("response", "{}"))
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return events if isinstance(events, list) else []


def run_worker(
    db_path: Optional[str] = None,
    limit: int = 10,
    max_retries: int = 3,
) -> Dict[str, int]:
    """Processes pending documents using local Ollama with retry & dead-letter status handling."""
    init_db(db_path)
    conn = get_connection(db_path)
    stats = {"processed": 0, "events_created": 0, "failed": 0, "skipped": 0}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        docs = conn.execute(
            """
            SELECT * FROM documents
            WHERE status = 'pending' AND COALESCE(retry_count, 0) < ?
            ORDER BY meeting_date DESC, doc_id ASC
            LIMIT ?
            """,
            (max_retries, limit),
        ).fetchall()

        for doc in docs:
            raw_text = (doc["raw_text"] or "").strip()
            if not raw_text:
                conn.execute(
                    "UPDATE documents SET status = 'skipped', error_message = 'No raw_text available yet', processed_at = ? WHERE doc_id = ?",
                    (now_iso, doc["doc_id"]),
                )
                stats["skipped"] += 1
                continue

            try:
                extracted = _call_ollama_extract(raw_text, doc["title"] or "")
                for idx, ev in enumerate(extracted):
                    ev_title = (ev.get("title") or "").strip()
                    if not ev_title:
                        continue
                    yes_c = int(ev.get("yes_count") or 0)
                    no_c = int(ev.get("no_count") or 0)
                    abs_c = int(ev.get("abstain_count") or 0)
                    miss_c = int(ev.get("absent_count") or 0)
                    ev_type = (ev.get("event_type") or "ordinance").strip().lower()
                    plain_sum = (ev.get("plain_summary") or "").strip()
                    diff_sum = (ev.get("diff_summary") or "").strip()
                    impact = compute_impact_score(ev_title, ev_type, yes_c, no_c, plain_sum)

                    ev_hash = hashlib.sha1(
                        f"{doc['jurisdiction_id']}|{doc['meeting_date']}|{ev_title}|{idx}".encode("utf-8")
                    ).hexdigest()[:14]
                    event_id = f"ev_{ev_hash}"

                    conn.execute(
                        """
                        INSERT OR IGNORE INTO events
                        (event_id, jurisdiction_id, doc_id, meeting_date, title, plain_summary, diff_summary,
                         qa_status, event_type, topic, outcome, yes_count, no_count, abstain_count,
                         absent_count, vote_margin, impact_score, source_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            doc["jurisdiction_id"],
                            doc["doc_id"],
                            doc["meeting_date"] or now_iso[:10],
                            ev_title,
                            plain_sum,
                            diff_sum,
                            ev_type,
                            (ev.get("topic") or "General").strip(),
                            (ev.get("outcome") or "Recorded").strip(),
                            yes_c,
                            no_c,
                            abs_c,
                            miss_c,
                            abs(yes_c - no_c),
                            impact,
                            doc["source_url"],
                        ),
                    )
                    stats["events_created"] += 1

                conn.execute(
                    "UPDATE documents SET status = 'processed', processed_at = ?, error_message = NULL WHERE doc_id = ?",
                    (now_iso, doc["doc_id"]),
                )
                stats["processed"] += 1
            except Exception as exc:
                retries = int(doc["retry_count"] or 0) + 1
                new_status = "failed" if retries >= max_retries else "pending"
                conn.execute(
                    "UPDATE documents SET status = ?, retry_count = ?, error_message = ? WHERE doc_id = ?",
                    (new_status, retries, str(exc)[:300], doc["doc_id"]),
                )
                stats["failed"] += 1

        conn.commit()
        return stats
    finally:
        conn.close()
