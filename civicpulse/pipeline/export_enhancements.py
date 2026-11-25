"""Post-export enhancements for CivicPulse v2.

Runs cleanly alongside (or right after) `python -m civicpulse.cli export` to add:
  1. Versioned scoring methodology JSON + downloadable Markdown/JSON formula files
  2. Upcoming Meetings & Public Comment Deadlines payload (public/data/upcoming_meetings.json)
  3. Quarterly sharded search index (public/data/search_chunks/) for fast pagination as data grows
  4. Per-jurisdiction and per-topic RSS 2.0 feeds (public/feeds/*.xml)
  5. Freshness metadata ("as_of_date", "stale_days", "is_stale") & normalized fields in directory.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from civicpulse.pipeline.feeds import generate_all_feeds
from civicpulse.pipeline.normalize import (
    classify_topic,
    detect_body_type,
    is_business_relevant,
    normalize_level,
    normalize_outcome,
)
from civicpulse.pipeline.scoring_spec import (
    FORMULA_VERSION,
    calculate_auditable_impact,
    write_scoring_docs,
)

STALE_THRESHOLD_DAYS = 14


def _quarter_key(date_str: str) -> str:
    if not date_str or len(date_str) < 7:
        return "undated"
    try:
        year = int(date_str[:4])
        month = int(date_str[5:7])
        q = (month - 1) // 3 + 1
        return f"{year}-Q{q}"
    except ValueError:
        return "undated"


def _days_since(date_str: Optional[str], now_utc: datetime) -> Optional[int]:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return max(0, (now_utc - dt).days)
    except ValueError:
        return None


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def build_upcoming_meetings(conn: sqlite3.Connection, today_iso: str) -> List[Dict[str, Any]]:
    """Extracts upcoming meetings from documents with meeting_date >= today."""
    doc_cols = _table_columns(conn, "documents")
    jur_cols = _table_columns(conn, "jurisdictions")
    if "documents" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }:
        return []

    portal_col = "j.portal_url" if "portal_url" in jur_cols else "''"
    level_col = "j.level" if "level" in jur_cols else "'city'"
    sql = f"""
        SELECT d.doc_id, d.jurisdiction_id, d.meeting_date, d.doc_type, d.title, d.source_url,
               j.name AS jurisdiction_name, {portal_col} AS portal_url, {level_col} AS level
        FROM documents d
        JOIN jurisdictions j ON j.ocd_division_id = d.jurisdiction_id
        WHERE d.meeting_date >= ?
          AND COALESCE(j.status, 'active') = 'active'
        ORDER BY d.meeting_date ASC, j.name ASC
        LIMIT 100
    """
    rows = conn.execute(sql, (today_iso,)).fetchall()
    seen = set()
    upcoming: List[Dict[str, Any]] = []
    for r in rows:
        key = (r["jurisdiction_id"], r["meeting_date"], (r["title"] or "")[:60])
        if key in seen:
            continue
        seen.add(key)
        upcoming.append({
            "jurisdiction_id": r["jurisdiction_id"],
            "jurisdiction_name": r["jurisdiction_name"],
            "level": normalize_level(r["level"], r["jurisdiction_id"]),
            "meeting_date": r["meeting_date"],
            "title": r["title"] or "Regular Meeting",
            "doc_type": r["doc_type"] or "agenda",
            "agenda_url": r["source_url"] or r["portal_url"] or "",
            "portal_url": r["portal_url"] or "",
            "public_comment_note": (
                "Check the official agenda packet for exact sign-up cutoff "
                "(most Front Range councils close written/online public comment 2-24 hours before gavel)."
            ),
        })
    return upcoming


def shard_search_index(events: List[Dict[str, Any]], data_dir: Path) -> Dict[str, Any]:
    """Splits search events into quarterly JSON shards so large indices load incrementally."""
    chunks_dir = data_dir / "search_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        qk = _quarter_key(ev.get("meeting_date") or "")
        grouped.setdefault(qk, []).append(ev)

    manifest_chunks = []
    for qk in sorted(grouped.keys(), reverse=True):
        chunk_events = sorted(
            grouped[qk],
            key=lambda x: (x.get("meeting_date") or "", x.get("impact_score") or 0),
            reverse=True,
        )
        chunk_file = chunks_dir / f"{qk}.json"
        chunk_file.write_text(json.dumps(chunk_events, indent=2) + "\n", encoding="utf-8")
        manifest_chunks.append({
            "quarter": qk,
            "path": f"data/search_chunks/{qk}.json",
            "count": len(chunk_events),
            "bytes": chunk_file.stat().st_size,
        })

    manifest = {
        "schema_version": "2.1",
        "formula_version": FORMULA_VERSION,
        "total_events": len(events),
        "chunks": manifest_chunks,
    }
    (chunks_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def run_export_enhancements(
    db_path: str = "core_civic.db",
    public_dir: Path = Path("public"),
    site_base_url: str = "https://civics-d03.pages.dev",
) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    today_iso = now_utc.strftime("%Y-%m-%d")
    data_dir = public_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Always export versioned scoring methodology + downloadable formula docs
    scoring_out = write_scoring_docs(public_dir)

    # 2. Load DB data for upcoming meetings, normalized events, freshness, and RSS feeds
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        upcoming = build_upcoming_meetings(conn, today_iso)
        (data_dir / "upcoming_meetings.json").write_text(
            json.dumps({"as_of": today_iso, "count": len(upcoming), "meetings": upcoming}, indent=2) + "\n",
            encoding="utf-8",
        )

        # Build enriched, normalized event list for sharding + RSS + business radar
        ev_cols = _table_columns(conn, "events")
        doc_cols = _table_columns(conn, "documents")
        jur_cols = _table_columns(conn, "jurisdictions")

        roster_sizes = {
            r["jurisdiction_id"]: r["cnt"]
            for r in conn.execute(
                "SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities WHERE COALESCE(active, 1) = 1 GROUP BY jurisdiction_id"
            ).fetchall()
        }
        vote_counts = {
            r["event_id"]: r["cnt"]
            for r in conn.execute(
                "SELECT event_id, COUNT(*) AS cnt FROM entity_actions GROUP BY event_id"
            ).fetchall()
        }

        capture_select = "e.capture_method" if "capture_method" in ev_cols else "'' AS capture_method"
        qa_select = "e.qa_status" if "qa_status" in ev_cols else "'verified' AS qa_status"
        doc_title_join = (
            "LEFT JOIN documents d ON d.doc_id = e.doc_id" if "doc_id" in ev_cols else ""
        )
        doc_title_col = "d.title AS doc_title" if "doc_id" in ev_cols and "title" in doc_cols else "'' AS doc_title"
        level_col = "j.level" if "level" in jur_cols else "'city'"

        rows = conn.execute(
            f"""
            SELECT e.event_id, e.jurisdiction_id, e.meeting_date, e.title, e.event_type,
                   e.topic, e.outcome, e.yes_count, e.no_count,
                   COALESCE(e.abstain_count, 0) AS abstain_count,
                   COALESCE(e.plain_summary, '') AS plain_summary,
                   COALESCE(e.source_url, '') AS source_url,
                   {capture_select}, {qa_select}, {doc_title_col},
                   j.name AS jurisdiction_name, {level_col} AS level,
                   COALESCE(j.adapter_type, '') AS adapter_type
            FROM events e
            JOIN jurisdictions j ON j.ocd_division_id = e.jurisdiction_id
            {doc_title_join}
            WHERE COALESCE(j.status, 'active') = 'active'
            ORDER BY e.meeting_date DESC
            """
        ).fetchall()

        normalized_events: List[Dict[str, Any]] = []
        latest_date_by_jur: Dict[str, str] = {}

        for r in rows:
            jid = r["jurisdiction_id"]
            mdate = r["meeting_date"] or ""
            if mdate > latest_date_by_jur.get(jid, ""):
                latest_date_by_jur[jid] = mdate

            ind_votes = vote_counts.get(r["event_id"], 0)
            norm_out = normalize_outcome(
                r["outcome"],
                r["yes_count"] or 0,
                r["no_count"] or 0,
                r["abstain_count"] or 0,
                individual_vote_count=ind_votes,
            )
            topic = classify_topic(r["title"], r["plain_summary"], r["topic"])
            roster_n = roster_sizes.get(jid, 0)
            body_type = detect_body_type(r["title"], r["doc_title"], norm_out.yes_count + norm_out.no_count, roster_n)
            expected_size = (
                max(norm_out.yes_count + norm_out.no_count + norm_out.abstain_count, 1)
                if body_type == "committee"
                else roster_n
            )
            impact = calculate_auditable_impact(
                event_type=r["event_type"] or "motion",
                yes_count=norm_out.yes_count,
                no_count=norm_out.no_count,
                abstain_count=norm_out.abstain_count,
                expected_body_size=expected_size,
                body_type=body_type,
                title=r["title"] or "",
                summary=r["plain_summary"] or "",
            )

            capture = r["capture_method"] or (
                "structured_api" if (r["adapter_type"] or "").lower() == "legistar" and ind_votes > 0 else "ai_minutes_pdf"
            )
            slug = jid.replace("ocd-division/", "").replace("/", "__").replace(":", "_").replace("-", "_")

            normalized_events.append({
                "event_id": r["event_id"],
                "jurisdiction_id": jid,
                "jurisdiction_slug": slug,
                "jurisdiction_name": r["jurisdiction_name"],
                "level": normalize_level(r["level"], jid),
                "meeting_date": mdate,
                "title": r["title"],
                "event_type": r["event_type"],
                "topic": topic,
                "business_relevant": is_business_relevant(topic),
                "outcome_status": norm_out.status,
                "passage_method": norm_out.passage_method,
                "tally": norm_out.tally,
                "yes_count": norm_out.yes_count,
                "no_count": norm_out.no_count,
                "body_type": body_type,
                "impact_score": impact.score,
                "impact_breakdown": impact.to_dict(),
                "formula_version": FORMULA_VERSION,
                "capture_method": capture,
                "qa_status": r["qa_status"] or "verified",
                "plain_summary": r["plain_summary"],
                "source_url": r["source_url"],
            })

        # 3. Write quarterly search shards + feeds
        shard_manifest = shard_search_index(normalized_events, data_dir)
        feed_manifest = generate_all_feeds(normalized_events, public_dir, site_base_url=site_base_url)

        # 4. Patch freshness & normalized levels into directory.json if present
        dir_path = data_dir / "directory.json"
        if dir_path.exists():
            dir_obj = json.loads(dir_path.read_text(encoding="utf-8"))
            jurs = dir_obj.get("jurisdictions", dir_obj if isinstance(dir_obj, list) else [])
            for j in jurs:
                jid = j.get("ocd_division_id") or j.get("jurisdiction_id") or ""
                j["level"] = normalize_level(j.get("level"), jid)
                as_of = latest_date_by_jur.get(jid) or j.get("last_updated") or ""
                stale_days = _days_since(as_of, now_utc)
                j["as_of_date"] = as_of[:10] if as_of else None
                j["stale_days"] = stale_days
                j["is_stale"] = bool(
                    j.get("status") == "active"
                    and stale_days is not None
                    and stale_days > STALE_THRESHOLD_DAYS
                )
            if isinstance(dir_obj, dict):
                dir_obj["formula_version"] = FORMULA_VERSION
                dir_obj["formula_hash"] = scoring_out["formula_hash"]
                dir_obj["as_of_date"] = today_iso
            dir_path.write_text(json.dumps(dir_obj, indent=2) + "\n", encoding="utf-8")

        return {
            "scoring": scoring_out,
            "upcoming_count": len(upcoming),
            "normalized_events": len(normalized_events),
            "search_chunks": len(shard_manifest["chunks"]),
            "rss_jurisdictions": len(feed_manifest["jurisdictions"]),
            "rss_topics": len(feed_manifest["topics"]),
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CivicPulse v2 post-export enhancements.")
    parser.add_argument("--db", default="core_civic.db", help="Path to SQLite database")
    parser.add_argument("--public-dir", default="public", help="Path to public output directory")
    parser.add_argument("--site-url", default="https://civics-d03.pages.dev", help="Base public URL")
    args = parser.parse_args()

    result = run_export_enhancements(args.db, Path(args.public_dir), site_base_url=args.site_url)
    print("[EXPORT+] Enhancements complete:", json.dumps(result))


if __name__ == "__main__":
    main()
