import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from db import DB_PATH, get_connection, init_db

try:
    from ai_agent_3_engage import run_agent_3_engagement_guides
except ImportError:
    run_agent_3_engagement_guides = None

try:
    from ai_agent_4_lifecycle import run_agent_4_lifecycle_tracker
except ImportError:
    run_agent_4_lifecycle_tracker = None

PUBLIC_DATA_DIR = Path("public/data")


def _slugify_division(div_id: str) -> str:
    return (
        div_id.replace("ocd-division/", "")
        .replace("/", "__")
        .replace(":", "_")
        .replace("-", "_")
    )


def build_static_json_and_index(db_path: str = DB_PATH, out_dir: Path = PUBLIC_DATA_DIR) -> Dict[str, Any]:
    init_db(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = get_connection(db_path)
    try:
        jurs = conn.execute(
            "SELECT * FROM jurisdictions ORDER BY CASE WHEN LOWER(COALESCE(status, 'active')) = 'active' THEN 0 ELSE 1 END, name ASC"
        ).fetchall()

        jurisdiction_entries: List[Dict[str, Any]] = []
        search_index: List[Dict[str, Any]] = []

        for j in jurs:
            div_id = j["ocd_division_id"]
            status = (j["status"] or "active").lower()
            file_name = f"{_slugify_division(div_id)}.json"

            entities_rows = conn.execute(
                "SELECT * FROM entities WHERE jurisdiction_id = ? AND active = 1 ORDER BY district ASC, name ASC",
                (div_id,),
            ).fetchall()

            events_rows = conn.execute(
                "SELECT * FROM events WHERE jurisdiction_id = ? ORDER BY meeting_date DESC, event_id DESC",
                (div_id,),
            ).fetchall()

            doc_stats = conn.execute(
                "SELECT COUNT(*), MIN(meeting_date) FROM documents WHERE jurisdiction_id = ?",
                (div_id,),
            ).fetchone()
            doc_count = doc_stats[0] or 0
            docs_since = doc_stats[1] or (events_rows[-1]["meeting_date"] if events_rows else today_str)

            roster_size = len(entities_rows)
            actions_by_event: Dict[str, List[sqlite3.Row]] = {}
            actions_by_entity: Dict[str, List[sqlite3.Row]] = {}

            for ev in events_rows:
                ev_id = ev["event_id"]
                ev_actions = conn.execute(
                    "SELECT * FROM entity_actions WHERE event_id = ?", (ev_id,)
                ).fetchall()
                actions_by_event[ev_id] = ev_actions
                for act in ev_actions:
                    actions_by_entity.setdefault(act["entity_id"], []).append(act)

            # Build per-entity metrics and vote/sponsored lists
            entities_out: List[Dict[str, Any]] = []
            event_lookup = {ev["event_id"]: ev for ev in events_rows}

            for ent in entities_rows:
                pid = ent["ocd_person_id"]
                ent_acts = actions_by_entity.get(pid, [])
                votes_list = []
                sponsored_list = []
                present_votes = 0
                total_votes = 0
                pivotal_votes = 0
                impact_scores = []

                for act in ent_acts:
                    ev = event_lookup.get(act["event_id"])
                    if not ev:
                        continue
                    atype = (act["action_type"] or "").lower()
                    if atype == "vote":
                        total_votes += 1
                        val = (act["value"] or "").strip()
                        if val.lower() not in ("absent", ""):
                            present_votes += 1
                        if act["is_pivotal"]:
                            pivotal_votes += 1
                        imp = float(ev["impact_score"] or 0.0)
                        impact_scores.append(imp)
                        votes_list.append({
                            "event_id": ev["event_id"],
                            "meeting_date": ev["meeting_date"],
                            "title": ev["title"],
                            "plain_summary": ev["plain_summary"] if "plain_summary" in ev.keys() else "",
                            "event_type": ev["event_type"],
                            "vote": val or "Absent",
                            "is_pivotal": bool(act["is_pivotal"]),
                            "impact_score": imp,
                            "rationale_summary": act["rationale_summary"] or "",
                            "verbatim_quote": act["verbatim_quote"] or "",
                        })
                    else:
                        sponsored_list.append({
                            "event_id": ev["event_id"],
                            "meeting_date": ev["meeting_date"],
                            "title": ev["title"],
                            "action_type": act["action_type"],
                        })

                att_rate = round((present_votes / total_votes) * 100) if total_votes > 0 else 0
                avg_imp = round(sum(impact_scores) / len(impact_scores), 1) if impact_scores else 0.0
                piv_rate = round((pivotal_votes / total_votes) * 100) if total_votes > 0 else 0

                try:
                    social_links = json.loads(ent["social_links_json"] or "{}")
                except Exception:
                    social_links = {}
                try:
                    bio_extra = json.loads(ent["bio_extra_json"] or "{}")
                except Exception:
                    bio_extra = {}

                entities_out.append({
                    "ocd_person_id": pid,
                    "jurisdiction_id": div_id,
                    "name": ent["name"],
                    "entity_type": ent["entity_type"] or "legislator",
                    "role": ent["role"] or "Representative",
                    "district": ent["district"] or "At-Large",
                    "elected_date": ent["elected_date"] or "Active Term",
                    "website_url": ent["website_url"] or "",
                    "portal_url": ent["portal_url"] or j["portal_url"] or "",
                    "party": ent["party"] or "Nonpartisan",
                    "phone": ent["phone"] or "",
                    "email": ent["email"] or "",
                    "social_links": social_links,
                    "bio_extra": bio_extra,
                    "metrics": {
                        "attendance_rate": att_rate,
                        "present_votes": present_votes,
                        "total_votes": total_votes,
                        "avg_impact_score": avg_imp,
                        "pivotal_votes": pivotal_votes,
                        "pivotal_rate": piv_rate,
                        "sponsored_count": len(sponsored_list),
                    },
                    "sponsored_items": sponsored_list,
                    "votes": votes_list,
                })

            entity_map = {e["ocd_person_id"]: e for e in entities_out}
            events_out: List[Dict[str, Any]] = []

            for ev in events_rows:
                ev_id = ev["event_id"]
                ev_acts = actions_by_event.get(ev_id, [])
                votes_detail = []
                sponsors_detail = []
                quotes_texts = []
                voters_texts = []

                for act in ev_acts:
                    ent_obj = entity_map.get(act["entity_id"])
                    ent_name = ent_obj["name"] if ent_obj else act["entity_id"]
                    voters_texts.append(ent_name)
                    if act["verbatim_quote"]:
                        quotes_texts.append(act["verbatim_quote"])

                    if (act["action_type"] or "").lower() == "vote":
                        votes_detail.append({
                            "entity_id": act["entity_id"],
                            "name": ent_name,
                            "district": ent_obj["district"] if ent_obj else "",
                            "elected_date": ent_obj["elected_date"] if ent_obj else "Active Term",
                            "vote": act["value"] or "Absent",
                            "is_pivotal": bool(act["is_pivotal"]),
                            "rationale_summary": act["rationale_summary"] or "",
                            "verbatim_quote": act["verbatim_quote"] or "",
                        })
                    else:
                        sponsors_detail.append({
                            "entity_id": act["entity_id"],
                            "name": ent_name,
                            "action_type": act["action_type"],
                        })

                yes_c = ev["yes_count"] or 0
                no_c = ev["no_count"] or 0
                abs_c = ev["abstain_count"] or 0
                miss_c = ev["absent_count"] or 0
                att_count = yes_c + no_c + abs_c
                att_rate = round((att_count / roster_size) * 100) if roster_size > 0 else None

                plain_sum = ev["plain_summary"] if "plain_summary" in ev.keys() else ""
                diff_sum = ev["diff_summary"] if "diff_summary" in ev.keys() else ""
                qa_stat = ev["qa_status"] if "qa_status" in ev.keys() else "verified"

                ev_dict = {
                    "event_id": ev_id,
                    "jurisdiction_id": div_id,
                    "meeting_date": ev["meeting_date"],
                    "title": ev["title"],
                    "plain_summary": plain_sum or "",
                    "diff_summary": diff_sum or "",
                    "qa_status": qa_stat or "verified",
                    "event_type": ev["event_type"] or "ordinance",
                    "topic": ev["topic"] or "General",
                    "outcome": ev["outcome"] or "Recorded",
                    "yes_count": yes_c,
                    "no_count": no_c,
                    "abstain_count": abs_c,
                    "absent_count": miss_c,
                    "vote_margin": ev["vote_margin"] or 0,
                    "impact_score": ev["impact_score"] or 0.0,
                    "source_url": ev["source_url"] or j["portal_url"] or "",
                    "roster_size": roster_size,
                    "attendance_count": att_count,
                    "attendance_rate": att_rate,
                    "sponsors": sponsors_detail,
                    "votes": votes_detail,
                }
                events_out.append(ev_dict)

                if status == "active":
                    search_index.append({
                        "event_id": ev_id,
                        "jurisdiction_id": div_id,
                        "jurisdiction_name": j["name"],
                        "meeting_date": ev["meeting_date"],
                        "title": ev["title"],
                        "plain_summary": plain_sum or "",
                        "topic": ev["topic"] or "General",
                        "outcome": ev["outcome"] or "Recorded",
                        "yes_count": yes_c,
                        "no_count": no_c,
                        "impact_score": ev["impact_score"] or 0.0,
                        "quotes_text": " ".join(quotes_texts),
                        "voters_text": " ".join(voters_texts),
                    })

            jur_payload = {
                "jurisdiction": {
                    "ocd_division_id": div_id,
                    "name": j["name"],
                    "level": j["level"],
                    "lat": j["lat"],
                    "lng": j["lng"],
                    "portal_url": j["portal_url"] or "",
                    "parent_division_id": j["parent_division_id"],
                    "status": status,
                    "docs_since": docs_since,
                    "last_updated": now_str,
                },
                "entities": entities_out,
                "events": events_out,
            }
            (out_dir / file_name).write_text(json.dumps(jur_payload, indent=2), encoding="utf-8")

            jurisdiction_entries.append({
                "ocd_division_id": div_id,
                "name": j["name"],
                "level": j["level"],
                "lat": j["lat"],
                "lng": j["lng"],
                "portal_url": j["portal_url"] or "",
                "parent_division_id": j["parent_division_id"],
                "status": status,
                "file": file_name,
                "entity_count": len(entities_out),
                "event_count": len(events_out),
                "document_count": doc_count,
                "docs_since": docs_since,
                "last_updated": now_str,
            })

        index_payload = {
            "last_updated": now_str,
            "jurisdictions": jurisdiction_entries,
            "search_index": search_index,
        }
        (out_dir / "index.json").write_text(json.dumps(index_payload, indent=2), encoding="utf-8")
        print(f"[EXPORT] Updated {out_dir / 'index.json'} ({len(jurisdiction_entries)} jurisdictions, {len(search_index)} search events).")
        return index_payload
    finally:
        conn.close()


def refresh_all_json_and_index() -> None:
    build_static_json_and_index()
    if run_agent_3_engagement_guides:
        run_agent_3_engagement_guides()
    if run_agent_4_lifecycle_tracker:
        run_agent_4_lifecycle_tracker()


if __name__ == "__main__":
    refresh_all_json_and_index()