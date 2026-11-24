from __future__ import annotations

import re
from typing import Optional

from civicpulse.db import get_connection, init_db

FISCAL_KEYWORDS = re.compile(
    r"\b(budget|tax|bond|appropriation|mill levy|fee|rate|capital|million|grant|debt|sales tax)\b",
    re.IGNORECASE,
)
STRUCTURAL_KEYWORDS = re.compile(
    r"\b(ordinance|zoning|land use|charter|comprehensive plan|annexation|code amendment|housing|transit|water)\b",
    re.IGNORECASE,
)
PROCEDURAL_KEYWORDS = re.compile(
    r"\b(minutes|adjourn|executive session|proclamation|consent calendar|roll call)\b",
    re.IGNORECASE,
)


def compute_impact_score(
    title: str,
    event_type: str = "ordinance",
    yes_count: int = 0,
    no_count: int = 0,
    plain_summary: str = "",
) -> float:
    """Transparent, auditable 0-100 impact score (nonpartisan)."""
    blob = f"{title} {plain_summary}".strip()
    score = 30.0

    etype = (event_type or "").lower()
    if etype == "ordinance":
        score += 20.0
    elif etype == "budget":
        score += 25.0
    elif etype == "resolution":
        score += 10.0
    elif etype in ("motion", "consent"):
        score += 5.0

    if FISCAL_KEYWORDS.search(blob):
        score += 18.0
    if STRUCTURAL_KEYWORDS.search(blob):
        score += 12.0
    if PROCEDURAL_KEYWORDS.search(blob):
        score -= 15.0

    total_votes = yes_count + no_count
    if total_votes > 0 and no_count > 0:
        margin = abs(yes_count - no_count)
        if margin <= 1:
            score += 20.0
        elif margin <= 2:
            score += 12.0
        else:
            score += 6.0

    return round(max(5.0, min(100.0, score)), 1)


def recalculate_all_metrics(db_path: Optional[str] = None) -> int:
    """Recomputes impact_score and vote_margin across all stored events."""
    init_db(db_path)
    conn = get_connection(db_path)
    updated = 0
    try:
        rows = conn.execute(
            "SELECT event_id, title, event_type, yes_count, no_count, plain_summary FROM events"
        ).fetchall()
        for row in rows:
            yes_c = int(row["yes_count"] or 0)
            no_c = int(row["no_count"] or 0)
            margin = abs(yes_c - no_c)
            impact = compute_impact_score(
                title=row["title"] or "",
                event_type=row["event_type"] or "ordinance",
                yes_count=yes_c,
                no_count=no_c,
                plain_summary=row["plain_summary"] or "",
            )
            conn.execute(
                "UPDATE events SET vote_margin = ?, impact_score = ? WHERE event_id = ?",
                (margin, impact, row["event_id"]),
            )
            updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()
