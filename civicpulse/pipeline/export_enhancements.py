"""Post-export enhancements & full-site normalization sync for CivicPulse v2 Clean Baseline.

Runs right after `python -m civicpulse.cli export` to guarantee every exported file
under public/ shares the exact same clean, normalized, Colorado-scoped state:
  1. Purges archived out-of-scope jurisdictions (e.g., San Jose, CA) from directory.json,
     index.json, and public/data/country_us__*.json
  2. Syncs normalized topics, outcomes, tallies, committee-aware Impact Scores,
     capture provenance, QA status, and freshness badges into EVERY per-jurisdiction JSON
     and search_index.json (not just search_chunks/)
  3. Exports versioned scoring methodology JSON + downloadable .md / .json formula docs
  4. Exports upcoming_meetings.json, quarterly search_chunks/, and per-city/topic RSS feeds
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


def _slugify(div_id: str) -> str:
    return div_id.replace("ocd-division/", "").replace("/", "__").replace(":", "_").replace("-", "_")


def build_upcoming_meetings(conn: sqlite3.Connection, today_iso: str) -> List[Dict[str, Any]]:
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
    chunks_dir = data_dir / "search_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Clear old chunk files before regenerating
    for old_f in chunks_dir.glob("*.json"):
        old_f.unlink()

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
        "schema_version": "2.2",
        "formula_version": FORMULA_VERSION,
        "total_events": len(events),
        "chunks": manifest_chunks,
    }
    (chunks_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _sync_per_jurisdiction_json_files(
    data_dir: Path,
    archived_ids: set,
    events_by_id: Dict[str, Dict[str, Any]],
    latest_date_by_jur: Dict[str, str],
    now_utc: datetime,
) -> Dict[str, int]:
    """Removes archived jurisdiction JSONs and syncs normalized fields into active ones."""
    removed = 0
    patched = 0

    for jid in archived_ids:
        stale_file = data_dir / f"{_slugify(jid)}.json"
        if stale_file.exists():
            stale_file.unlink()
            removed += 1

    for jf in sorted(data_dir.glob("country_us__*.json")):
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        jur_obj = payload.get("jurisdiction")
        jid = ""
        if isinstance(jur_obj, dict):
            jid = jur_obj.get("ocd_division_id") or jur_obj.get("jurisdiction_id") or ""
            if jid in archived_ids:
                jf.unlink()
                removed += 1
                continue
            jur_obj["level"] = normalize_level(jur_obj.get("level"), jid)
            as_of = latest_date_by_jur.get(jid) or jur_obj.get("last_updated") or ""
            stale_days = _days_since(as_of, now_utc)
            jur_obj["as_of_date"] = as_of[:10] if as_of else None
            jur_obj["stale_days"] = stale_days
            jur_obj["is_stale"] = bool(
                (jur_obj.get("status") or "active") == "active"
                and stale_days is not None
                and stale_days > STALE_THRESHOLD_DAYS
            )
            jur_obj["formula_version"] = FORMULA_VERSION

        # Patch normalized event fields inside payload["events"]
        ev_list = payload.get("events")
        if isinstance(ev_list, list):
            for ev in ev_list:
                eid = ev.get("event_id")
                norm = events_by_id.get(eid)
                if not norm:
                    continue
                ev["topic"] = norm["topic"]
                ev["business_relevant"] = norm["business_relevant"]
                ev["outcome"] = norm["outcome_status"]
                ev["outcome_status"] = norm["outcome_status"]
                ev["passage_method"] = norm["passage_method"]
                ev["tally"] = norm["tally"]
                ev["body_type"] = norm["body_type"]
                ev["impact_score"] = norm["impact_score"]
                ev["impact_breakdown"] = norm["impact_breakdown"]
                ev["formula_version"] = norm["formula_version"]
                ev["capture_method"] = norm["capture_method"]
                ev["qa_status"] = norm["qa_status"]

        jf.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        patched += 1

    return {"archived_files_removed": removed, "jurisdiction_files_synced": patched}


def run_export_enhancements(
    db_path: str = "core_civic.db",
    public_dir: Path = Path("public"),
    site_base_url: str = "https://civics-d03.pages.dev",
) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    today_iso = now_utc.strftime("%Y-%m-%d")
    data_dir = public_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    scoring_out = write_scoring_docs(public_dir)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        archived_ids = {
            r[0]
            for r in conn.execute(
                "SELECT ocd_division_id FROM jurisdictions WHERE LOWER(COALESCE(status, '')) = 'archived'"
            ).fetchall()
        }

        upcoming = build_upcoming_meetings(conn, today_iso)
        (data_dir / "upcoming_meetings.json").write_text(
            json.dumps({"as_of": today_iso, "count": len(upcoming), "meetings": upcoming}, indent=2) + "\n",
            encoding="utf-8",
        )

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
        doc_title_join = "LEFT JOIN documents d ON d.doc_id = e.doc_id" if "doc_id" in ev_cols else ""
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
        events_by_id: Dict[str, Dict[str, Any]] = {}
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
            ev_obj = {
                "event_id": r["event_id"],
                "jurisdiction_id": jid,
                "jurisdiction_slug": _slugify(jid),
                "jurisdiction_name": r["jurisdiction_name"],
                "level": normalize_level(r["level"], jid),
                "meeting_date": mdate,
                "title": r["title"],
                "event_type": r["event_type"],
                "topic": topic,
                "business_relevant": is_business_relevant(topic),
                "outcome": norm_out.status,
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
            }
            normalized_events.append(ev_obj)
            events_by_id[r["event_id"]] = ev_obj

        # 1. Write quarterly search shards + keep monolithic search_index.json normalized in sync
        shard_manifest = shard_search_index(normalized_events, data_dir)
        (data_dir / "search_index.json").write_text(
            json.dumps(normalized_events, indent=2) + "\n", encoding="utf-8"
        )

        # 2. Generate RSS feeds
        feed_manifest = generate_all_feeds(normalized_events, public_dir, site_base_url=site_base_url)

        # 3. Sync directory.json & legacy index.json (strip archived rows, normalize levels, add freshness)
        for fname in ("directory.json", "index.json"):
            fpath = data_dir / fname
            if not fpath.exists():
                continue
            obj = json.loads(fpath.read_text(encoding="utf-8"))
            is_list = isinstance(obj, list)
            jurs = obj if is_list else obj.get("jurisdictions", [])
            cleaned = []
            for j in jurs:
                jid = j.get("ocd_division_id") or j.get("jurisdiction_id") or ""
                if jid in archived_ids or (j.get("status") or "").lower() == "archived":
                    continue
                j["level"] = normalize_level(j.get("level"), jid)
                as_of = latest_date_by_jur.get(jid) or j.get("last_updated") or ""
                stale_days = _days_since(as_of, now_utc)
                j["as_of_date"] = as_of[:10] if as_of else None
                j["stale_days"] = stale_days
                j["is_stale"] = bool(
                    (j.get("status") or "active") == "active"
                    and stale_days is not None
                    and stale_days > STALE_THRESHOLD_DAYS
                )
                cleaned.append(j)
            if is_list:
                obj = cleaned
            else:
                obj["jurisdictions"] = cleaned
                obj["formula_version"] = FORMULA_VERSION
                obj["formula_hash"] = scoring_out["formula_hash"]
                obj["as_of_date"] = today_iso
                if "search_index" in obj:
                    obj["search_index"] = normalized_events
            fpath.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

        # 4. Sync all per-jurisdiction JSONs & remove archived files
        sync_stats = _sync_per_jurisdiction_json_files(
            data_dir, archived_ids, events_by_id, latest_date_by_jur, now_utc
        )

        return {
            "scoring": scoring_out,
            "upcoming_count": len(upcoming),
            "normalized_events": len(normalized_events),
            "search_chunks": len(shard_manifest["chunks"]),
            "rss_jurisdictions": len(feed_manifest["jurisdictions"]),
            "rss_topics": len(feed_manifest["topics"]),
            **sync_stats,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CivicPulse v2 Clean Baseline export enhancements.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--public-dir", default="public")
    parser.add_argument("--site-url", default="https://civics-d03.pages.dev")
    args = parser.parse_args()
    res = run_export_enhancements(args.db, Path(args.public_dir), site_base_url=args.site_url)
    print("[EXPORT+] Complete:", json.dumps(res))


if __name__ == "__main__":
    main()
