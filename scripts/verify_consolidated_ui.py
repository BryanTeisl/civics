"""Verifies the consolidated single-state CivicPulse frontend (public/index.html + public/js/civicpulse_app.js)."""
from __future__ import annotations

import html.parser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LEGACY_OVERLAY_FILES = [
    "public/assets/civicpulse_ui_bridge.js",
    "public/assets/civicpulse_v3_customer.js",
    "public/assets/civicpulse_v3_1_growth.js",
    "public/assets/civicpulse_v3_2_agenda_preview.js",
    "public/assets/civicpulse_v3_5_home_tabs.js",
    "public/assets/civicpulse_unclaimed_ux.js",
    "public/assets/civicpulse_request_intake.js",
    "public/assets/civicpulse_v4_workspace.js",
]


class _TagBalanceChecker(html.parser.HTMLParser):
    VOID_TAGS = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t not in self.VOID_TAGS:
            self.stack.append(t)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != t:
            self.errors.append(f"Mismatched closing tag </{t}> (stack top: {self.stack[-1] if self.stack else 'EMPTY'})")
        else:
            self.stack.pop()


def main() -> None:
    idx = REPO_ROOT / "public" / "index.html"
    js = REPO_ROOT / "public" / "js" / "civicpulse_app.js"
    assert idx.exists(), "Missing public/index.html"
    assert js.exists(), "Missing public/js/civicpulse_app.js"

    html_src = idx.read_text(encoding="utf-8")
    checker = _TagBalanceChecker()
    checker.feed(html_src)
    assert not checker.errors, f"HTML errors: {checker.errors}"
    assert not checker.stack, f"Unclosed HTML tags: {checker.stack}"

    # Ensure zero legacy overlay scripts remain referenced in index.html
    for legacy in LEGACY_OVERLAY_FILES:
        fname = Path(legacy).name
        assert fname not in html_src, f"Legacy overlay script still referenced in public/index.html: {fname}"

    js_src = js.read_text(encoding="utf-8")
    assert js_src.count("{") == js_src.count("}"), "JS brace mismatch in civicpulse_app.js"
    assert js_src.count("(") == js_src.count(")"), "JS paren mismatch in civicpulse_app.js"

    print("[OK] Consolidated public/index.html HTML tags balanced (0 errors, 0 legacy overlays).")
    print("[OK] Consolidated public/js/civicpulse_app.js syntax balance verified.")


if __name__ == "__main__":
    main()
