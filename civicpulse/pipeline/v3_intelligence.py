"""CivicPulse v3 Customer Intelligence Exporter (civicpulse/pipeline/v3_intelligence.py).

Generates static, $0/month JSON intelligence bundles for the v3 Customer Suite:
  1. public/data/executive_digest.json   — High-impact decisions, split votes, business/regulatory radar
  2. public/data/alignment_explorer.json — Per-council pairwise voting alignment, dissent rate & split-vote explorer
  3. public/data/official_contacts.json  — Verified representative emails + official council public-comment fallbacks

Usage:
  python -m civicpulse.pipeline.v3_intelligence --db core_civic.db --public-dir public
"""
from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Official public-comment / council-wide email addresses for active Colorado jurisdictions
# Used as automatic fallback in Public Comment Composer when an individual seat lacks an email.
OFFICIAL_COUNCIL_COMMENT_EMAILS: Dict[str, Dict[str, str]] = {
    "ocd-division/country:us/state:co/place:fort_collins": {
        "council_email": "cityleaders@fcgov.com",
        "clerk_url": "https://www.fcgov.com/cityclerk/",
    },
    "ocd-division/country:us/state:co/place:denver": {
        "council_email": "dencc@denvergov.org",
        "clerk_url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Denver-City-Council",
    },
    "ocd-division/country:us/state:co/place:colorado_springs": {
        "council_email": "allcouncil@coloradosprings.gov",
        "clerk_url": "https://coloradosprings.gov/city-council",
    },
    "ocd-division/country:us/state:co/place:boulder": {
        "council_email": "council@bouldercolorado.gov",
        "clerk_url": "https://bouldercolorado.gov/government/city-council",
    },
    "ocd-division/country:us/state:co/place:greeley": {
        "council_email": "citycouncil@greeleygov.com",
        "clerk_url": "https://greeleygov.com/government/council",
    },
    "ocd-division/country:us/state:co/place:longmont": {
        "council_email": "city.clerk@longmontcolorado.gov",
        "clerk_url": "https://longmontcolorado.gov/city-council/",
    },
    "ocd-division/country:us/state:co/place:thornton": {
        "council_email": "council@thorntonco.gov",
        "clerk_url": "https://www.thorntonco.gov/government/city-council",
    },
    "ocd-division/country:us/state:co/place:westminster": {
        "council_email": "citycouncil@westminsterco.gov",
        "clerk_url": "https://www.westminsterco.gov/Government/CityCouncil",
    },
    "ocd-division/country:us/state:co/place:erie": {
        "council_email": "council@erieco.gov",
        "clerk_url": "https://www.erieco.gov/176/Town-Council",
    },
    "ocd-division/country:us/state:co/place:windsor": {
        "council_email": "townboard@windsorgov.com",
        "clerk_url": "https://www.windsorgov.com/101/Town-Board",
    },
    "ocd-division/country:us/state:co/school_district:poudre_r1": {
        "council_email": "board@psdschools.org",
        "clerk_url": "https://www.psdschools.org/your-district/board-of-education",
    },
    "ocd-division/country:us/state:co/place:arvada": {
        "council_email": "citycouncil@arvada.org",
        "clerk_url": "https://www.arvadaco.gov/249/City-Council",
    },
    "ocd-division/country:us/state:co/place:pueblo": {
        "council_email": "cityclerk@pueblo.us",
        "clerk_url": "https://www.pueblo.us/104/City-Council",
    },
    "ocd-division/country:us/state:co/place:commerce_city": {
        "council_email": "cityclerk@c3gov.com",
        "clerk_url": "https://www.c3gov.com/government/city-council",
    },
    "ocd-division/country:us/state:co/place:grand_junction": {
        "council_email": "citycouncil@gjcity.org",
        "clerk_url": "https://www.gjcity.org/166/City-Council",
    },
    "ocd-division/country:us/state:co/place:aurora": {
        "council_email": "citycouncil@auroragov.org",
        "clerk_url": "https://www.auroragov.org/city_hall/mayor___city_council",
    },
    "ocd-division/country:us/state:co/county:boulder": {
        "council_email": "commissioners@bouldercounty.gov",
        "clerk_url": "https://bouldercounty.gov/government/board-of-county-commissioners/",
    },
    "ocd-division/country:us/state:co/school_district:boulder_valley_re2": {
        "council_email": "bvsd.board@bvsd.org",
        "clerk_url": "https://www.bvsd.org/about/board-of-education",
    },
}

BUSINESS_TOPICS = {
    "Zoning & Land Use",
    "Permits & Licensing",
    "Taxes, Fees & Utilities",
    "Contracts & Procurement",
    "Housing & Development",
    "Budget & Finance",
    "Transportation & Infrastructure",
}


def _norm_vote(v: str) -> str:
    s = (v or "").strip().lower()
    if s in ("yes", "yea", "aye", "for", "approve", "approved"):
        return "yes"
    if s in ("no", "nay", "against", "oppose", "denied"):
        return "no"
    return ""


def build_executive_digest(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = conn.execute(
        """
        SELECT e.event_id, e.jurisdiction_id, j.name AS jurisdiction_name,
               e.meeting_date, e.title, e.topic, e.outcome,
               COALESCE(e.yes_count, 0) AS yes_count,
               COALESCE(e.no_count, 0) AS no_count,
               COALESCE(e.impact_score, 0) AS impact_score,
               COALESCE(e.plain_summary, '') AS plain_summary,
               COALESCE(e.source_url, j.portal_url, '') AS source_url,
               COALESCE(e.qa_status, 'unverified') AS qa_status
        FROM events e
        JOIN jurisdictions j ON j.ocd_division_id = e.jurisdiction_id
        WHERE LOWER(COALESCE(j.status, 'active')) = 'active'
        ORDER BY e.meeting_date DESC, e.impact_score DESC
        """
    ).fetchall()

    items: List[Dict[str, Any]] = []
    split_votes: List[Dict[str, Any]] = []
    business_alerts: List[Dict[str, Any]] = []
    topic_counts: Counter = Counter()
    jur_counts: Counter = Counter()

    for r in rows:
        yes_c, no_c = int(r["yes_count"]), int(r["no_count"])
        is_split = yes_c > 0 and no_c > 0
        topic = r["topic"] or "General"
        topic_counts[topic] += 1
        jur_counts[r["jurisdiction_name"]] += 1

        card = {
            "event_id": r["event_id"],
            "jurisdiction_id": r["jurisdiction_id"],
            "jurisdiction_name": r["jurisdiction_name"],
            "meeting_date": r["meeting_date"] or "",
            "title": r["title"] or "",
            "topic": topic,
            "outcome": r["outcome"] or "Recorded",
            "yes_count": yes_c,
            "no_count": no_c,
            "is_split": is_split,
            "impact_score": int(r["impact_score"]),
            "plain_summary": r["plain_summary"],
            "source_url": r["source_url"],
            "qa_status": r["qa_status"],
        }
        items.append(card)
        if is_split:
            split_votes.append(card)
        if topic in BUSINESS_TOPICS:
            business_alerts.append(card)

    top_impact = sorted(items, key=lambda x: (-x["impact_score"], x["meeting_date"]), reverse=False)
    top_impact = sorted(items, key=lambda x: (x["impact_score"], x["meeting_date"]), reverse=True)[:12]
    recent_splits = sorted(split_votes, key=lambda x: (x["meeting_date"], x["impact_score"]), reverse=True)[:12]
    recent_biz = sorted(business_alerts, key=lambda x: (x["meeting_date"], x["impact_score"]), reverse=True)[:15]

    return {
        "schema_version": "3.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "stats": {
            "total_events": len(items),
            "total_split_votes": len(split_votes),
            "split_vote_pct": round((len(split_votes) / len(items)) * 100, 1) if items else 0.0,
            "active_jurisdictions_with_events": len(jur_counts),
            "business_relevant_events": len(business_alerts),
        },
        "top_topics": [{"topic": k, "count": v} for k, v in topic_counts.most_common(10)],
        "top_impact_decisions": top_impact,
        "notable_split_votes": recent_splits,
        "business_regulatory_alerts": recent_biz,
    }


def build_alignment_explorer(conn: sqlite3.Connection) -> Dict[str, Any]:
    active_jurs = conn.execute(
        """
        SELECT ocd_division_id, name
        FROM jurisdictions
        WHERE LOWER(COALESCE(status, 'active')) = 'active'
        ORDER BY name ASC
        """
    ).fetchall()

    by_jur: Dict[str, Any] = {}

    for j in active_jurs:
        jid = j["ocd_division_id"]
        jname = j["name"]

        ev_rows = conn.execute(
            """
            SELECT event_id, meeting_date, title, topic, outcome,
                   COALESCE(yes_count, 0) AS yes_count,
                   COALESCE(no_count, 0) AS no_count,
                   COALESCE(impact_score, 0) AS impact_score,
                   COALESCE(source_url, '') AS source_url
            FROM events
            WHERE jurisdiction_id = ?
            ORDER BY meeting_date DESC
            """,
            (jid,),
        ).fetchall()

        if not ev_rows:
            continue

        ev_map = {r["event_id"]: dict(r) for r in ev_rows}
        action_rows = conn.execute(
            """
            SELECT ea.event_id, ea.entity_id, ea.action_type, COALESCE(en.name, ea.entity_id) AS rep_name
            FROM entity_actions ea
            LEFT JOIN entities en ON en.ocd_person_id = ea.entity_id
            WHERE ea.event_id IN (SELECT event_id FROM events WHERE jurisdiction_id = ?)
            """,
            (jid,),
        ).fetchall()

        votes_by_event: Dict[str, Dict[str, str]] = defaultdict(dict)
        rep_names: Dict[str, str] = {}
        for a in action_rows:
            nv = _norm_vote(a["action_type"])
            if not nv:
                continue
            votes_by_event[a["event_id"]][a["entity_id"]] = nv
            rep_names[a["entity_id"]] = a["rep_name"]

        pair_stats: Dict[Tuple[str, str], List[int]] = defaultdict(lambda: [0, 0])  # [agree, total]
        rep_dissent: Dict[str, List[int]] = defaultdict(lambda: [0, 0])  # [minority_votes, total_votes]
        split_cards: List[Dict[str, Any]] = []
        unanimous_cnt = 0
        split_cnt = 0

        for eid, ev in ev_map.items():
            vmap = votes_by_event.get(eid, {})
            yes_reps = sorted([rep_names[k] for k, v in vmap.items() if v == "yes"])
            no_reps = sorted([rep_names[k] for k, v in vmap.items() if v == "no"])

            is_split = (ev["yes_count"] > 0 and ev["no_count"] > 0) or (len(yes_reps) > 0 and len(no_reps) > 0)
            if is_split:
                split_cnt += 1
                split_cards.append({
                    "event_id": eid,
                    "meeting_date": ev["meeting_date"],
                    "title": ev["title"],
                    "topic": ev["topic"] or "General",
                    "outcome": ev["outcome"] or "Recorded",
                    "tally": f"{ev['yes_count']}-{ev['no_count']}",
                    "impact_score": int(ev["impact_score"]),
                    "yes_voters": yes_reps,
                    "no_voters": no_reps,
                    "source_url": ev["source_url"],
                })
            else:
                unanimous_cnt += 1

            # Determine majority side for dissent tracking
            if vmap:
                maj = "yes" if len(yes_reps) >= len(no_reps) else "no"
                for rid, rv in vmap.items():
                    rep_dissent[rid][1] += 1
                    if is_split and rv != maj:
                        rep_dissent[rid][0] += 1

                for r1, r2 in itertools.combinations(sorted(vmap.keys()), 2):
                    pair_stats[(r1, r2)][1] += 1
                    if vmap[r1] == vmap[r2]:
                        pair_stats[(r1, r2)][0] += 1

        pairs_out = []
        for (r1, r2), (agree, tot) in pair_stats.items():
            if tot < 2:
                continue
            pairs_out.append({
                "rep_a": rep_names.get(r1, r1),
                "rep_b": rep_names.get(r2, r2),
                "shared_votes": tot,
                "agreement_pct": round((agree / tot) * 100, 1),
            })

        most_aligned = sorted(pairs_out, key=lambda x: (-x["agreement_pct"], -x["shared_votes"]))[:6]
        most_divergent = sorted(pairs_out, key=lambda x: (x["agreement_pct"], -x["shared_votes"]))[:6]

        dissenters = []
        for rid, (min_v, tot_v) in rep_dissent.items():
            if tot_v < 1:
                continue
            dissenters.append({
                "entity_id": rid,
                "name": rep_names.get(rid, rid),
                "minority_votes": min_v,
                "total_votes": tot_v,
                "dissent_rate_pct": round((min_v / tot_v) * 100, 1),
            })
        dissenters.sort(key=lambda x: (-x["dissent_rate_pct"], -x["minority_votes"], x["name"]))

        total_ev = unanimous_cnt + split_cnt
        by_jur[jid] = {
            "jurisdiction_id": jid,
            "jurisdiction_name": jname,
            "total_events": total_ev,
            "unanimous_events": unanimous_cnt,
            "split_events": split_cnt,
            "split_rate_pct": round((split_cnt / total_ev) * 100, 1) if total_ev else 0.0,
            "dissent_leaderboard": dissenters[:12],
            "most_aligned_pairs": most_aligned,
            "most_divergent_pairs": most_divergent,
            "recent_split_votes": split_cards[:10],
        }

    return {
        "schema_version": "3.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "jurisdiction_count": len(by_jur),
        "by_jurisdiction": by_jur,
    }


def build_official_contacts(conn: sqlite3.Connection) -> Dict[str, Any]:
    jurs = conn.execute(
        """
        SELECT ocd_division_id, name, COALESCE(portal_url, '') AS portal_url
        FROM jurisdictions
        WHERE LOWER(COALESCE(status, 'active')) = 'active'
        ORDER BY name ASC
        """
    ).fetchall()

    ent_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    has_email = "email" in ent_cols
    has_phone = "phone" in ent_cols

    contacts: Dict[str, Any] = {}
    for j in jurs:
        jid = j["ocd_division_id"]
        fallback = OFFICIAL_COUNCIL_COMMENT_EMAILS.get(jid, {})
        sel_email = "COALESCE(email, '')" if has_email else "''"
        sel_phone = "COALESCE(phone, '')" if has_phone else "''"

        reps = conn.execute(
            f"""
            SELECT name, COALESCE(role, 'Representative') AS role,
                   COALESCE(district, 'At-Large') AS district,
                   {sel_email} AS email, {sel_phone} AS phone
            FROM entities
            WHERE jurisdiction_id = ? AND COALESCE(active, 1) = 1
            ORDER BY name ASC
            """,
            (jid,),
        ).fetchall()

        rep_list = [dict(r) for r in reps]
        rep_emails = [r["email"] for r in rep_list if r["email"]]

        contacts[jid] = {
            "jurisdiction_id": jid,
            "jurisdiction_name": j["name"],
            "council_comment_email": fallback.get("council_email") or (rep_emails[0] if rep_emails else ""),
            "clerk_url": fallback.get("clerk_url") or j["portal_url"],
            "representative_emails": rep_emails,
            "representatives": rep_list,
        }

    return {
        "schema_version": "3.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "by_jurisdiction": contacts,
    }


def run_v3_intelligence(db_path: str = "core_civic.db", public_dir: Path = Path("public")) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        digest = build_executive_digest(conn)
        alignment = build_alignment_explorer(conn)
        contacts = build_official_contacts(conn)
    finally:
        conn.close()

    data_dir = public_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "executive_digest.json").write_text(json.dumps(digest, indent=2) + "\n", encoding="utf-8")
    (data_dir / "alignment_explorer.json").write_text(json.dumps(alignment, indent=2) + "\n", encoding="utf-8")
    (data_dir / "official_contacts.json").write_text(json.dumps(contacts, indent=2) + "\n", encoding="utf-8")

    return {
        "executive_digest_events": digest["stats"]["total_events"],
        "split_votes": digest["stats"]["total_split_votes"],
        "alignment_jurisdictions": alignment["jurisdiction_count"],
        "contact_jurisdictions": len(contacts["by_jurisdiction"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CivicPulse v3 Customer Suite static JSON.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--public-dir", default="public")
    args = parser.parse_args()
    res = run_v3_intelligence(args.db, Path(args.public_dir))
    print("[V3-INTEL]", json.dumps(res))


if __name__ == "__main__":
    main()
