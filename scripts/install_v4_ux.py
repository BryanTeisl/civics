"""Wires CivicPulse v4.0 Representative Bios & Scoped Workspace UX."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_run_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        print("[WARN] scripts/run_daily.ps1 not found.")
        return
    src = p.read_text(encoding="utf-8")
    if "civicpulse.pipeline.rep_bios" in src:
        print("[OK] scripts/run_daily.ps1 already runs rep_bios")
        return

    anchor = "python -m civicpulse.pipeline.export_enhancements"
    if anchor in src:
        hook = (
            'if (Test-Path "civicpulse\\pipeline\\rep_bios.py") {\n'
            '        python -m civicpulse.pipeline.rep_bios --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append\n'
            '    }\n'
            '    ' + anchor
        )
        p.write_text(src.replace(anchor, hook, 1), encoding="utf-8")
        print("[PATCHED] Wired rep_bios into scripts/run_daily.ps1")
    else:
        print("[WARN] Could not find export_enhancements anchor in scripts/run_daily.ps1")


def wire_index() -> None:
    p = REPO_ROOT / "public" / "index.html"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_v4_workspace.js"></script>'
    if "civicpulse_v4_workspace.js" not in src and "</body>" in src:
        p.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
        print("[PATCHED] Wired civicpulse_v4_workspace.js into public/index.html")
    else:
        print("[OK] public/index.html already includes civicpulse_v4_workspace.js")


if __name__ == "__main__":
    wire_run_daily()
    wire_index()
