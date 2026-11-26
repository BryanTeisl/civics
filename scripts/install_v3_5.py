"""Wires CivicPulse v3.5 Tabbed Home UX & QA Trust Calibration (idempotent)."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_index() -> None:
    p = REPO_ROOT / "public" / "index.html"
    if not p.exists():
        print("[WARN] public/index.html not found.")
        return
    src = p.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_v3_5_home_tabs.js"></script>'
    if "civicpulse_v3_5_home_tabs.js" in src:
        print("[OK] public/index.html already includes civicpulse_v3_5_home_tabs.js")
        return
    if "</body>" in src:
        p.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
        print("[PATCHED] Wired civicpulse_v3_5_home_tabs.js into public/index.html")


def wire_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    if "calibrate_qa_trust.py" in src:
        print("[OK] scripts/run_daily.ps1 already runs calibrate_qa_trust.py")
        return
    anchor = "python scripts\\normalize_db.py --db core_civic.db --apply"
    if anchor in src:
        replacement = (
            anchor
            + "\n    if (Test-Path \"scripts\\calibrate_qa_trust.py\") {\n"
            + "        python scripts\\calibrate_qa_trust.py --db core_civic.db --apply 2>&1 | Tee-Object -FilePath $LogFile -Append\n"
            + "    }"
        )
        p.write_text(src.replace(anchor, replacement, 1), encoding="utf-8")
        print("[PATCHED] Wired calibrate_qa_trust.py into scripts/run_daily.ps1")


if __name__ == "__main__":
    wire_index()
    wire_daily()
