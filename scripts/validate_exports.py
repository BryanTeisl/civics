"""Validates exported static JSON files in public/data/ for schema compliance,
canonical naming hygiene, and absence of duplicate/legacy layouts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List

CANONICAL_LEVELS = {"city", "county", "school_district", "special_district", "state", "federal"}
STALE_NAME_PATTERNS = (
    re.compile(r"^ocd-division", re.IGNORECASE),
    re.compile(r"^country_us__.*-.*\.json$"),
)


def validate_data_dir(data_dir: Path, allow_missing_optional: bool = False) -> List[str]:
    errors: List[str] = []
    if not data_dir.exists():
        return [f"Data directory not found: {data_dir}"]

    # 1. Check naming hygiene & legacy layouts
    for f in sorted(data_dir.glob("*.json")):
        for pat in STALE_NAME_PATTERNS:
            if pat.match(f.name):
                errors.append(f"Stale/duplicate filename detected: {f.name}")
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid JSON in {f.name}: {exc}")
            continue

        if isinstance(payload, dict):
            if ("councilors" in payload or "agenda_items" in payload) and "representatives" not in payload:
                errors.append(f"Legacy v1 payload layout in {f.name} (contains councilors/agenda_items)")

    # 2. Validate directory.json if present
    dir_file = data_dir / "directory.json"
    if dir_file.exists():
        data = json.loads(dir_file.read_text(encoding="utf-8"))
        jurs = data.get("jurisdictions", data if isinstance(data, list) else None)
        if not isinstance(jurs, list):
            errors.append("directory.json must contain a 'jurisdictions' list")
        else:
            seen_ids = set()
            for idx, j in enumerate(jurs):
                jid = j.get("ocd_division_id") or j.get("jurisdiction_id")
                if not jid:
                    errors.append(f"directory.json item #{idx} missing ocd_division_id")
                    continue
                if jid in seen_ids:
                    errors.append(f"Duplicate jurisdiction in directory.json: {jid}")
                seen_ids.add(jid)
                lvl = (j.get("level") or "").strip().lower()
                if lvl and lvl not in CANONICAL_LEVELS:
                    errors.append(f"Non-canonical level '{lvl}' for {jid} (expected one of {sorted(CANONICAL_LEVELS)})")
    elif not allow_missing_optional:
        errors.append("Missing required file: directory.json")

    # 3. Validate scoring_methodology.json if present (or required)
    meth_file = data_dir / "scoring_methodology.json"
    if meth_file.exists():
        meth = json.loads(meth_file.read_text(encoding="utf-8"))
        for key in ("formula_version", "effective_date", "formula_hash", "equation", "changelog"):
            if not meth.get(key):
                errors.append(f"scoring_methodology.json missing required field: {key}")
    elif not allow_missing_optional:
        errors.append("Missing required file: scoring_methodology.json")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CivicPulse static JSON exports.")
    parser.add_argument("--data-dir", default="public/data", help="Path to public/data")
    parser.add_argument("--allow-missing-optional", action="store_true")
    args = parser.parse_args()

    errs = validate_data_dir(Path(args.data_dir), allow_missing_optional=args.allow_missing_optional)
    if errs:
        print("[VALIDATE] FAILED with errors:")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print(f"[VALIDATE] PASSED: {args.data_dir} passed all schema and naming hygiene checks.")


if __name__ == "__main__":
    main()
