import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from db import get_connection, init_db, seed_public_profiles

OUTPUT_DIR = Path(os.environ.get("CIVIC_EXPORT_DIR", "public/data"))


def slugify_division_id(division_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", division_id).strip("-").lower()
    return f"{slug}.json"


def safe_json_loads(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def export_all() -> None:
    init_db()
    seed_public_profiles()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        jurisdictions = conn.execute(
            "SELECT * FROM jurisdictions ORDER BY status ASC, level ASC, name ASC"
        ).fetchall()

        index_jurisdictions: List[Dict[str, Any]] = []
        global_search_index: List[Dict[str, Any]] = []

        for j in jurisdictions:
            div_id = j["ocd_division_id"]
            status = j["status"] or "active"
            file_name = slugify_division_id(div_id)

            if status == "unclaimed":
                index_jurisdictions.append(
                    {
                        "ocd_division_id": div_id,
                        "name": j["name"],
                        "level": j["level"],
                        "status": "unclaimed",
                        "lat": j["lat"],
                        "lng": j["lng"],
                        "portal_url": j["portal_url"],
                        "parent_division_id": j["parent_division_id"],
                        "file": None,
                        "entity_count": 0,
                        "event_count": 0,
                        "docs_since": None,
                        "last_updated": now_iso,
                    }
                )
                continue

            entities = conn.execute(
                """
                SELECT * FROM entities
                WHERE jurisdiction_id = ? AND active = 1
                ORDER BY district ASC, name ASC
                """,
                (div_id,),
            ).fetchall()

            events = conn.execute(
                """
                SELECT * FROM events
                WHERE jurisdiction_id = ?
                ORDER BY meeting_date DESC, event_id DESC
                """,
                (div_id,),
            ).fetchall()

            earliest_row = conn.execute(
                """
                SELECT MIN(dt) AS min_dt FROM (
                    SELECT MIN(meeting_date) AS dt FROM events
                    WHERE jurisdiction_id = ? AND meeting_date IS NOT NULL AND meeting_date != ''
                    UNION ALL
                    SELECT MIN(meeting_date) AS dt FROM documents
                    WHERE jurisdiction_id = ? AND meeting_date IS NOT NULL AND meeting_date != ''
                )
                """,
                (div_id, div_id),
            ).fetchone()
            docs_since = (
                earliest_row["min_dt"]
                if earliest_row and earliest_row["min_dt"]
                else now_iso
            )

            actions = conn.execute(
                """
                SELECT ea.*, e.name AS entity_name, e.district AS entity_district,
                       e.role AS entity_role, e.elected_date AS entity_elected_date
                FROM entity_actions ea
                JOIN events ev ON ea.event_id = ev.event_id
                JOIN entities e ON ea.entity_id = e.ocd_person_id
                WHERE ev.jurisdiction_id = ?
                """,
                (div_id,),
            ).fetchall()

            actions_by_event: Dict[str, List[Dict[str, Any]]] = {}
            actions_by_entity: Dict[str, List[Dict[str, Any]]] = {}
            for a in actions:
                a_dict = dict(a)
                actions_by_event.setdefault(a["event_id"], []).append(a_dict)
                actions_by_entity.setdefault(a["entity_id"], []).append(a_dict)

            events_by_id = {ev["event_id"]: dict(ev) for ev in events}
            roster_size = len(entities)

            exported_events: List[Dict[str, Any]] = []
            for ev in events:
                ev_id = ev["event_id"]
                ev_actions = actions_by_event.get(ev_id, [])

                vote_records = []
                sponsors = []
                quotes_list = []

                for act in ev_actions:
                    if act["action_type"] == "vote":
                        vote_records.append(
                            {
                                "entity_id": act["entity_id"],
                                "name": act["entity_name"],
                                "district": act["entity_district"],
                                "role": act["entity_role"],
                                "elected_date": act["entity_elected_date"] or "Active Term",
                                "vote": act["value"],
                                "is_pivotal": bool(act["is_pivotal"]),
                                "rationale_summary": act["rationale_summary"],
                                "verbatim_quote": act["verbatim_quote"],
                            }
                        )
                        if act["verbatim_quote"]:
                            quotes_list.append(
                                {
                                    "speaker": act["entity_name"],
                                    "quote": act["verbatim_quote"],
                                }
                            )
                    elif act["action_type"] in ("sponsor", "motion", "second"):
                        sponsors.append(
                            {
                                "entity_id": act["entity_id"],
                                "name": act["entity_name"],
                                "action_type": act["action_type"],
                            }
                        )

                present_count = sum(
                    1 for v in vote_records if v["vote"] in ("Yes", "No", "Abstain")
                )
                attendance_rate = (
                    round((present_count / roster_size) * 100, 1)
                    if roster_size > 0 and vote_records
                    else None
                )

                ev_payload = {
                    "event_id": ev_id,
                    "meeting_date": ev["meeting_date"],
                    "title": ev["title"],
                    "event_type": ev["event_type"],
                    "topic": ev["topic"] or "General",
                    "outcome": ev["outcome"],
                    "yes_count": ev["yes_count"],
                    "no_count": ev["no_count"],
                    "abstain_count": ev["abstain_count"],
                    "absent_count": ev["absent_count"],
                    "vote_margin": ev["vote_margin"],
                    "impact_score": ev["impact_score"],
                    "source_url": ev["source_url"] or j["portal_url"],
                    "attendance_count": present_count,
                    "roster_size": roster_size,
                    "attendance_rate": attendance_rate,
                    "sponsors": sponsors,
                    "votes": vote_records,
                    "quotes": quotes_list,
                }
                exported_events.append(ev_payload)

                global_search_index.append(
                    {
                        "event_id": ev_id,
                        "jurisdiction_id": div_id,
                        "jurisdiction_name": j["name"],
                        "jurisdiction_file": file_name,
                        "meeting_date": ev["meeting_date"],
                        "title": ev["title"],
                        "event_type": ev["event_type"],
                        "topic": ev["topic"] or "General",
                        "outcome": ev["outcome"],
                        "yes_count": ev["yes_count"],
                        "no_count": ev["no_count"],
                        "impact_score": ev["impact_score"],
                        "quotes_text": " ".join(q["quote"] for q in quotes_list),
                        "voters_text": " ".join(
                            f"{v['name']}:{v['vote']}" for v in vote_records
                        ),
                    }
                )

            exported_entities: List[Dict[str, Any]] = []
            for ent in entities:
                pid = ent["ocd_person_id"]
                p_actions = actions_by_entity.get(pid, [])

                vote_history = []
                sponsored_items = []
                present_votes = 0
                total_vote_records = 0
                pivotal_count = 0
                impact_scores = []

                for act in p_actions:
                    ev_ref = events_by_id.get(act["event_id"])
                    if not ev_ref:
                        continue

                    if act["action_type"] == "vote":
                        total_vote_records += 1
                        val = act["value"]
                        if val in ("Yes", "No", "Abstain"):
                            present_votes += 1
                        if act["is_pivotal"]:
                            pivotal_count += 1
                        if ev_ref.get("impact_score") is not None:
                            impact_scores.append(float(ev_ref["impact_score"]))

                        vote_history.append(
                            {
                                "event_id": act["event_id"],
                                "meeting_date": ev_ref["meeting_date"],
                                "title": ev_ref["title"],
                                "event_type": ev_ref["event_type"],
                                "topic": ev_ref["topic"] or "General",
                                "outcome": ev_ref["outcome"],
                                "vote": val,
                                "is_pivotal": bool(act["is_pivotal"]),
                                "impact_score": ev_ref["impact_score"],
                                "rationale_summary": act["rationale_summary"],
                                "verbatim_quote": act["verbatim_quote"],
                                "source_url": ev_ref["source_url"] or j["portal_url"],
                            }
                        )
                    elif act["action_type"] in ("sponsor", "motion", "second"):
                        sponsored_items.append(
                            {
                                "event_id": act["event_id"],
                                "meeting_date": ev_ref["meeting_date"],
                                "title": ev_ref["title"],
                                "action_type": act["action_type"],
                                "outcome": ev_ref["outcome"],
                            }
                        )

                vote_history.sort(key=lambda x: x["meeting_date"], reverse=True)
                sponsored_items.sort(key=lambda x: x["meeting_date"], reverse=True)

                attendance_pct = (
                    round((present_votes / total_vote_records) * 100, 1)
                    if total_vote_records > 0
                    else 0.0
                )
                avg_impact = (
                    round(sum(impact_scores) / len(impact_scores), 1)
                    if impact_scores
                    else 0.0
                )
                pivotal_pct = (
                    round((pivotal_count / total_vote_records) * 100, 1)
                    if total_vote_records > 0
                    else 0.0
                )

                exported_entities.append(
                    {
                        "ocd_person_id": pid,
                        "name": ent["name"],
                        "entity_type": ent["entity_type"],
                        "role": ent["role"],
                        "district": ent["district"],
                        "elected_date": ent["elected_date"] or "Active Term",
                        "party": ent["party"] or "Nonpartisan",
                        "phone": ent["phone"],
                        "email": ent["email"],
                        "website_url": ent["website_url"] or ent["portal_url"],
                        "portal_url": ent["portal_url"] or j["portal_url"],
                        "social_links": safe_json_loads(ent["social_links_json"], {}),
                        "bio_extra": safe_json_loads(ent["bio_extra_json"], {}),
                        "metrics": {
                            "total_votes": total_vote_records,
                            "present_votes": present_votes,
                            "attendance_rate": attendance_pct,
                            "avg_impact_score": avg_impact,
                            "pivotal_votes": pivotal_count,
                            "pivotal_rate": pivotal_pct,
                            "sponsored_count": len(sponsored_items),
                        },
                        "sponsored_items": sponsored_items,
                        "votes": vote_history,
                    }
                )

            jurisdiction_payload = {
                "jurisdiction": {
                    "ocd_division_id": div_id,
                    "name": j["name"],
                    "level": j["level"],
                    "lat": j["lat"],
                    "lng": j["lng"],
                    "portal_url": j["portal_url"],
                    "parent_division_id": j["parent_division_id"],
                    "docs_since": docs_since,
                    "last_updated": now_iso,
                },
                "entities": exported_entities,
                "events": exported_events,
            }

            out_file = OUTPUT_DIR / file_name
            out_file.write_text(json.dumps(jurisdiction_payload, indent=2), encoding="utf-8")

            index_jurisdictions.append(
                {
                    "ocd_division_id": div_id,
                    "name": j["name"],
                    "level": j["level"],
                    "status": "active",
                    "lat": j["lat"],
                    "lng": j["lng"],
                    "portal_url": j["portal_url"],
                    "parent_division_id": j["parent_division_id"],
                    "file": file_name,
                    "entity_count": len(exported_entities),
                    "event_count": len(exported_events),
                    "docs_since": docs_since,
                    "last_updated": now_iso,
                }
            )

        index_payload = {
            "last_updated": now_iso,
            "jurisdictions": index_jurisdictions,
            "search_index": global_search_index,
        }
        (OUTPUT_DIR / "index.json").write_text(
            json.dumps(index_payload, indent=2), encoding="utf-8"
        )

        print(
            f"Exported {len(index_jurisdictions)} jurisdiction entries and "
            f"{len(global_search_index)} searchable event(s) to {OUTPUT_DIR}/"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    export_all()
