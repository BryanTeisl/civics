from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from civicpulse.agents.scout import onboard_jurisdiction
from civicpulse.config import SETTINGS
from civicpulse.db import backup_database, init_db
from civicpulse.maintenance import probe_config, seed_from_config
from civicpulse.pipeline.cadence import compute_work_batch_limit, get_due_watch_jurisdictions
from civicpulse.pipeline.exporter import export_all
from civicpulse.pipeline.metrics import recalculate_all_metrics
from civicpulse.pipeline.roster_sync import sync_rosters
from civicpulse.pipeline.watcher import run_watcher
from civicpulse.pipeline.worker import run_worker


def _run_watch_with_cadence(
    db_path: str,
    year: Optional[int],
    limit: int,
    jurisdiction_id: Optional[str],
    min_interval_days: int,
    force: bool,
) -> Dict[str, Any]:
    if force or min_interval_days <= 0:
        return run_watcher(db_path=db_path, year=year, limit_per_jur=limit, jurisdiction_id=jurisdiction_id)

    due, skipped = get_due_watch_jurisdictions(
        db_path=db_path,
        min_interval_days=min_interval_days,
        jurisdiction_id=jurisdiction_id,
        force=False,
    )
    if skipped:
        print(f"[WATCH] Skipping {len(skipped)} jurisdiction(s) polled within last {min_interval_days}d.", flush=True)
    totals: Dict[str, Any] = {
        "polled": 0,
        "inserted": 0,
        "skipped_adapters": 0,
        "errors": 0,
        "skipped_recent": len(skipped),
    }
    for j in due:
        st = run_watcher(db_path=db_path, year=year, limit_per_jur=limit, jurisdiction_id=j["ocd_division_id"])
        for k in ("polled", "inserted", "skipped_adapters", "errors"):
            totals[k] += int(st.get(k, 0))
    return totals


def _run_work_with_caps(
    db_path: str,
    limit: int,
    jurisdiction_id: Optional[str],
    doc_type: Optional[str],
    fetch_only: bool,
    requeue_skipped: bool,
    pct_per_day: Optional[float],
    max_per_day: Optional[int],
) -> Dict[str, Any]:
    effective_limit = limit
    if not fetch_only and (pct_per_day is not None or max_per_day is not None):
        cap_info = compute_work_batch_limit(
            db_path=db_path,
            limit=limit,
            jurisdiction_id=jurisdiction_id,
            doc_type=doc_type,
            pct_per_day=pct_per_day,
            max_per_day=max_per_day,
        )
        effective_limit = cap_info["effective_limit"]
        cap_desc = []
        if pct_per_day is not None:
            cap_desc.append(f"{pct_per_day:g}%/day")
        if max_per_day is not None:
            cap_desc.append(f"max {max_per_day}/day")
        print(
            f"[WORK][CAP] Pending={cap_info['pending_total']} | Done today={cap_info['done_today']} | "
            f"Batch limit={effective_limit} ({', '.join(cap_desc)})",
            flush=True,
        )
        if effective_limit <= 0:
            print("[WORK] Daily cap reached or queue empty; remaining pending docs stay queued for tomorrow.", flush=True)
            return {
                "fetched": 0,
                "processed": 0,
                "events_created": 0,
                "votes_created": 0,
                "failed": 0,
                "skipped": 0,
                "capped": True,
            }

    return run_worker(
        db_path=db_path,
        limit=effective_limit,
        jurisdiction_id=jurisdiction_id,
        doc_type=doc_type,
        fetch_only=fetch_only,
        requeue_skipped=requeue_skipped,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="civicpulse",
        description="CivicPulse unified CLI for ingestion, AI extraction, onboarding, and static JSON export.",
    )
    parser.add_argument("--db", default=SETTINGS.db_path, help="Path to SQLite database (default: core_civic.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize or migrate SQLite schema.")

    p_seed = sub.add_parser("seed", help="Seed jurisdictions from a declarative JSON config file.")
    p_seed.add_argument("--file", required=True, type=Path, help="Path to jurisdiction JSON config")
    p_seed.add_argument("--activate-structured", action="store_true", help="Activate verified structured platforms")

    p_probe = sub.add_parser("probe", help="Run live endpoint health checks against a jurisdiction config file.")
    p_probe.add_argument("--file", required=True, type=Path, help="Path to jurisdiction JSON config")
    p_probe.add_argument("--year", type=int, default=None, help="Target year for archived meeting queries")

    p_watch = sub.add_parser("watch", help="Poll active jurisdictions for new agendas and minutes.")
    p_watch.add_argument("--year", type=int, default=None)
    p_watch.add_argument("--limit", type=int, default=25)
    p_watch.add_argument("--jurisdiction", default=None)
    p_watch.add_argument("--min-interval-days", type=int, default=0, help="Skip jurisdictions polled within N days (e.g. 7 for weekly)")
    p_watch.add_argument("--force", action="store_true", help="Ignore --min-interval-days and poll immediately")

    p_work = sub.add_parser("work", help="Fetch document text and extract votes & summaries via local Ollama.")
    p_work.add_argument("--limit", type=int, default=10)
    p_work.add_argument("--jurisdiction", default=None, help="Filter to a single OCD division ID")
    p_work.add_argument("--doc-type", choices=["minutes", "agenda"], default=None, help="Filter by document type")
    p_work.add_argument("--fetch-only", action="store_true", help="Download and cache raw_text without calling Ollama")
    p_work.add_argument("--requeue-skipped", action="store_true", help="Reset previously skipped documents back to pending")
    p_work.add_argument("--pct-per-day", type=float, default=None, help="Process up to P%% of pending docs per run (e.g. 25)")
    p_work.add_argument("--max-per-day", type=int, default=None, help="Hard daily cap on processed docs across runs")

    p_roster = sub.add_parser(
        "sync-rosters",
        help="Automatically sync elected council rosters (Legistar API, saved roster_url, or doc headers).",
    )
    p_roster.add_argument("--jurisdiction", default=None, help="Filter to a single OCD division ID")
    p_roster.add_argument("--roster-url", default=None, help="Official council webpage URL (saved to DB when --jurisdiction is set)")
    p_roster.add_argument("--deactivate-missing", action="store_true", help="Mark departed councilmembers active=0")
    p_roster.add_argument("--dry-run", action="store_true", help="Preview roster changes without writing to SQLite")
    p_roster.add_argument("--max-age-days", type=int, default=90, help="Skip rosters synced within N days (default: 90 = quarterly)")
    p_roster.add_argument("--force", action="store_true", help="Ignore --max-age-days and sync immediately")

    p_exp = sub.add_parser("export", help="Export sharded JSON, directory.json, search_index.json, and agent outputs.")
    p_exp.add_argument("--out-dir", type=Path, default=SETTINGS.public_data_dir)
    p_exp.add_argument("--no-backup", action="store_true")

    p_onboard = sub.add_parser("onboard", help="Scout and onboard a new city, county, or school district.")
    p_onboard.add_argument("--name", help="Jurisdiction name (e.g. 'Longmont City Council')")
    p_onboard.add_argument("--state", default="CO")
    p_onboard.add_argument("--level", default="city", choices=["city", "county", "school_district"])
    p_onboard.add_argument("--portal-url", default=None)
    p_onboard.add_argument("--roster-url", default=None)
    p_onboard.add_argument("--batch-file", type=Path, default=None)
    p_onboard.add_argument("--unclaimed-only", action="store_true")
    p_onboard.add_argument("--run-pipeline", action="store_true")

    p_maint = sub.add_parser("maintain", help="Maintenance tasks (recalculate-impact, backup).")
    p_maint.add_argument("task", choices=["recalculate-impact", "backup"])

    p_all = sub.add_parser("run-all", help="Run cadence-aware roster sync -> watch -> capped work -> export pipeline.")
    p_all.add_argument("--work-limit", type=int, default=10)
    p_all.add_argument("--work-doc-type", choices=["minutes", "agenda"], default="minutes")
    p_all.add_argument("--work-pct-per-day", type=float, default=None, help="Drain up to P%% of pending docs per day (e.g. 25)")
    p_all.add_argument("--work-max-per-day", type=int, default=None, help="Hard daily cap on processed docs (e.g. 8)")
    p_all.add_argument("--watch-interval-days", type=int, default=7, help="Weekly watch interval in days (0 = always)")
    p_all.add_argument("--roster-max-age-days", type=int, default=90, help="Quarterly roster sync interval in days")
    p_all.add_argument("--skip-work", action="store_true")
    p_all.add_argument("--sync-rosters", action="store_true", help="Run quarterly cadence-gated roster sync")
    p_all.add_argument("--force-export", action="store_true", help="Always export even if no new docs/events were created")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = args.db

    if args.command == "init":
        applied = init_db(db_path)
        print(f"[DB] Migrations applied: {applied or 'already up to date'}")
        return 0

    if args.command == "seed":
        res = seed_from_config(args.file, activate_structured=args.activate_structured, db_path=db_path)
        print(f"[SEED] Inserted {res['inserted']}, updated {res['updated']} from {args.file}")
        return 0

    if args.command == "probe":
        results = probe_config(args.file, year=args.year)
        for r in results:
            flag = "PASS" if r["ok"] else "FAIL"
            print(
                f"[{flag}] {r['name']:30s} | {r['adapter_type']:10s} | "
                f"HTTP={str(r['status_code']):4s} | items={r['item_count']:3d} | {r['sample_title']}"
            )
        passed = sum(1 for r in results if r["ok"])
        print(f"Summary: {passed}/{len(results)} endpoints reachable.")
        return 0 if passed == len(results) else 1

    if args.command == "watch":
        stats = _run_watch_with_cadence(
            db_path=db_path,
            year=args.year,
            limit=args.limit,
            jurisdiction_id=args.jurisdiction,
            min_interval_days=args.min_interval_days,
            force=args.force,
        )
        print(f"[WATCH] Done: {stats}")
        return 0

    if args.command == "work":
        stats = _run_work_with_caps(
            db_path=db_path,
            limit=args.limit,
            jurisdiction_id=args.jurisdiction,
            doc_type=args.doc_type,
            fetch_only=args.fetch_only,
            requeue_skipped=args.requeue_skipped,
            pct_per_day=args.pct_per_day,
            max_per_day=args.max_per_day,
        )
        print(f"[WORK] Done: {stats}")
        return 0

    if args.command == "sync-rosters":
        stats = sync_rosters(
            db_path=db_path,
            jurisdiction_id=args.jurisdiction,
            roster_url=args.roster_url,
            deactivate_missing=args.deactivate_missing,
            dry_run=args.dry_run,
            max_age_days=args.max_age_days,
            force=args.force,
        )
        print(f"[ROSTER] Done: {stats}")
        return 0

    if args.command == "export":
        export_all(db_path=db_path, out_dir=args.out_dir, run_backup=not args.no_backup)
        return 0

    if args.command == "onboard":
        if args.batch_file:
            batch = json.loads(args.batch_file.read_text(encoding="utf-8"))
            for item in batch:
                res = onboard_jurisdiction(
                    name=item["name"],
                    state=item.get("state", args.state),
                    level=item.get("level", "city"),
                    portal_url=item.get("portal_url"),
                    roster_url=item.get("roster_url"),
                    activate=not args.unclaimed_only,
                    db_path=db_path,
                )
                print(f"[ONBOARD] {res['name']} -> {res['adapter_type']} ({res['status']})")
        elif args.name:
            res = onboard_jurisdiction(
                name=args.name,
                state=args.state,
                level=args.level,
                portal_url=args.portal_url,
                roster_url=args.roster_url,
                activate=not args.unclaimed_only,
                db_path=db_path,
            )
            print(f"[ONBOARD] {res['name']} -> {res['adapter_type']} ({res['status']})")
        else:
            parser.error("Provide --name or --batch-file")

        if args.run_pipeline:
            run_watcher(db_path=db_path)
            export_all(db_path=db_path)
        return 0

    if args.command == "maintain":
        if args.task == "recalculate-impact":
            count = recalculate_all_metrics(db_path=db_path)
            print(f"[MAINTAIN] Recalculated impact & margin for {count} event(s).")
        elif args.task == "backup":
            dest = backup_database(db_path=db_path)
            print(f"[BACKUP] {dest or 'Set ONEDRIVE_BACKUP_DIR to enable backups.'}")
        return 0

    if args.command == "run-all":
        init_db(db_path)
        changed = False

        if args.sync_rosters:
            r_stats = sync_rosters(
                db_path=db_path,
                deactivate_missing=True,
                max_age_days=args.roster_max_age_days,
            )
            if r_stats.get("added", 0) or r_stats.get("updated", 0) or r_stats.get("deactivated", 0):
                changed = True

        w_stats = _run_watch_with_cadence(
            db_path=db_path,
            year=None,
            limit=25,
            jurisdiction_id=None,
            min_interval_days=args.watch_interval_days,
            force=False,
        )
        if w_stats.get("inserted", 0) > 0:
            changed = True
            if not args.skip_work:
                run_worker(db_path=db_path, limit=25, doc_type=args.work_doc_type, fetch_only=True)

        if not args.skip_work:
            wk_stats = _run_work_with_caps(
                db_path=db_path,
                limit=args.work_limit,
                jurisdiction_id=None,
                doc_type=args.work_doc_type,
                fetch_only=False,
                requeue_skipped=False,
                pct_per_day=args.work_pct_per_day,
                max_per_day=args.work_max_per_day,
            )
            if wk_stats.get("events_created", 0) > 0 or wk_stats.get("votes_created", 0) > 0:
                changed = True

        if changed or args.force_export:
            export_all(db_path=db_path)
        else:
            print("[EXPORT] No new rosters, documents, or votes today; skipping export.", flush=True)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
