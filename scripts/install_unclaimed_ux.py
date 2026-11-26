"""Wires public/assets/civicpulse_unclaimed_ux.js into public/index.html (idempotent).

Usage:
  python scripts/install_unclaimed_ux.py
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_unclaimed_ux(index_path: Path) -> bool:
    if not index_path.exists():
        print(f"[WARN] {index_path} not found.")
        return False
    src = index_path.read_text(encoding="utf-8")
    tag = '  <script type="module" src="assets/civicpulse_unclaimed_ux.js"></script>'
    if "civicpulse_unclaimed_ux.js" in src:
        print("[OK] public/index.html already loads civicpulse_unclaimed_ux.js")
        return True
    assert "</body>" in src, "Missing </body> tag in public/index.html"
    index_path.write_text(src.replace("</body>", f"{tag}\n</body>", 1), encoding="utf-8")
    print("[PATCHED] Wired civicpulse_unclaimed_ux.js into public/index.html")
    return True


if __name__ == "__main__":
    wire_unclaimed_ux(REPO_ROOT / "public" / "index.html")
