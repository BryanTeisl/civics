"""Idempotent SQLite normalization & cleanup script for CivicPulse v2.

Fixes:
  1. Unifies jurisdiction levels (municipal -> city, school_board -> school_district)
  2. Archives out-of-scope non-Colorado test jurisdictions (e.g., San Jose, CA) while
     keeping the schema multi-state ready via state codes
  3. Deduplicates duplicate Poudre School District entries
  4. Normalizes messy outcomes ("Adopted 7-0 (7-0)", "Approved by Consent")
  5. Reclassifies vague "General" topics into Resident + Commercial taxonomy
  6. Recalculates committee-aware versioned Impact Scores (Formula v2.0.0)
  7. Validates AI-extracted roll-call votes against active rosters before 'verified'
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Allow running directly as `python scripts/normalize_db.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from civicpulse.pipeline.normalize import (
    classify_topic,
    detect_body_type,
    normalize_level,
    normalize_outcome,
    validate_extracted_event,
)
from civicpulse.pipeline.scoring_spec import calculate_auditable_impact


def _add_col(conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")


def normalize_database(db_path: str, apply: bool = False, colorado_only: bool = True) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {
        "levels_fixed": 0,
        "out_of_scope_archived": 0,
        "poudre_deduped": 0,
        "outcomes_normalized": 0,
        "topics_improved": 0,
        "scores_recalculated": 0,
        "qa_downgraded": 0,
    }

    try:
        if apply:
            _add_col(conn, "events", "outcome_status", "TEXT DEFAULT ''")
            _add_col(conn, "events", "passage_method", "TEXT DEFAULT ''")
            _add_col(conn, "events", "tally", "TEXT DEFAULT ''")
            _add_col(conn, "events", "body_type", "TEXT DEFAULT 'full_body'")
            _add_col(conn, "events", "capture_method", "TEXT DEFAULT ''")
            _add_col(conn, "events", "formula_version", "TEXT DEFAULT ''")
            _add_col(conn, "events", "qa_notes", "TEXT DEFAULT ''")

        # 1. Normalize jurisdiction levels
        for row in conn.execute("SELECT ocd_division_id, level, status FROM jurisdictions").fetchall():
            canon = normalize_level(row["level"], row["ocd_division_id"])
            if canon != (row["level"] or ""):
                stats["levels_fixed"] += 1
                if apply:
                    conn.execute(
                        "UPDATE jurisdictions SET level = ? WHERE ocd_division_id = ?",
                        (canon, row["ocd_division_id"]),
                    )

            # 2. Scope to Colorado (archive out-of-state test rows like San Jose, CA without deleting history)
            if colorado_only and "state:co" not in row["ocd_division_id"].lower():
                if (row["status"] or "") != "archived":
                    stats["out_of_scope_archived"] += 1
                    if apply:
                        conn.execute(
                            "UPDATE jurisdictions SET status = 'archived' WHERE ocd_division_id = ?",
                            (row["ocd_division_id"],),
                        )

        # 3. Deduplicate legacy Poudre School District row if canonical row exists
        poudre_legacy = "ocd-division/country:us/state:co/sd:poudre"
        poudre_canon = "ocd-division/country:us/state:co/school_district:poudre_r1"
        has_legacy = conn.execute(
            "SELECT 1 FROM jurisdictions WHERE ocd_division_id = ?", (poudre_legacy,)
        ).fetchone()
        has_canon = conn.execute(
            "SELECT 1 FROM jurisdictions WHERE ocd_division_id = ?", (poudre_canon,)
        ).fetchone()
        if has_legacy and has_canon:
            stats["poudre_deduped"] += 1
            if apply:
                conn.execute("UPDATE documents SET jurisdiction_id = ? WHERE jurisdiction_id = ?", (poudre_canon, poudre_legacy))
                conn.execute("UPDATE events SET jurisdiction_id = ? WHERE jurisdiction_id = ?", (poudre_canon, poudre_legacy))
                conn.execute("UPDATE entities SET jurisdiction_id = ? WHERE jurisdiction_id = ?", (poudre_canon, poudre_legacy))
                conn.execute("DELETE FROM jurisdictions WHERE ocd_division_id = ?", (poudre_legacy,))

        # Preload active rosters & actions
        roster_sizes = {
            r["jurisdiction_id"]: r["cnt"]
            for r in conn.execute(
                "SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities WHERE COALESCE(active, 1) = 1 GROUP BY jurisdiction_id"
            ).fetchall()
        }
        actions_by_event: dict = {}
        for a in conn.execute("SELECT event_id, entity_id, value FROM entity_actions").fetchall():
            actions_by_event.setdefault(a["event_id"], []).append(dict(a))

        # 4-7. Normalize events, topics, committee scores, and QA status
        ev_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        doc_join = "LEFT JOIN documents d ON d.doc_id = e.doc_id" if "doc_id" in ev_cols else ""
        doc_title_expr = "d.title AS doc_title" if "doc_id" in ev_cols else "'' AS doc_title"

        events = conn.execute(
            f"""
            SELECT e.event_id, e.jurisdiction_id, e.title, e.event_type, e.topic, e.outcome,
                   e.yes_count, e.no_count, COALESCE(e.abstain_count, 0) AS abstain_count,
                   COALESCE(e.absent_count, 0) AS absent_count,
                   COALESCE(e.plain_summary, '') AS plain_summary,
                   COALESCE(e.impact_score, 0) AS impact_score,
                   COALESCE(e.qa_status, 'verified') AS qa_status,
                   {doc_title_expr},
                   COALESCE(j.adapter_type, '') AS adapter_type
            FROM events e
            JOIN jurisdictions j ON j.ocd_division_id = e.jurisdiction_id
            {doc_join}
            """
        ).fetchall()

        for ev in events:
            eid = ev["event_id"]
            jid = ev["jurisdiction_id"]
            votes = actions_by_event.get(eid, [])
            norm_out = normalize_outcome(
                ev["outcome"],
                ev["yes_count"] or 0,
                ev["no_count"] or 0,
                ev["abstain_count"] or 0,
                individual_vote_count=len(votes),
            )
            if norm_out.status != (ev["outcome"] or ""):
                stats["outcomes_normalized"] += 1

            new_topic = classify_topic(ev["title"], ev["plain_summary"], ev["topic"])
            if new_topic != (ev["topic"] or ""):
                stats["topics_improved"] += 1

            roster_n = roster_sizes.get(jid, 0)
            body_type = detect_body_type(ev["title"], ev["doc_title"], norm_out.yes_count + norm_out.no_count, roster_n)
            expected_size = (
                max(norm_out.yes_count + norm_out.no_count + norm_out.abstain_count, 1)
                if body_type == "committee"
                else roster_n
            )
            impact = calculate_auditable_impact(
                event_type=ev["event_type"] or "motion",
                yes_count=norm_out.yes_count,
                no_count=norm_out.no_count,
                abstain_count=norm_out.abstain_count,
                expected_body_size=expected_size,
                body_type=body_type,
                title=ev["title"] or "",
                summary=ev["plain_summary"] or "",
            )
            if round(float(ev["impact_score"] or 0), 1) != impact.score:
                stats["scores_recalculated"] += 1

            capture = (
                "structured_api"
                if (ev["adapter_type"] or "").lower() == "legistar" and len(votes) > 0
                else "ai_minutes_pdf"
            )
            qa_res = validate_extracted_event(
                outcome_status=norm_out.status,
                yes_count=norm_out.yes_count,
                no_count=norm_out.no_count,
                abstain_count=norm_out.abstain_count,
                absent_count=ev["absent_count"] or 0,
                matched_votes=votes,
                unmatched_voter_names=[],
                roster_size=roster_n,
                capture_method=capture,
                body_type=body_type,
            )
            if qa_res.qa_status != "verified":
                stats["qa_downgraded"] += 1

            if apply:
                conn.execute(
                    """
                    UPDATE events
                    SET outcome = ?,
                        outcome_status = ?,
                        passage_method = ?,
                        tally = ?,
                        yes_count = ?,
                        no_count = ?,
                        abstain_count = ?,
                        topic = ?,
                        body_type = ?,
                        capture_method = ?,
                        impact_score = ?,
                        formula_version = ?,
                        qa_status = ?,
                        qa_notes = ?
                    WHERE event_id = ?
                    """,
                    (
                        norm_out.status,
                        norm_out.status,
                        norm_out.passage_method,
                        norm_out.tally,
                        norm_out.yes_count,
                        norm_out.no_count,
                        norm_out.abstain_count,
                        new_topic,
                        body_type,
                        capture,
                        impact.score,
                        impact.formula_version,
                        qa_res.qa_status,
                        "; ".join(qa_res.issues),
                        eid,
                    ),
                )

        if apply:
            conn.commit()
        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize CivicPulse SQLite data quality.")
    parser.add_argument("--db", default="core_civic.db", help="Path to SQLite database")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--keep-non-colorado", action="store_true", help="Do not archive non-CO rows")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    res = normalize_database(args.db, apply=args.apply, colorado_only=not args.keep_non_colorado)
    print(f"[NORMALIZE:{mode}] {res}")


if __name__ == "__main__":
    main()
