"""Single-command Clean Baseline Readiness Audit for CivicPulse.

Checks every technical, data-quality, frontend-consistency, and Git-hygiene gate
to confirm the repository is a 100% clean base before tagging/upgrading.

Usage:
  python scripts/baseline_audit.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _status(ok: bool, warn: bool = False) -> str:
    if ok:
        return "PASS"
    return "WARN" if warn else "FAIL"


def run_audit() -> int:
    failures = 0
    print("=== CIVICPULSE CLEAN BASELINE AUDIT ===\n")

    # 1. Check .github/workflows has no broken v1 scripts
    wf_dir = REPO_ROOT / ".github" / "workflows"
    bad_wfs = []
    if wf_dir.exists():
        for wf in wf_dir.glob("*.yml"):
            txt = wf.read_text(encoding="utf-8", errors="ignore")
            for legacy in ("python db.py", "python watcher.py", "python exporter.py", "python enrich_socials.py"):
                if legacy in txt:
                    bad_wfs.append(f"{wf.name} calls '{legacy}'")
    ok_wf = len(bad_wfs) == 0
    if not ok_wf:
        failures += 1
    print(f"[{_status(ok_wf)}] GitHub Actions Workflows: {'clean v2 CI' if ok_wf else '; '.join(bad_wfs)}")

    # 2. Check Git does not track core_civic.db or __pycache__
    try:
        tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True).splitlines()
        bad_tracked = [f for f in tracked if f.endswith("core_civic.db") or "__pycache__/" in f]
        ok_git = len(bad_tracked) == 0
        if not ok_git:
            failures += 1
        print(f"[{_status(ok_git)}] Git Tracking Hygiene: {'no DB/pycache tracked' if ok_git else f'tracked: {bad_tracked[:4]}'}")
    except Exception:
        print("[WARN] Git Tracking Hygiene: could not run git ls-files")

    # 3. Check public/data has zero stale/duplicate/archived JSONs & canonical levels
    data_dir = REPO_ROOT / "public" / "data"
    stale_files = []
    level_issues = []
    if data_dir.exists():
        for jf in data_dir.glob("*.json"):
            if jf.name.startswith("ocd-division") or jf.name == "country_us__state_ca__place_san_jose.json":
                stale_files.append(jf.name)
        dir_f = data_dir / "directory.json"
        if dir_f.exists():
            d = json.loads(dir_f.read_text(encoding="utf-8"))
            jurs = d.get("jurisdictions", d if isinstance(d, list) else [])
            for j in jurs:
                if (j.get("status") or "").lower() == "archived":
                    level_issues.append(f"archived leaked: {j.get('name')}")
                lvl = (j.get("level") or "").lower()
                if lvl not in ("city", "county", "school_district", "special_district", "state", "federal"):
                    level_issues.append(f"non-canonical level '{lvl}' on {j.get('name')}")
    ok_data = len(stale_files) == 0 and len(level_issues) == 0
    if not ok_data:
        failures += 1
    print(f"[{_status(ok_data)}] Export Naming & Scope: {'clean Colorado v2 schema' if ok_data else f'stale={stale_files}, issues={level_issues[:3]}'}")

    # 4. Check frontend level filter alignment (city vs municipality)
    idx_f = REPO_ROOT / "public" / "index.html"
    app_js = REPO_ROOT / "public" / "js" / "app.js"
    if idx_f.exists() and app_js.exists():
        idx_txt = idx_f.read_text(encoding="utf-8", errors="ignore")
        app_txt = app_js.read_text(encoding="utf-8", errors="ignore")
        has_city_pill = 'data-level="city"' in idx_txt and 'data-level="municipality"' not in idx_txt
        if not has_city_pill:
            failures += 1
        print(
            f"[{_status(has_city_pill)}] Frontend City Filter Pill: "
            + ("index.html uses canonical data-level='city'" if has_city_pill else "index.html still has stale data-level='municipality'")
        )

    # 5. Check required public artifacts exist
    required = [
        "public/data/directory.json",
        "public/data/scoring_methodology.json",
        "public/data/upcoming_meetings.json",
        "public/data/search_chunks/manifest.json",
        "public/data/feeds_index.json",
        "public/docs/civicpulse_impact_formula.md",
        "public/docs/civicpulse_impact_formula.json",
        "public/feeds/all.xml",
    ]
    missing = [r for r in required if not (REPO_ROOT / r).exists()]
    ok_art = len(missing) == 0
    if not ok_art:
        failures += 1
    print(f"[{_status(ok_art)}] Required Static Artifacts: {'all 8 present' if ok_art else f'missing {missing}'}")

    # 6. Database quality & contact coverage summary
    db_file = REPO_ROOT / "core_civic.db"
    if db_file.exists():
        c = sqlite3.connect(db_file)
        total_ev = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        gen_ev = c.execute("SELECT COUNT(*) FROM events WHERE LOWER(COALESCE(topic,'')) = 'general'").fetchone()[0]
        total_reps = c.execute("SELECT COUNT(*) FROM entities WHERE COALESCE(active,1)=1").fetchone()[0]
        cols = {r[1] for r in c.execute("PRAGMA table_info(entities)").fetchall()}
        email_reps = (
            c.execute("SELECT COUNT(*) FROM entities WHERE COALESCE(active,1)=1 AND email IS NOT NULL AND TRIM(email)!=''").fetchone()[0]
            if "email" in cols
            else 0
        )
        ev_cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
        qa_counts = (
            dict(c.execute("SELECT COALESCE(qa_status,'verified'), COUNT(*) FROM events GROUP BY qa_status").fetchall())
            if "qa_status" in ev_cols
            else {}
        )
        c.close()
        gen_pct = round((gen_ev / total_ev) * 100, 1) if total_ev else 0.0
        email_pct = round((email_reps / total_reps) * 100, 1) if total_reps else 0.0
        print(f"[INFO] DB Events: {total_ev} total | 'General' topic: {gen_ev} ({gen_pct}%) | QA: {qa_counts}")
        print(f"[INFO] Active Representatives: {total_reps} total | With official email: {email_reps} ({email_pct}%)")

    print("\n=== RESULT:", "CLEAN BASELINE READY ===" if failures == 0 else f"{failures} FAILURE(S) TO FIX ===")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_audit())
