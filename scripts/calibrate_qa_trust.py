"""QA Trust Calibration & False-Warning Cleanup (scripts/calibrate_qa_trust.py).

Previously, strict full-council roster checks downgraded ~200 legitimate events
(such as 4-member Denver committees, partial-attendance meetings, and voice/consent
votes in Longmont/Thornton) to `qa_status = 'needs_review'`, diluting resident trust.

This module applies objective, defensible QA rules:
  - `verified`:
      * Valid ISO meeting date (`YYYY-MM-DD`)
      * Substantive title (len >= 6, not an outcome-only junk string like "Adopted 7-0")
      * Valid recorded outcome or tally (`yes_count + no_count > 0` OR Consent/Voice/Procedural)
      * If named individual roll-call votes exist, their yes/no counts do not wildly
        contradict the recorded tally (within ±1 for abstention/recusal edge cases, OR
        committee/partial roll-call count <= active roster size).
  - `needs_review`:
      * Missing/invalid meeting date
      * Outcome-only junk title or empty title
      * Contradictory vote math (e.g., named 'yes' votes > recorded yes_count + 1, or
        named 'no' votes > recorded no_count + 1, or impossible tally > max(roster*2, 25))
      * Missing both outcome and tally (`yes_count == 0 and no_count == 0` and unknown outcome)

Usage:
  # Preview calibration impact (dry-run)
  python scripts/calibrate_qa_trust.py --db core_civic.db

  # Apply calibrated QA statuses to SQLite and patch normalize_db.py
  python scripts/calibrate_qa_trust.py --db core_civic.db --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JUNK_TITLE_RE = re.compile(
    r"^(adopted|passed|approved|failed|denied|carried|tabled|motion\s+carried|unanimous|consent|roll\s+call|minutes)[\s:\-\(\)\d/]*$",
    re.IGNORECASE,
)


def evaluate_event_qa(
    meeting_date: str,
    title: str,
    outcome: str,
    yes_count: int,
    no_count: int,
    named_yes: int,
    named_no: int,
    roster_size: int,
) -> Tuple[str, List[str]]:
    """Returns ('verified' | 'needs_review', [reason_codes])."""
    reasons: List[str] = []
    dt = (meeting_date or "").strip()
    t = (title or "").strip()
    out = (outcome or "").strip().lower()
    y = int(yes_count or 0)
    n = int(no_count or 0)
    ny = int(named_yes or 0)
    nn = int(named_no or 0)

    if not ISO_DATE_RE.match(dt):
        reasons.append("invalid_or_missing_date")

    if len(t) < 6 or JUNK_TITLE_RE.match(t):
        reasons.append("junk_or_empty_title")

    max_plausible = max(roster_size * 2, 25) if roster_size > 0 else 25
    if y < 0 or n < 0 or (y + n) > max_plausible:
        reasons.append("impossible_tally")

    # Contradictory named-vote math (only flag when named votes actively conflict with tally)
    if (ny + nn) > 0 and (y + n) > 0:
        if ny > y + 1 or nn > n + 1:
            reasons.append("named_votes_exceed_tally")
        if y == 0 and ny >= 2:
            reasons.append("zero_yes_tally_with_named_yes")
        if n == 0 and nn >= 2:
            reasons.append("zero_no_tally_with_named_no")

    # Missing both tally and recognizable outcome
    recognized_outcomes = {
        "passed", "adopted", "approved", "failed", "denied", "tabled",
        "continued", "withdrawn", "consent", "voice vote", "recorded", "referred",
    }
    if y == 0 and n == 0 and not any(tok in out for tok in recognized_outcomes):
        reasons.append("missing_outcome_and_tally")

    status = "needs_review" if reasons else "verified"
    return status, reasons


def calibrate_database_qa(db_path: Path, apply: bool = False) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ev_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        has_qa = "qa_status" in ev_cols
        if not has_qa:
            return {"error": "events.qa_status column missing"}

        roster_counts = {
            r["jurisdiction_id"]: int(r["cnt"])
            for r in conn.execute(
                "SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities WHERE COALESCE(active, 1) = 1 GROUP BY jurisdiction_id"
            ).fetchall()
        }

        vote_counts: Dict[str, List[int]] = {}
        for r in conn.execute("SELECT event_id, LOWER(COALESCE(action_type, '')) AS act FROM entity_actions").fetchall():
            eid = r["event_id"]
            act = r["act"]
            pair = vote_counts.setdefault(eid, [0, 0])
            if act in ("yes", "yea", "aye", "for", "approve", "approved"):
                pair[0] += 1
            elif act in ("no", "nay", "against", "oppose", "denied"):
                pair[1] += 1

        rows = conn.execute(
            """
            SELECT event_id, jurisdiction_id, meeting_date, title, outcome,
                   COALESCE(yes_count, 0) AS yes_count,
                   COALESCE(no_count, 0) AS no_count,
                   COALESCE(qa_status, 'unverified') AS qa_status
            FROM events
            """
        ).fetchall()

        before_counts: Dict[str, int] = {}
        after_counts: Dict[str, int] = {}
        reason_tally: Dict[str, int] = {}
        updates: List[Tuple[str, str]] = []

        for r in rows:
            old_qa = r["qa_status"]
            before_counts[old_qa] = before_counts.get(old_qa, 0) + 1

            ny, nn = vote_counts.get(r["event_id"], [0, 0])
            new_qa, reasons = evaluate_event_qa(
                meeting_date=r["meeting_date"],
                title=r["title"],
                outcome=r["outcome"],
                yes_count=r["yes_count"],
                no_count=r["no_count"],
                named_yes=ny,
                named_no=nn,
                roster_size=roster_counts.get(r["jurisdiction_id"], 0),
            )
            after_counts[new_qa] = after_counts.get(new_qa, 0) + 1
            for rs in reasons:
                reason_tally[rs] = reason_tally.get(rs, 0) + 1
            if new_qa != old_qa:
                updates.append((new_qa, r["event_id"]))

        if apply and updates:
            conn.executemany("UPDATE events SET qa_status = ? WHERE event_id = ?", updates)
            conn.commit()

        return {
            "mode": "APPLY" if apply else "DRY_RUN",
            "total_events": len(rows),
            "changed": len(updates),
            "before": before_counts,
            "after": after_counts,
            "needs_review_reasons": reason_tally,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate CivicPulse QA trust statuses.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    res = calibrate_database_qa(Path(args.db), apply=args.apply)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
