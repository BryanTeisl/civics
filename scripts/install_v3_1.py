"""Wires CivicPulse v3.1 Planning & Zoning Early Warning into public/index.html & scripts/run_daily.ps1."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_index() -> None:
    p = REPO_ROOT / "public" / "index.html"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_v3_1_growth.js"></script>'
    if "civicpulse_v3_1_growth.js" not in src and "</body>" in src:
        p.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
        print("[PATCHED] Wired civicpulse_v3_1_growth.js into public/index.html")


def wire_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    if "early_warning" in src:
        print("[OK] scripts/run_daily.ps1 already runs early_warning")
        return
    anchor = "python -m civicpulse.pipeline.export_enhancements --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append"
    if anchor in src:
        hook = (
            anchor
            + "\n    }\n"
            + '    if (Test-Path "civicpulse\\pipeline\\early_warning.py") {\n'
            + "        python -m civicpulse.pipeline.early_warning --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append"
        )
        p.write_text(src.replace(anchor + "\n    }", hook + "\n    }", 1), encoding="utf-8")
        print("[PATCHED] Wired early_warning into scripts/run_daily.ps1")


if __name__ == "__main__":
    wire_index()
    wire_daily()
