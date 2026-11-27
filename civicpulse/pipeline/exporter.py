from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from civicpulse.agents.engagement import build_engagement_guides, normalize_human_portal_url
from civicpulse.agents.lifecycle import build_bill_lifecycles
from civicpulse.config import SETTINGS
from civicpulse.db import backup_database, get_connection, init_db


def slugify_division(div_id: str) -> str:
    return (
        div_id.replace("ocd-division/", "")
        .replace("/", "__")
        .replace(":", "_")
        .replace("-", "_")
    )


def export_all(
    db_path: Optional[str] = None,
    out_dir: Optional[Path] = None,
    run_backup: bool = True,
) -> Dict[str, Any]:
    """Single unified exporter: builds sharded jurisdiction JSON, directory.json, lazy search_index.json,
    backwards-compatible index.json, engagement_guides.json, and bill_lifecycles.json."""
    init_db(db_path)
    target_dir = out_dir or SETTINGS.public_data_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = get_connection(db_path)
    try:
        jurs = conn.execute(
            """
            SELECT * FROM jurisdictions
            ORDER BY CASE WHEN LOWER(COALESCE(status, 'active')) = 'active' THEN 0 ELSE 1 END, name ASC
            """
        ).fetchall()

        jurisdiction_entries: List[Dict[str, Any]] = []
        search_index: List[Dict[str, Any]] = []

        for j in jurs:
            div_id = j["ocd_division_id"]
            status = (j["status"] or "active").lower()
            file_name = f"{slugify_division(div_id)}.json"
            human_portal = normalize_human_portal_url(j["portal_url"] or "")

            entities_rows = conn.execute(
                "SELECT * FROM entities WHERE jurisdiction_id = ? AND active = 1 ORDER BY district ASC, name ASC",
                (div_id,),
            ).fetchall()

            events_rows = conn.execute(
                "SELECT * FROM events WHERE jurisdiction_id = ? ORDER BY meeting_date DESC, event_id DESC",
                (div_id,),
            ).fetchall()

            doc_stats = conn.execute(
                "SELECT COUNT(*) AS cnt, MIN(meeting_date) AS first_dt FROM documents WHERE jurisdiction_id = ?",
                (div_id,),
            ).fetchone()
            doc_count = doc_stats["cnt"] or 0
            docs_since = doc_stats["first_dt"] or (events_rows[-1]["meeting_date"] if events_rows else today_str)

            # Single batched query per jurisdiction (eliminates N+1 per-event queries)
            all_actions = conn.execute(
                """
                SELECT ea.*
                FROM entity_actions ea
                JOIN events e ON ea.event_id = e.event_id
                WHERE e.jurisdiction_id = ?
                """,
                (div_id,),
            ).fetchall()

            actions_by_event: Dict[str, List[Any]] = defaultdict(list)
            actions_by_entity: Dict[str, List[Any]] = defaultdict(list)
            for act in all_actions:
                actions_by_event[act["event_id"]].append(act)
                actions_by_entity[act["entity_id"]].append(act)

            roster_size = len(entities_rows)
            event_lookup = {ev["event_id"]: ev for ev in events_rows}
            entities_out: List[Dict[str, Any]] = []

            for ent in entities_rows:
                pid = ent["ocd_person_id"]
                ent_acts = actions_by_entity.get(pid, [])
                votes_list = []
                sponsored_list = []
                present_votes = 0
                total_votes = 0
                pivotal_votes = 0
                impact_scores: List[float] = []

                for act in ent_acts:
                    ev = event_lookup.get(act["event_id"])
                    if not ev:
                        continue
                    if (act["action_type"] or "").lower() == "vote":
                        total_votes += 1
                        val = (act["value"] or "").strip()
                        if val.lower() not in ("absent", ""):
                            present_votes += 1
                        if act["is_pivotal"]:
                            pivotal_votes += 1
                        imp = float(ev["impact_score"] or 0.0)
                        impact_scores.append(imp)
                        votes_list.append(
                            {
                                "event_id": ev["event_id"],
                                "meeting_date": ev["meeting_date"],
                                "title": ev["title"],
                                "plain_summary": ev["plain_summary"] or "",
                                "event_type": ev["event_type"],
                                "vote": val or "Absent",
                                "is_pivotal": bool(act["is_pivotal"]),
                                "impact_score": imp,
                                "rationale_summary": act["rationale_summary"] or "",
                                "verbatim_quote": act["verbatim_quote"] or "",
                            }
                        )
                    else:
                        sponsored_list.append(
                            {
                                "event_id": ev["event_id"],
                                "meeting_date": ev["meeting_date"],
                                "title": ev["title"],
                                "action_type": act["action_type"],
                            }
                        )

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

                entities_out.append(
                    {
                        "ocd_person_id": pid,
                        "jurisdiction_id": div_id,
                        "name": ent["name"],
                        "entity_type": ent["entity_type"] or "legislator",
                        "role": ent["role"] or "Representative",
                        "district": ent["district"] or "At-Large",
                        "elected_date": ent["elected_date"] or "Active Term",
                        "website_url": ent["website_url"] or "",
                        "portal_url": normalize_human_portal_url(ent["portal_url"] or human_portal),
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
                    }
                )

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
                        votes_detail.append(
                            {
                                "entity_id": act["entity_id"],
                                "name": ent_name,
                                "district": ent_obj["district"] if ent_obj else "",
                                "elected_date": ent_obj["elected_date"] if ent_obj else "Active Term",
                                "vote": act["value"] or "Absent",
                                "is_pivotal": bool(act["is_pivotal"]),
                                "rationale_summary": act["rationale_summary"] or "",
                                "verbatim_quote": act["verbatim_quote"] or "",
                            }
                        )
                    else:
                        sponsors_detail.append(
                            {
                                "entity_id": act["entity_id"],
                                "name": ent_name,
                                "action_type": act["action_type"],
                            }
                        )

                yes_c = int(ev["yes_count"] or 0)
                no_c = int(ev["no_count"] or 0)
                abs_c = int(ev["abstain_count"] or 0)
                miss_c = int(ev["absent_count"] or 0)
                att_count = yes_c + no_c + abs_c
                att_rate = round((att_count / roster_size) * 100) if roster_size > 0 else None

                ev_dict = {
                    "event_id": ev_id,
                    "jurisdiction_id": div_id,
                    "meeting_date": ev["meeting_date"],
                    "title": ev["title"],
                    "plain_summary": ev["plain_summary"] or "",
                    "diff_summary": ev["diff_summary"] or "",
                    "qa_status": ev["qa_status"] or "verified",
                    "event_type": ev["event_type"] or "ordinance",
                    "topic": ev["topic"] or "General",
                    "outcome": ev["outcome"] or "Recorded",
                    "yes_count": yes_c,
                    "no_count": no_c,
                    "abstain_count": abs_c,
                    "absent_count": miss_c,
                    "vote_margin": int(ev["vote_margin"] or abs(yes_c - no_c)),
                    "impact_score": float(ev["impact_score"] or 0.0),
                    "source_url": normalize_human_portal_url(ev["source_url"] or human_portal),
                    "roster_size": roster_size,
                    "attendance_count": att_count,
                    "attendance_rate": att_rate,
                    "sponsors": sponsors_detail,
                    "votes": votes_detail,
                }
                events_out.append(ev_dict)

                if status == "active":
                    search_index.append(
                        {
                            "event_id": ev_id,
                            "jurisdiction_id": div_id,
                            "jurisdiction_name": j["name"],
                            "meeting_date": ev["meeting_date"],
                            "title": ev["title"],
                            "plain_summary": ev["plain_summary"] or "",
                            "topic": ev["topic"] or "General",
                            "outcome": ev["outcome"] or "Recorded",
                            "yes_count": yes_c,
                            "no_count": no_c,
                            "impact_score": float(ev["impact_score"] or 0.0),
                            "quotes_text": " ".join(quotes_texts),
                            "voters_text": " ".join(voters_texts),
                        }
                    )

            jur_payload = {
                "jurisdiction": {
                    "ocd_division_id": div_id,
                    "name": j["name"],
                    "level": j["level"],
                    "lat": j["lat"],
                    "lng": j["lng"],
                    "portal_url": human_portal,
                    "parent_division_id": j["parent_division_id"],
                    "status": status,
                    "docs_since": docs_since,
                    "last_updated": now_str,
                },
                "entities": entities_out,
                "events": events_out,
            }
            if status == "active":  # [ACTIVE-ONLY-SHARDS]
                (target_dir / file_name).write_text(json.dumps(jur_payload, indent=2), encoding="utf-8")

            jurisdiction_entries.append(
                {
                    "ocd_division_id": div_id,
                    "name": j["name"],
                    "level": j["level"],
                    "lat": j["lat"],
                    "lng": j["lng"],
                    "portal_url": human_portal,
                    "parent_division_id": j["parent_division_id"],
                    "status": status,
                    "file": file_name,
                    "entity_count": len(entities_out),
                    "event_count": len(events_out),
                    "document_count": doc_count,
                    "docs_since": docs_since,
                    "last_updated": now_str,
                }
            )

        # 1. Lightweight directory.json for fast initial page render
        directory_payload = {
            "last_updated": now_str,
            "jurisdictions": jurisdiction_entries,
        }
        (target_dir / "directory.json").write_text(json.dumps(directory_payload, indent=2), encoding="utf-8")

        # 2. Dedicated lazy-loaded search_index.json
        search_payload = {
            "last_updated": now_str,
            "search_index": search_index,
        }
        (target_dir / "search_index.json").write_text(json.dumps(search_payload, indent=2), encoding="utf-8")

        # 3. Backwards-compatible index.json (metadata only; frontend lazy-loads search_index.json)
        (target_dir / "index.json").write_text(json.dumps(directory_payload, indent=2), encoding="utf-8")
    finally:
        conn.close()

    # 4. Run Agent 3 (Engagement Guides) & Agent 4 (Bill Lifecycles)
    build_engagement_guides(db_path=db_path, out_dir=target_dir)
    build_bill_lifecycles(db_path=db_path, out_dir=target_dir)

    if run_backup:
        backup_path = backup_database(db_path=db_path)
        if backup_path:
            print(f"[BACKUP] Saved SQLite snapshot to {backup_path}")

    print(
        f"[EXPORT] Wrote directory.json ({len(jurisdiction_entries)} jurisdictions) "
        f"& search_index.json ({len(search_index)} events) to {target_dir}"
    )
    return {"jurisdictions": len(jurisdiction_entries), "search_events": len(search_index)}
