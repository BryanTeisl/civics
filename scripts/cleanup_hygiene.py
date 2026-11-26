"""CivicPulse Pre-Expansion Cleanup & Hygiene Tool (scripts/cleanup_hygiene.py).

Performs five safe, idempotent cleanups before expanding further:
  1. Marks historical past agendas (`meeting_date < today`) as `skipped` while leaving
     upcoming agendas (`meeting_date >= today`) intact for Upcoming Meetings & Previews.
  2. Deduplicates same-day API (`doc_id IS NULL`) vs. PDF (`doc_id IS NOT NULL`) duplicate
     events (e.g., Denver Section 18-91), keeping the structured API record.
  3. Stops exporting ~500 empty `unclaimed` per-jurisdiction JSON files in `public/data/`
     (patches `exporter.py` / `export_enhancements.py` and prunes existing empty unclaimed
     `country_us__*.json` shells while preserving all `active` jurisdiction JSONs).
  4. Fixes the ambiguous topic fixture in `tests/test_v3_2_agenda_preview.py`.
  5. Fixes the DOM injection order race between v3.1 & v3.2 scripts and repairs any
     legacy `$5` mailto templates on `$15` / `$50` support buttons in `public/index.html`.

Usage:
  # Preview changes (dry-run, no modifications)
  python scripts/cleanup_hygiene.py --db core_civic.db

  # Apply all database, code, and static-file cleanups
  python scripts/cleanup_hygiene.py --db core_civic.db --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent

SECTION_OR_ORD_RE = re.compile(
    r"\b(?:section|sec\.?|ordinance|ord\.?|resolution|res\.?|bill|no\.?)\s*#?\s*([0-9]{1,4}[-–][0-9A-Za-z]+)\b",
    re.IGNORECASE,
)

STOP_WORDS = {
    "ordinance", "resolution", "amending", "approving", "relating", "concerning",
    "section", "city", "council", "denver", "revised", "municipal", "code", "for",
    "the", "and", "with", "that", "from", "into", "this",
}


def _title_tokens(title: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]{4,}", (title or "").lower())
    return {w for w in words if w not in STOP_WORDS}


def _extract_code(title: str) -> str:
    m = SECTION_OR_ORD_RE.search(title or "")
    return m.group(1).lower() if m else ""


def skip_past_agendas(conn: sqlite3.Connection, today_iso: str, apply: bool = False) -> int:
    count = conn.execute(
        """
        SELECT COUNT(*) FROM documents
        WHERE LOWER(doc_type) = 'agenda'
          AND status = 'pending'
          AND meeting_date IS NOT NULL
          AND meeting_date < ?
        """,
        (today_iso,),
    ).fetchone()[0]
    if apply and count > 0:
        conn.execute(
            """
            UPDATE documents
            SET status = 'skipped'
            WHERE LOWER(doc_type) = 'agenda'
              AND status = 'pending'
              AND meeting_date IS NOT NULL
              AND meeting_date < ?
            """,
            (today_iso,),
        )
    return int(count)


def dedupe_api_vs_pdf_events(conn: sqlite3.Connection, apply: bool = False) -> List[Dict[str, Any]]:
    """Finds same-day duplicates where both a structured API row (doc_id IS NULL)
    and a PDF-extracted row (doc_id IS NOT NULL) exist for the same measure."""
    rows = conn.execute(
        """
        SELECT event_id, jurisdiction_id, meeting_date, title, doc_id
        FROM events
        WHERE meeting_date IS NOT NULL
        ORDER BY jurisdiction_id, meeting_date
        """
    ).fetchall()

    by_bucket: Dict[tuple, List[tuple]] = {}
    for r in rows:
        by_bucket.setdefault((r[1], r[2]), []).append(r)

    dupes_to_remove: List[Dict[str, Any]] = []
    for (jid, dt), items in by_bucket.items():
        api_items = [x for x in items if x[4] is None]
        pdf_items = [x for x in items if x[4] is not None]
        if not api_items or not pdf_items:
            continue

        for pdf_row in pdf_items:
            pdf_id, _, _, pdf_title, pdf_doc = pdf_row
            pdf_code = _extract_code(pdf_title)
            pdf_toks = _title_tokens(pdf_title)

            matched_api = None
            for api_row in api_items:
                api_id, _, _, api_title, _ = api_row
                api_code = _extract_code(api_title)
                api_toks = _title_tokens(api_title)

                code_match = bool(pdf_code and api_code and pdf_code == api_code)
                overlap = (
                    len(pdf_toks & api_toks) / max(1, min(len(pdf_toks), len(api_toks)))
                    if (pdf_toks and api_toks)
                    else 0.0
                )
                if code_match or overlap >= 0.72:
                    matched_api = api_row
                    break

            if matched_api:
                dupes_to_remove.append({
                    "removed_event_id": pdf_id,
                    "removed_doc_id": pdf_doc,
                    "removed_title": pdf_title,
                    "kept_event_id": matched_api[0],
                    "kept_title": matched_api[3],
                    "jurisdiction_id": jid,
                    "meeting_date": dt,
                })

    if apply and dupes_to_remove:
        for d in dupes_to_remove:
            conn.execute("DELETE FROM entity_actions WHERE event_id = ?", (d["removed_event_id"],))
            conn.execute("DELETE FROM events WHERE event_id = ?", (d["removed_event_id"],))

    return dupes_to_remove


def prune_unclaimed_jurisdiction_jsons(
    db_path: Path,
    data_dir: Path,
    apply: bool = False,
) -> Dict[str, int]:
    """Removes empty per-jurisdiction JSON shells for `unclaimed` jurisdictions while
    preserving every `active` jurisdiction file and all non-jurisdiction JSON payloads."""
    if not data_dir.exists() or not db_path.exists():
        return {"pruned": 0, "kept_active": 0}

    conn = sqlite3.connect(db_path)
    try:
        active_ids = {
            r[0]
            for r in conn.execute(
                "SELECT ocd_division_id FROM jurisdictions WHERE LOWER(COALESCE(status, 'active')) = 'active'"
            ).fetchall()
        }
        unclaimed_ids = {
            r[0]
            for r in conn.execute(
                "SELECT ocd_division_id FROM jurisdictions WHERE LOWER(COALESCE(status, '')) = 'unclaimed'"
            ).fetchall()
        }
    finally:
        conn.close()

    def slugify(div_id: str) -> str:
        return (
            div_id.replace("ocd-division/", "")
            .replace("/", "__")
            .replace(":", "_")
            .replace("-", "_")
        )

    active_files = {f"{slugify(jid)}.json" for jid in active_ids}
    unclaimed_files = {f"{slugify(jid)}.json" for jid in unclaimed_ids}

    pruned = 0
    kept_active = 0
    for fp in sorted(data_dir.glob("country_us__*.json")):
        if fp.name in active_files:
            kept_active += 1
        elif fp.name in unclaimed_files:
            pruned += 1
            if apply:
                fp.unlink()

    return {"pruned": pruned, "kept_active": kept_active}


def patch_exporter_active_only(repo_root: Path, apply: bool = False) -> List[str]:
    """Updates exporter.py & export_enhancements.py so per-jurisdiction JSON files
    are only written for active jurisdictions (unclaimed rows still live in directory.json)."""
    notes: List[str] = []

    # 1. civicpulse/pipeline/exporter.py
    exp_p = repo_root / "civicpulse" / "pipeline" / "exporter.py"
    if exp_p.exists():
        src = exp_p.read_text(encoding="utf-8")
        marker = "# [CLEANUP: active-only per-jurisdiction files]"
        if marker not in src:
            # Look for loop writing per-jurisdiction JSON
            old_snippet = 'out_path = data_dir / f"{slug}.json"'
            if old_snippet in src:
                patched = src.replace(
                    old_snippet,
                    f'{marker}\n        if str(j.get("status") or "active").lower() != "active":\n            continue\n        {old_snippet}',
                    1,
                )
                if apply:
                    exp_p.write_text(patched, encoding="utf-8")
                notes.append("exporter.py: guarded per-jurisdiction JSON write to active jurisdictions only")

    # 2. civicpulse/pipeline/export_enhancements.py
    enh_p = repo_root / "civicpulse" / "pipeline" / "export_enhancements.py"
    if enh_p.exists():
        src = enh_p.read_text(encoding="utf-8")
        old_q = "SELECT ocd_division_id FROM jurisdictions WHERE COALESCE(status, 'active') != 'archived'"
        new_q = "SELECT ocd_division_id FROM jurisdictions WHERE LOWER(COALESCE(status, 'active')) = 'active'"
        if old_q in src:
            if apply:
                enh_p.write_text(src.replace(old_q, new_q, 1), encoding="utf-8")
            notes.append("export_enhancements.py: limited per-jurisdiction JSON sync to active jurisdictions")

    return notes


def fix_v32_test_and_dom_order(repo_root: Path, apply: bool = False) -> List[str]:
    """Fixes the 1 ambiguous test fixture in test_v3_2_agenda_preview.py, enforces deterministic
    DOM order between v3.1 & v3.2 sections, and fixes legacy $5 mailto strings on $15/$50 buttons."""
    notes: List[str] = []

    # 1. Fix test_v3_2_agenda_preview.py
    t32 = repo_root / "tests" / "test_v3_2_agenda_preview.py"
    if t32.exists():
        src = t32.read_text(encoding="utf-8")
        if "Residential Short-Term Rental Licensing Rules" in src:
            new_src = src.replace(
                "Item 1: Ordinance No. 2026-44 Amending Residential Short-Term Rental Licensing Rules",
                "Item 1: Ordinance No. 2026-44 Amending Liquor and Business Licensing Rules",
            ).replace(
                'assert "Short-Term Rental" in items[0]["title"]',
                'assert "Business Licensing" in items[0]["title"]',
            )
            if apply:
                t32.write_text(new_src, encoding="utf-8")
            notes.append("tests/test_v3_2_agenda_preview.py: fixed topic classification test input")

    # 2. Fix deterministic DOM mount order between v3.1 (P&Z Early Warning) & v3.2 (Agenda Previews)
    js31 = repo_root / "public" / "assets" / "civicpulse_v3_1_growth.js"
    if js31.exists():
        src = js31.read_text(encoding="utf-8")
        old_ins = 'anchor.insertAdjacentElement("afterend", sec);'
        new_ins = '(document.getElementById("v32AgendaPreviewsSection") || anchor).insertAdjacentElement("afterend", sec);'
        if old_ins in src and "v32AgendaPreviewsSection" not in src:
            if apply:
                js31.write_text(src.replace(old_ins, new_ins, 1), encoding="utf-8")
            notes.append("public/assets/civicpulse_v3_1_growth.js: anchored P&Z Early Warning deterministically after Agenda Previews")

    # 3. Fix legacy $5 mailto subject/body on $15 / $50 support buttons in public/index.html
    idx_p = repo_root / "public" / "index.html"
    if idx_p.exists():
        src = idx_p.read_text(encoding="utf-8")
        updated = src
        # Repair buttons where visible text says $15 or $50 but preceding href still encodes $5
        updated = re.sub(
            r'(href="mailto:[^"]*?)(%245|\$5)([^"]*?"[^>]*>[^<]*\$15)',
            r"\g<1>%2415\g<3>",
            updated,
        )
        updated = re.sub(
            r'(href="mailto:[^"]*?)(%245|\$5)([^"]*?"[^>]*>[^<]*\$50)',
            r"\g<1>%2450\g<3>",
            updated,
        )
        if updated != src:
            if apply:
                idx_p.write_text(updated, encoding="utf-8")
            notes.append("public/index.html: repaired legacy $5 mailto links on $15/$50 support buttons")

    return notes


def run_cleanup(db_path: Path, repo_root: Path = REPO_ROOT, apply: bool = False) -> Dict[str, Any]:
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report: Dict[str, Any] = {
        "mode": "APPLY" if apply else "DRY_RUN",
        "as_of": today_iso,
    }

    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            report["past_agendas_skipped"] = skip_past_agendas(conn, today_iso, apply=apply)
            dupes = dedupe_api_vs_pdf_events(conn, apply=apply)
            report["api_vs_pdf_dupes_removed"] = len(dupes)
            report["api_vs_pdf_dupe_details"] = dupes
            if apply:
                conn.commit()
        finally:
            conn.close()

    report["unclaimed_json_prune"] = prune_unclaimed_jurisdiction_jsons(
        db_path, repo_root / "public" / "data", apply=apply
    )
    report["exporter_patches"] = patch_exporter_active_only(repo_root, apply=apply)
    report["frontend_and_test_patches"] = fix_v32_test_and_dom_order(repo_root, apply=apply)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CivicPulse pre-expansion cleanup & hygiene.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--apply", action="store_true", help="Apply all cleanups (default is dry-run)")
    args = parser.parse_args()
    res = run_cleanup(Path(args.db), REPO_ROOT, apply=args.apply)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
