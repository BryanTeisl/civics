"""Procedural Noise & Duplicate Event Cleaner (civicpulse/pipeline/dedupe_procedural.py).

Solves two real data-quality leaks across all jurisdictions:
  1. Same-day duplicate events extracted from overlapping agenda/minutes docs
     (e.g., 4 copies of "Motion to go into Executive Session for Annual Evaluations").
     Reassigns any entity_actions safely to the canonical highest-signal event before
     removing duplicates.
  2. Low-value procedural housekeeping items (call to order, adjournment, approval of
     minutes, executive session motions, roll call). Flags them (`is_procedural = 1`)
     and caps their impact_score at <= 15 so substantive ordinances/budgets lead.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROCEDURAL_PATTERNS = [
    r"\bexecutive\s+session\b",
    r"\bcall\s+to\s+order\b",
    r"\badjourn(ment|ed)?\b",
    r"\broll\s+call\b",
    r"\bpledge\s+of\s+allegiance\b",
    r"\bapproval\s+of\s+(the\s+)?(agenda|minutes)\b",
    r"\bapprove\s+(the\s+)?(agenda|minutes)\b",
    r"\bconsent\s+calendar\s+approval\b",
    r"\bproclamation\b",
    r"\bceremonial\b",
    r"\bexcuse\s+absen",
]
PROCEDURAL_RE = re.compile("|".join(PROCEDURAL_PATTERNS), re.IGNORECASE)


def ensure_procedural_column(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "is_procedural" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN is_procedural INTEGER DEFAULT 0")
    conn.commit()


def normalize_title_key(title: str) -> str:
    t = re.sub(r"[^a-z0-9\s]+", " ", (title or "").lower())
    t = re.sub(
        r"\b(consideration of a|consideration of|motion to|a motion to|to conduct the|for the|the|a|an|of)\b",
        " ",
        t,
    )
    return re.sub(r"\s+", " ", t).strip()


def is_procedural_title(title: str, event_type: str = "") -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if PROCEDURAL_RE.search(t):
        if re.search(r"\b(ordinance|zoning|budget|tax|mill\s+levy|annexation|bond|appropriation)\b", t, re.I):
            return False
        return True
    return False


def titles_are_duplicates(t1: str, t2: str) -> bool:
    k1 = normalize_title_key(t1)
    k2 = normalize_title_key(t2)
    if not k1 or not k2:
        return False
    if k1 == k2:
        return True
    if (k1 in k2 or k2 in k1) and min(len(k1), len(k2)) >= 18:
        return True
    return SequenceMatcher(None, k1, k2).ratio() >= 0.84


def run_dedupe_and_procedural_cleanup(
    db_path: Path = Path("core_civic.db"),
    apply: bool = False,
) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_procedural_column(conn)

    vote_counts = dict(
        conn.execute("SELECT event_id, COUNT(*) FROM entity_actions GROUP BY event_id").fetchall()
    )
    rows = conn.execute(
        """
        SELECT event_id, jurisdiction_id, meeting_date, title, event_type,
               COALESCE(impact_score, 0) AS impact_score,
               COALESCE(is_procedural, 0) AS is_procedural
        FROM events
        ORDER BY jurisdiction_id, meeting_date DESC, event_id ASC
        """
    ).fetchall()

    by_day: Dict[Tuple[str, str], List[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_day[(r["jurisdiction_id"], str(r["meeting_date"] or "")[:10])].append(r)

    duplicates_to_merge: List[Tuple[str, str]] = []
    for _, day_rows in by_day.items():
        clusters: List[List[sqlite3.Row]] = []
        for row in day_rows:
            placed = False
            for cl in clusters:
                if titles_are_duplicates(row["title"], cl[0]["title"]):
                    cl.append(row)
                    placed = True
                    break
            if not placed:
                clusters.append([row])

        for cl in clusters:
            if len(cl) <= 1:
                continue
            cl_sorted = sorted(
                cl,
                key=lambda r: (
                    vote_counts.get(r["event_id"], 0),
                    len(r["title"] or ""),
                    float(r["impact_score"] or 0),
                ),
                reverse=True,
            )
            canonical = cl_sorted[0]
            for dup in cl_sorted[1:]:
                duplicates_to_merge.append((dup["event_id"], canonical["event_id"]))

    removed_ids = {d for d, _ in duplicates_to_merge}
    procedural_updates: List[Tuple[str, float]] = []
    for r in rows:
        if r["event_id"] in removed_ids:
            continue
        if is_procedural_title(r["title"], r["event_type"] or ""):
            capped = min(float(r["impact_score"] or 0), 15.0)
            if int(r["is_procedural"] or 0) != 1 or float(r["impact_score"] or 0) > 15.0:
                procedural_updates.append((r["event_id"], capped))

    reassigned_votes = 0
    if apply:
        for dup_id, canon_id in duplicates_to_merge:
            dup_actions = conn.execute(
                "SELECT action_id, entity_id, action_type FROM entity_actions WHERE event_id = ?",
                (dup_id,),
            ).fetchall()
            for act in dup_actions:
                exists = conn.execute(
                    "SELECT 1 FROM entity_actions WHERE event_id = ? AND entity_id = ? AND action_type = ?",
                    (canon_id, act["entity_id"], act["action_type"]),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "UPDATE entity_actions SET event_id = ? WHERE action_id = ?",
                        (canon_id, act["action_id"]),
                    )
                    reassigned_votes += 1
                else:
                    conn.execute("DELETE FROM entity_actions WHERE action_id = ?", (act["action_id"],))
            conn.execute("DELETE FROM events WHERE event_id = ?", (dup_id,))

        for eid, capped in procedural_updates:
            conn.execute(
                "UPDATE events SET is_procedural = 1, impact_score = ? WHERE event_id = ?",
                (capped, eid),
            )
        conn.commit()

    conn.close()
    return {
        "mode": "APPLY" if apply else "DRY_RUN",
        "duplicates_merged": len(duplicates_to_merge),
        "votes_reassigned": reassigned_votes,
        "procedural_capped": len(procedural_updates),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate same-day events & cap procedural housekeeping noise")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--apply", action="store_true", help="Write changes to SQLite (default is dry-run)")
    args = parser.parse_args()
    res = run_dedupe_and_procedural_cleanup(Path(args.db), apply=args.apply)
    print("[DEDUPE-PROCEDURAL]", json.dumps(res))


if __name__ == "__main__":
    main()
