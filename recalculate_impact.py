from db import get_connection, init_db


def compute_impact_score(
    event_type: str,
    title: str,
    yes_count: int,
    no_count: int,
    roster_size: int,
) -> tuple[float, int]:
    """
    Deterministic, auditable 0-100 Impact Score:
      1. Legal Weight (10-40 pts): Ordinance/Budget = 35, Resolution/Contract = 25, Procedural = 10
      2. Contestedness (0-40 pts): Scales inversely with vote margin when no_count > 0
      3. Turnout / Full-Body Weight (0-20 pts): Ratio of voting members to full council roster
    """
    etype = (event_type or "").lower()
    t_lower = (title or "").lower()

    if "ordinance" in etype or "budget" in etype or "appropriation" in t_lower or "charter" in t_lower:
        legal_pts = 35.0
    elif "resolution" in etype or "contract" in t_lower or "agreement" in t_lower:
        legal_pts = 25.0
    else:
        legal_pts = 15.0

    total_cast = (yes_count or 0) + (no_count or 0)
    margin = abs((yes_count or 0) - (no_count or 0)) if total_cast > 0 else 0

    if (no_count or 0) == 0 or total_cast == 0:
        contested_pts = 0.0
    else:
        # 1-vote margin -> 40 pts; wider splits scale proportionally
        closeness = max(0.0, 1.0 - ((margin - 1) / max(1, total_cast)))
        contested_pts = round(15.0 + (25.0 * closeness), 1)

    if roster_size > 0 and total_cast > 0:
        turnout_ratio = min(1.0, total_cast / roster_size)
        turnout_pts = round(turnout_ratio * 20.0, 1)
    else:
        turnout_pts = 0.0

    total_score = min(100.0, round(legal_pts + contested_pts + turnout_pts, 1))
    return total_score, margin


def recalculate_all() -> None:
    init_db()
    conn = get_connection()
    try:
        rosters = {
            row["jurisdiction_id"]: row["cnt"]
            for row in conn.execute(
                "SELECT jurisdiction_id, COUNT(*) AS cnt FROM entities WHERE active = 1 GROUP BY jurisdiction_id"
            ).fetchall()
        }

        events = conn.execute("SELECT * FROM events").fetchall()
        updated = 0
        for ev in events:
            r_size = rosters.get(ev["jurisdiction_id"], 0)
            score, margin = compute_impact_score(
                ev["event_type"],
                ev["title"],
                ev["yes_count"] or 0,
                ev["no_count"] or 0,
                r_size,
            )
            conn.execute(
                "UPDATE events SET impact_score = ?, vote_margin = ? WHERE event_id = ?",
                (score, margin, ev["event_id"]),
            )
            updated += 1

        conn.commit()
        print(f"Recalculated auditable impact scores for {updated} event(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    recalculate_all()
