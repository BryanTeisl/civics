"""Idempotently wires CivicPulse v3 Customer Suite into public/index.html & scripts/run_daily.ps1."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_index() -> None:
    p = REPO_ROOT / "public" / "index.html"
    if not p.exists():
        print("[WARN] public/index.html not found.")
        return
    src = p.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_v3_suite.js"></script>'
    if "civicpulse_v3_suite.js" not in src and "</body>" in src:
        p.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
        print("[PATCHED] Wired civicpulse_v3_suite.js into public/index.html")
    else:
        print("[OK] public/index.html already includes civicpulse_v3_suite.js")


def wire_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    if "v3_intelligence" in src:
        print("[OK] scripts/run_daily.ps1 already runs v3_intelligence")
        return
    anchor = "python -m civicpulse.pipeline.export_enhancements --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append"
    if anchor in src:
        hook = (
            anchor
            + "\n    }\n"
            + '    if (Test-Path "civicpulse\\pipeline\\v3_intelligence.py") {\n'
            + "        python -m civicpulse.pipeline.v3_intelligence --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append"
        )
        p.write_text(src.replace(anchor + "\n    }", hook + "\n    }", 1), encoding="utf-8")
        print("[PATCHED] Wired v3_intelligence into scripts/run_daily.ps1")


if __name__ == "__main__":
    wire_index()
    wire_daily()
