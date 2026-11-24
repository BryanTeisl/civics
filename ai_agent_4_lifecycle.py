import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import DB_PATH, get_connection, init_db

OUTPUT_LIFECYCLES_PATH = Path("public/data/bill_lifecycles.json")

MEASURE_CODE_RE = re.compile(
    r"\b(?:ordinance|ord\.?|resolution|res\.?|bill|matter|no\.?)\s*#?\s*([0-9]{2,4}[-–][0-9A-Za-z]+|[0-9]+-[0-9]{2,4}|[0-9]{2,5})\b",
    re.IGNORECASE,
)


def extract_measure_code(title: str) -> Optional[str]:
    if not title:
        return None
    m = MEASURE_CODE_RE.search(title)
    if not m:
        return None
    raw = re.sub(r"\s+", "", m.group(1)).upper()
    return raw if len(raw) >= 2 else None


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", (title or "").lower())
    stop = {"ordinance", "resolution", "approving", "amending", "relating", "concerning", "city", "council", "meeting", "item"}
    return {w for w in words if w not in stop}


def build_lifecycles_for_jurisdiction(conn: sqlite3.Connection, jurisdiction_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, meeting_date, title, event_type, outcome, yes_count, no_count, impact_score, source_url
        FROM events
        WHERE jurisdiction_id = ?
        ORDER BY meeting_date ASC, event_id ASC
        """,
        (jurisdiction_id,),
    ).fetchall()

    by_code: Dict[str, List[sqlite3.Row]] = {}
    unmatched: List[sqlite3.Row] = []

    for r in rows:
        code = extract_measure_code(r["title"] or "")
        if code:
            by_code.setdefault(code, []).append(r)
        else:
            unmatched.append(r)

    chains: List[Dict[str, Any]] = []

    # 1. Explicit measure code lifecycles
    for code, ev_list in by_code.items():
        if len(ev_list) < 2:
            continue
        stages = [
            {
                "event_id": ev["event_id"],
                "meeting_date": ev["meeting_date"],
                "title": ev["title"],
                "event_type": ev["event_type"],
                "outcome": ev["outcome"] or "Recorded",
                "tally": f"{ev['yes_count'] or 0}-{ev['no_count'] or 0}",
                "impact_score": ev["impact_score"] or 0,
                "source_url": ev["source_url"] or "",
            }
            for ev in ev_list
        ]
        chains.append({
            "lifecycle_id": f"{jurisdiction_id}::code::{code}",
            "match_basis": f"Measure ID #{code}",
            "jurisdiction_id": jurisdiction_id,
            "stage_count": len(stages),
            "first_date": stages[0]["meeting_date"],
            "latest_date": stages[-1]["meeting_date"],
            "latest_outcome": stages[-1]["outcome"],
            "stages": stages,
        })

    # 2. Title-overlap fallback for multi-stage items without explicit numbers
    used_ids = {s["event_id"] for c in chains for s in c["stages"]}
    pool = [r for r in (list(unmatched) + [r for evs in by_code.values() if len(evs) == 1 for r in evs]) if r["event_id"] not in used_ids]

    for idx, base_ev in enumerate(pool):
        if base_ev["event_id"] in used_ids:
            continue
        base_toks = _title_tokens(base_ev["title"] or "")
        if len(base_toks) < 3:
            continue
        group = [base_ev]
        for other in pool[idx + 1:]:
            if other["event_id"] in used_ids:
                continue
            other_toks = _title_tokens(other["title"] or "")
            if not other_toks:
                continue
            overlap = len(base_toks & other_toks) / max(1, min(len(base_toks), len(other_toks)))
            if overlap >= 0.7:
                group.append(other)

        if len(group) >= 2:
            for g in group:
                used_ids.add(g["event_id"])
            stages = [
                {
                    "event_id": ev["event_id"],
                    "meeting_date": ev["meeting_date"],
                    "title": ev["title"],
                    "event_type": ev["event_type"],
                    "outcome": ev["outcome"] or "Recorded",
                    "tally": f"{ev['yes_count'] or 0}-{ev['no_count'] or 0}",
                    "impact_score": ev["impact_score"] or 0,
                    "source_url": ev["source_url"] or "",
                }
                for ev in group
            ]
            chains.append({
                "lifecycle_id": f"{jurisdiction_id}::topic::{group[0]['event_id']}",
                "match_basis": "Related Agenda Topic Match",
                "jurisdiction_id": jurisdiction_id,
                "stage_count": len(stages),
                "first_date": stages[0]["meeting_date"],
                "latest_date": stages[-1]["meeting_date"],
                "latest_outcome": stages[-1]["outcome"],
                "stages": stages,
            })

    return chains


def run_agent_4_lifecycle_tracker(db_path: str = DB_PATH, output_path: Path = OUTPUT_LIFECYCLES_PATH) -> Dict[str, Any]:
    init_db(db_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        jurs = conn.execute("SELECT ocd_division_id FROM jurisdictions").fetchall()
        lifecycles_by_jur: Dict[str, List[Dict[str, Any]]] = {}
        total_chains = 0

        for j in jurs:
            div_id = j["ocd_division_id"]
            chains = build_lifecycles_for_jurisdiction(conn, div_id)
            lifecycles_by_jur[div_id] = chains
            total_chains += len(chains)

        payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_lifecycles": total_chains,
            "by_jurisdiction": lifecycles_by_jur,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[Agent 4 - Bill-Lifecycle Tracker] Exported {total_chains} multi-stage lifecycle(s) to {output_path}")
        return payload
    finally:
        conn.close()


if __name__ == "__main__":
    run_agent_4_lifecycle_tracker()
