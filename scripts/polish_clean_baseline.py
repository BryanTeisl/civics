"""Final polish for CivicPulse v2 Clean Baseline:
  1. Fixes `data-level="municipality"` -> `data-level="city"` in public/index.html so the
     "Cities & Towns" filter pill matches canonical `"level": "city"` in directory.json.
  2. Updates scripts/baseline_audit.py to verify `data-level="city"`.
  3. Reconciles unanimous roll-call votes where individual Yes votes (3..roster_size-1) were
     extracted cleanly with 0 No votes, but the LLM reported full-council size (e.g., 9-0)
     instead of present-member count (7-0). Genuine overcounts remain `needs_review`/`flagged`.

Usage:
  python scripts/polish_clean_baseline.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from civicpulse.pipeline.normalize import normalize_outcome, validate_extracted_event


def fix_frontend_city_filter_pill() -> bool:
    idx_path = REPO_ROOT / "public" / "index.html"
    if not idx_path.exists():
        print("[WARN] public/index.html not found.")
        return False
    src = idx_path.read_text(encoding="utf-8")
    if 'data-level="municipality"' in src:
        src = src.replace('data-level="municipality"', 'data-level="city"')
        idx_path.write_text(src, encoding="utf-8")
        print('[PATCHED] Fixed public/index.html: data-level="municipality" -> data-level="city"')
        return True
    print('[OK] public/index.html already uses data-level="city"')
    return True


def update_baseline_audit_check() -> None:
    audit_path = REPO_ROOT / "scripts" / "baseline_audit.py"
    if not audit_path.exists():
        return
    src = audit_path.read_text(encoding="utf-8")
    old_block = """        has_muni_pill = 'data-level="municipality"' in idx_txt
        handles_city_alias = ('"city"' in app_txt or "'city'" in app_txt)
        ok_lvl_ui = (not has_muni_pill) or handles_city_alias
        print(
            f"[{_status(ok_lvl_ui, warn=True)}] Frontend City Filter Pill: "
            + ("js/app.js handles 'city' level" if ok_lvl_ui else "index.html uses data-level='municipality' — verify js/app.js maps 'city' -> municipality!")
        )"""
    new_block = """        has_city_pill = 'data-level="city"' in idx_txt and 'data-level="municipality"' not in idx_txt
        if not has_city_pill:
            failures += 1
        print(
            f"[{_status(has_city_pill)}] Frontend City Filter Pill: "
            + ("index.html uses canonical data-level='city'" if has_city_pill else "index.html still has stale data-level='municipality'")
        )"""
    if old_block in src:
        audit_path.write_text(src.replace(old_block, new_block, 1), encoding="utf-8")
        print("[PATCHED] Updated scripts/baseline_audit.py to enforce data-level='city'")


def reconcile_unanimous_with_absences(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {"tallies_aligned_to_present": 0, "verified": 0, "needs_review": 0, "flagged": 0}
    by_city = defaultdict(Counter)

    try:
        active_sizes = {
            r["jurisdiction_id"]: r["cnt"]
            for r in conn.execute(
                "SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities WHERE COALESCE(active, 1) = 1 GROUP BY jurisdiction_id"
            ).fetchall()
        }
        total_sizes = {
            r["jurisdiction_id"]: r["cnt"]
            for r in conn.execute(
                "SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities GROUP BY jurisdiction_id"
            ).fetchall()
        }

        actions_by_event = defaultdict(list)
        for a in conn.execute("SELECT event_id, entity_id, value FROM entity_actions").fetchall():
            actions_by_event[a["event_id"]].append({"entity_id": a["entity_id"], "value": a["value"]})

        ev_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        events = conn.execute(
            """
            SELECT e.event_id, e.jurisdiction_id, e.outcome,
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

        for ev in events:
            eid = ev["event_id"]
            jid = ev["jurisdiction_id"]
            votes = actions_by_event.get(eid, [])
            yes_c = ev["yes_count"]
            no_c = ev["no_count"]
            abs_c = ev["abstain_count"]
            tally_str = None

            rc_yes = sum(1 for v in votes if (v["value"] or "").lower() == "yes")
            rc_no = sum(1 for v in votes if (v["value"] or "").lower() == "no")
            rc_abs = sum(1 for v in votes if (v["value"] or "").lower() == "abstain")
            act_size = active_sizes.get(jid, 0)

            # Safe alignment: unanimous vote (no_c == 0, rc_no == 0, abs_c == 0) where LLM wrote full
            # council size (e.g., 9-0) even though 1-4 members were absent and rc_yes matched all present voters.
            if (
                no_c == 0
                and rc_no == 0
                and abs_c == 0
                and rc_abs == 0
                and 3 <= rc_yes < yes_c
                and yes_c == act_size
            ):
                yes_c = rc_yes
                tally_str = f"{yes_c}-0"
                stats["tallies_aligned_to_present"] += 1

            norm = normalize_outcome(ev["outcome"], yes_c, no_c, abs_c, len(votes))
            qa = validate_extracted_event(
                outcome_status=norm.status,
                yes_count=yes_c,
                no_count=no_c,
                abstain_count=abs_c,
                absent_count=ev["absent_count"],
                matched_votes=votes,
                unmatched_voter_names=[],
                roster_size=total_sizes.get(jid, 0),
            )
            stats[qa.qa_status] += 1
            by_city[ev["jurisdiction_name"]][qa.qa_status] += 1

            sets = ["yes_count = ?", "qa_status = ?"]
            vals = [yes_c, qa.qa_status]
            if tally_str and "tally" in ev_cols:
                sets.append("tally = ?")
                vals.append(tally_str)
            if "qa_notes" in ev_cols:
                sets.append("qa_notes = ?")
                vals.append("; ".join(qa.issues))
            vals.append(eid)
            conn.execute(f"UPDATE events SET {', '.join(sets)} WHERE event_id = ?", vals)

        conn.commit()
        print("\n=== UPDATED QA BREAKDOWN BY JURISDICTION ===")
        for city, cnts in sorted(by_city.items()):
            print(
                f"  {city:35s} | verified={cnts['verified']:3d} | "
                f"needs_review={cnts['needs_review']:3d} | flagged={cnts['flagged']:2d}"
            )
        print(f"\n[POLISH] {stats}")
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    fix_frontend_city_filter_pill()
    update_baseline_audit_check()
    db_f = REPO_ROOT / "core_civic.db"
    if db_f.exists():
        reconcile_unanimous_with_absences(db_f)
