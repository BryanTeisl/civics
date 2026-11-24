from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from civicpulse.agents.scout import onboard_jurisdiction
from civicpulse.config import SETTINGS
from civicpulse.db import backup_database, init_db
from civicpulse.maintenance import probe_config, seed_from_config
from civicpulse.pipeline.exporter import export_all
from civicpulse.pipeline.metrics import recalculate_all_metrics
from civicpulse.pipeline.watcher import run_watcher
from civicpulse.pipeline.worker import run_worker


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

    p_work = sub.add_parser("work", help="Fetch document text and extract votes & summaries via local Ollama.")
    p_work.add_argument("--limit", type=int, default=10)
    p_work.add_argument("--jurisdiction", default=None, help="Filter to a single OCD division ID")
    p_work.add_argument("--doc-type", choices=["minutes", "agenda"], default=None, help="Filter by document type")
    p_work.add_argument("--fetch-only", action="store_true", help="Download and cache raw_text without calling Ollama")
    p_work.add_argument("--requeue-skipped", action="store_true", help="Reset previously skipped documents back to pending")

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

    p_all = sub.add_parser("run-all", help="Run full watch -> work -> export pipeline.")
    p_all.add_argument("--work-limit", type=int, default=10)
    p_all.add_argument("--skip-work", action="store_true")

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
        stats = run_watcher(db_path=db_path, year=args.year, limit_per_jur=args.limit, jurisdiction_id=args.jurisdiction)
        print(f"[WATCH] Done: {stats}")
        return 0

    if args.command == "work":
        stats = run_worker(
            db_path=db_path,
            limit=args.limit,
            jurisdiction_id=args.jurisdiction,
            doc_type=args.doc_type,
            fetch_only=args.fetch_only,
            requeue_skipped=args.requeue_skipped,
        )
        print(f"[WORK] Done: {stats}")
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
        run_watcher(db_path=db_path)
        if not args.skip_work:
            run_worker(db_path=db_path, limit=args.work_limit)
        export_all(db_path=db_path)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())