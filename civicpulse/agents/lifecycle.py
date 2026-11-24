from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from civicpulse.config import SETTINGS
from civicpulse.db import get_connection, init_db

MEASURE_ID_RE = re.compile(
    r"\b(ordinance|resolution|bill|measure)\s*(?:no\.?|number|#)?\s*([0-9]{1,4}(?:-[0-9]{1,4})?)\b",
    re.IGNORECASE,
)


def _normalize_topic_key(title: str) -> str:
    cleaned = re.sub(r"\b(first|second|final|reading|of|consideration|motion|to|a|the|and|for|in)\b", "", title.lower())
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned).strip()
    tokens = [t for t in cleaned.split() if len(t) > 3]
    return " ".join(tokens[:5])


def build_bill_lifecycles(
    db_path: Optional[str] = None, out_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """Links multi-meeting ordinances, resolutions, and follow-up votes into chronological chains."""
    init_db(db_path)
    target_dir = out_dir or SETTINGS.public_data_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path)
    by_jurisdiction: Dict[str, List[Dict[str, Any]]] = {}
    try:
        rows = conn.execute(
            """
            SELECT event_id, jurisdiction_id, meeting_date, title, outcome, yes_count, no_count
            FROM events
            ORDER BY meeting_date ASC, event_id ASC
            """
        ).fetchall()

        grouped_by_jur: Dict[str, List[Any]] = defaultdict(list)
        for r in rows:
            grouped_by_jur[r["jurisdiction_id"]].append(r)

        for div_id, evs in grouped_by_jur.items():
            buckets: Dict[str, List[Any]] = defaultdict(list)
            basis_map: Dict[str, str] = {}

            for ev in evs:
                title = ev["title"] or ""
                m = MEASURE_ID_RE.search(title)
                if m:
                    key = f"id:{m.group(1).lower()}_{m.group(2)}"
                    basis_map[key] = f"Measure ID #{m.group(2)}"
                else:
                    tkey = _normalize_topic_key(title)
                    if not tkey:
                        continue
                    key = f"topic:{tkey}"
                    basis_map[key] = "Related Agenda Topic Match"
                buckets[key].append(ev)

            chains: List[Dict[str, Any]] = []
            for key, items in buckets.items():
                if len(items) < 2:
                    continue
                stages = [
                    {
                        "event_id": it["event_id"],
                        "meeting_date": it["meeting_date"],
                        "title": it["title"],
                        "outcome": it["outcome"] or "Recorded",
                        "tally": f"{it['yes_count'] or 0}-{it['no_count'] or 0}",
                    }
                    for it in items
                ]
                chains.append(
                    {
                        "chain_key": key,
                        "match_basis": basis_map[key],
                        "first_date": stages[0]["meeting_date"],
                        "latest_date": stages[-1]["meeting_date"],
                        "stage_count": len(stages),
                        "stages": stages,
                    }
                )

            if chains:
                chains.sort(key=lambda c: c["latest_date"], reverse=True)
                by_jurisdiction[div_id] = chains

        payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "by_jurisdiction": by_jurisdiction,
        }
        (target_dir / "bill_lifecycles.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    finally:
        conn.close()
