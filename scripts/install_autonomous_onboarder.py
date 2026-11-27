"""Wires Autonomous Jurisdiction Onboarding into scripts/run_daily.ps1 & public/index.html."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_run_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        print("[WARN] scripts/run_daily.ps1 not found.")
        return
    src = p.read_text(encoding="utf-8")
    if "autonomous_onboarder" in src:
        print("[OK] scripts/run_daily.ps1 already runs autonomous_onboarder")
        return

    anchor = "python -m civicpulse.cli watch"
    if anchor in src:
        hook = (
            'if (Test-Path "civicpulse\\pipeline\\autonomous_onboarder.py") {\n'
            '        python -m civicpulse.pipeline.autonomous_onboarder --db core_civic.db --public-dir public --max-per-run 2 --no-watch 2>&1 | Tee-Object -FilePath $LogFile -Append\n'
            '    }\n'
            '    ' + anchor
        )
        p.write_text(src.replace(anchor, hook, 1), encoding="utf-8")
        print("[PATCHED] Wired autonomous_onboarder into scripts/run_daily.ps1 right before watch")
    else:
        print("[WARN] Could not find `python -m civicpulse.cli watch` anchor in scripts/run_daily.ps1")


def wire_index() -> None:
    p = REPO_ROOT / "public" / "index.html"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_request_intake.js"></script>'
    if "civicpulse_request_intake.js" not in src and "</body>" in src:
        p.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
        print("[PATCHED] Wired civicpulse_request_intake.js into public/index.html")
    else:
        print("[OK] public/index.html already includes civicpulse_request_intake.js")


if __name__ == "__main__":
    wire_run_daily()
    wire_index()
