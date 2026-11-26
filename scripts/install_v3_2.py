"""Wires CivicPulse v3.2 Agenda Previews into public/index.html & scripts/run_daily.ps1."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_index() -> None:
    p = REPO_ROOT / "public" / "index.html"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_v3_2_agenda_preview.js"></script>'
    if "civicpulse_v3_2_agenda_preview.js" not in src and "</body>" in src:
        p.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
        print("[PATCHED] Wired civicpulse_v3_2_agenda_preview.js into public/index.html")


def wire_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    if "agenda_preview" in src:
        print("[OK] scripts/run_daily.ps1 already runs agenda_preview")
        return
    anchor = "python -m civicpulse.pipeline.export_enhancements --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append"
    if anchor in src:
        hook = (
            anchor
            + "\n    }\n"
            + '    if (Test-Path "civicpulse\\pipeline\\agenda_preview.py") {\n'
            + "        python -m civicpulse.pipeline.agenda_preview --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append"
        )
        p.write_text(src.replace(anchor + "\n    }", hook + "\n    }", 1), encoding="utf-8")
        print("[PATCHED] Wired agenda_preview into scripts/run_daily.ps1")


if __name__ == "__main__":
    wire_index()
    wire_daily()
