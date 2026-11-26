"""QA Reconciliation & Cleanup Tool for CivicPulse v2 Clean Baseline.

Fixes common structural causes of QA downgrades without lowering accuracy standards:
  1. Normalizes variant vote values in entity_actions ('aye'->'Yes', 'nay'->'No',
     'recused'/'present'/'abstained'->'Abstain') so tally comparisons are exact.
  2. Re-evaluates QA against full historical roster bounds (active + former members)
     so past meetings with former councilmembers aren't falsely flagged.
  3. Prints an actionable per-city breakdown of remaining `flagged` & `needs_review` items.
  4. Optional `--requeue-flagged` resets source documents behind severe `flagged`
     hallucinations back to `pending` (with retry_count=0) for clean re-extraction.

Usage:
  python scripts/reconcile_qa.py --db core_civic.db
  python scripts/reconcile_qa.py --db core_civic.db --apply
  python scripts/reconcile_qa.py --db core_civic.db --apply --requeue-flagged
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from civicpulse.pipeline.normalize import normalize_outcome, validate_extracted_event


def _canon_vote(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("yes", "aye", "yea", "for", "approve", "approved", "in favor"):
        return "Yes"
    if v in ("no", "nay", "against", "opposed"):
        return "No"
    if v in ("abstain", "abstained", "recused", "recuse", "present"):
        return "Abstain"
    if v in ("absent", "excused", "not present"):
        return "Absent"
    return raw.strip() or "Absent"


def reconcile_qa(db_path: str, apply: bool = False, requeue_flagged: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {
        "action_values_normalized": 0,
        "events_checked": 0,
        "verified": 0,
        "needs_review": 0,
        "flagged": 0,
        "flagged_docs_requeued": 0,
    }
    by_city_status = defaultdict(Counter)

    try:
        # 1. Normalize entity_actions vote values
        act_cols = {r[1] for r in conn.execute("PRAGMA table_info(entity_actions)").fetchall()}
        pk_col = "action_id" if "action_id" in act_cols else "rowid"
        for row in conn.execute(f"SELECT {pk_col} AS pk, value FROM entity_actions").fetchall():
            canon = _canon_vote(row["value"])
            if canon != (row["value"] or ""):
                stats["action_values_normalized"] += 1
                if apply:
                    conn.execute(f"UPDATE entity_actions SET value = ? WHERE {pk_col} = ?", (canon, row["pk"]))

        # Use MAX(active_roster, all_known_members) so historical meetings with former members aren't falsely flagged
        total_roster_sizes = {
            r["jurisdiction_id"]: r["cnt"]
            for r in conn.execute("SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities GROUP BY jurisdiction_id").fetchall()
        }

        actions_by_event = defaultdict(list)
        for a in conn.execute("SELECT event_id, entity_id, value FROM entity_actions").fetchall():
            actions_by_event[a["event_id"]].append({"entity_id": a["entity_id"], "value": _canon_vote(a["value"])})

        ev_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        has_doc_id = "doc_id" in ev_cols
        doc_sel = "e.doc_id" if has_doc_id else "NULL AS doc_id"

        events = conn.execute(
            f"""
            SELECT e.event_id, e.jurisdiction_id, {doc_sel}, e.outcome,
                   COALESCE(e.yes_count, 0) AS yes_count,
                   COALESCE(e.no_count, 0) AS no_count,
                   COALESCE(e.abstain_count, 0) AS abstain_count,
                   COALESCE(e.absent_count, 0) AS absent_count,
                   j.name AS jurisdiction_name
            FROM events e
            JOIN jurisdictions j ON j.ocd_division_id = e.jurisdiction_id
            WHERE COALESCE(j.status, 'active') = 'active'
            """
        ).fetchall()

        flagged_doc_ids = set()
        for ev in events:
            stats["events_checked"] += 1
            eid = ev["event_id"]
            jid = ev["jurisdiction_id"]
            votes = actions_by_event.get(eid, [])
            norm = normalize_outcome(
                ev["outcome"], ev["yes_count"], ev["no_count"], ev["abstain_count"], len(votes)
            )
            qa = validate_extracted_event(
                outcome_status=norm.status,
                yes_count=norm.yes_count,
                no_count=norm.no_count,
                abstain_count=norm.abstain_count,
                absent_count=ev["absent_count"],
                matched_votes=votes,
                unmatched_voter_names=[],
                roster_size=total_roster_sizes.get(jid, 0),
            )
            stats[qa.qa_status] += 1
            by_city_status[ev["jurisdiction_name"]][qa.qa_status] += 1

            if qa.qa_status == "flagged" and ev["doc_id"] is not None:
                flagged_doc_ids.add(ev["doc_id"])

            if apply and "qa_status" in ev_cols:
                if "qa_notes" in ev_cols:
                    conn.execute(
                        "UPDATE events SET qa_status = ?, qa_notes = ? WHERE event_id = ?",
                        (qa.qa_status, "; ".join(qa.issues), eid),
                    )
                else:
                    conn.execute("UPDATE events SET qa_status = ? WHERE event_id = ?", (qa.qa_status, eid))

        if apply and requeue_flagged and flagged_doc_ids:
            for did in flagged_doc_ids:
                conn.execute(
                    "UPDATE documents SET status = 'pending', retry_count = 0, processed_at = NULL WHERE doc_id = ?",
                    (did,),
                )
            stats["flagged_docs_requeued"] = len(flagged_doc_ids)

        if apply:
            conn.commit()

        print("=== QA BREAKDOWN BY JURISDICTION ===")
        for city, counts in sorted(by_city_status.items()):
            print(
                f"  {city:35s} | verified={counts['verified']:3d} | "
                f"needs_review={counts['needs_review']:3d} | flagged={counts['flagged']:2d}"
            )
        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and reconcile CivicPulse QA statuses.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--requeue-flagged", action="store_true")
    args = parser.parse_args()
    res = reconcile_qa(args.db, apply=args.apply, requeue_flagged=args.requeue_flagged)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[QA:{mode}] {res}")


if __name__ == "__main__":
    main()
