"""Upgrades CivicPulse topic classification to whole-word + title-weighted matching,
re-normalizes existing events, and activates the v3 Customer Suite end-to-end.

Usage:
  python scripts/upgrade_to_v3_0_1.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def upgrade_normalize_topic_matcher() -> bool:
    norm_p = REPO_ROOT / "civicpulse" / "pipeline" / "normalize.py"
    if not norm_p.exists():
        print("[WARN] civicpulse/pipeline/normalize.py not found.")
        return False

    src = norm_p.read_text(encoding="utf-8")
    if "COMPILED_TOPIC_RULES" in src:
        print("[OK] normalize.py already uses word-boundary COMPILED_TOPIC_RULES.")
        return True

    src = src.replace(
        '"memorandum of understanding", "mou", "lease", "purchase order",',
        '"memorandum of understanding", "mou", "lease", "leases", "purchase order", "master purchase order",',
    )
    src = src.replace(
        '"sustainability", "recycling", "compost", "tree", "wildlife", "oil and gas",',
        '"sustainability", "recycling", "compost", "plastic", "wildlife", "oil and gas",',
    )
    src = src.replace(
        '"election", "ballot", "charter", "appointment", "board member",',
        '"election", "ballot", "charter", "appointment", "board member", "reauthorization of boards", "boards and commissions",',
    )

    old_fn = """def classify_topic(
    title: str,
    summary: str = "",
    existing_topic: Optional[str] = None,
) -> str:
    \"\"\"Assigns a specific, browsable topic label (replaces vague 'General' & redundant bill types).\"\"\"
    existing = (existing_topic or "").strip()
    if existing and existing.lower() not in VAGUE_TOPICS:
        # Check if existing already matches one of our canonical labels
        for canonical, _ in TOPIC_RULES:
            if existing.lower() == canonical.lower():
                return canonical

    blob = f" {title or ''} {summary or ''} {existing} ".lower()
    best_topic = "General"
    best_hits = 0
    for topic_name, keywords in TOPIC_RULES:
        hits = sum(1 for kw in keywords if kw in blob)
        if hits > best_hits:
            best_hits = hits
            best_topic = topic_name
    return best_topic"""

    new_fn = """COMPILED_TOPIC_RULES: List[Tuple[str, List[re.Pattern]]] = [
    (
        topic_name,
        [re.compile(r"\\b" + re.escape(kw.strip()) + r"\\b", re.IGNORECASE) for kw in keywords if kw.strip()],
    )
    for topic_name, keywords in TOPIC_RULES
]


def classify_topic(
    title: str,
    summary: str = "",
    existing_topic: Optional[str] = None,
) -> str:
    \"\"\"Assigns a specific, browsable topic label using whole-word boundaries & 2x title weighting.\"\"\"
    existing = (existing_topic or "").strip()
    t_str = title or ""
    s_str = f"{summary or ''} {existing if existing.lower() not in VAGUE_TOPICS else ''}"
    best_topic = "General"
    best_score = 0
    for topic_name, patterns in COMPILED_TOPIC_RULES:
        score = 0
        for pat in patterns:
            if pat.search(t_str):
                score += 2
            elif pat.search(s_str):
                score += 1
        if score > best_score:
            best_score = score
            best_topic = topic_name
    return best_topic"""

    assert old_fn in src, "Could not locate classify_topic block in normalize.py"
    norm_p.write_text(src.replace(old_fn, new_fn, 1), encoding="utf-8")
    print("[PATCHED] Upgraded classify_topic() in civicpulse/pipeline/normalize.py to word-boundary + title-weighted matching.")
    return True


def run_step(cmd: list[str]) -> None:
    print(f"\n>>> Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def main() -> None:
    upgrade_normalize_topic_matcher()

    if (REPO_ROOT / "scripts" / "install_v3.py").exists():
        run_step([sys.executable, "scripts/install_v3.py"])

    if (REPO_ROOT / "core_civic.db").exists():
        run_step([sys.executable, "scripts/normalize_db.py", "--db", "core_civic.db", "--apply"])
        if (REPO_ROOT / "scripts" / "polish_clean_baseline.py").exists():
            run_step([sys.executable, "scripts/polish_clean_baseline.py"])
        run_step([sys.executable, "-m", "civicpulse.cli", "export"])
        run_step([sys.executable, "-m", "civicpulse.pipeline.export_enhancements", "--db", "core_civic.db", "--public-dir", "public"])
        if (REPO_ROOT / "civicpulse" / "pipeline" / "v3_intelligence.py").exists():
            run_step([sys.executable, "-m", "civicpulse.pipeline.v3_intelligence", "--db", "core_civic.db", "--public-dir", "public"])

    run_step([sys.executable, "scripts/validate_exports.py", "--data-dir", "public/data"])
    run_step([sys.executable, "-m", "pytest", "-v"])


if __name__ == "__main__":
    main()
