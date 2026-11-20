"""
Auditable, Formula-Driven Metrics Engine.
Computes Vote Impactfulness (event-level) and Legislator Impact (entity-level)
strictly from verifiable roll-call math — zero subjective grading.
"""
from typing import Dict, Tuple

EVENT_TYPE_WEIGHTS = {
    "budget": 1.00,      # Appropriations, tax levies, capital budgets
    "ordinance": 0.90,   # Binding municipal law / zoning / land use code
    "resolution": 0.65,  # Formal policy direction / contracts / intergovernmental agreements
    "motion": 0.50,      # Procedural or directive motions
    "consent": 0.20,     # Routine bundled consent agenda items
}


def compute_vote_impactfulness(
    yes_count: int,
    no_count: int,
    event_type: str = "ordinance",
) -> Tuple[float, int, bool]:
    """
    Returns (impact_score_0_to_100, vote_margin, is_razor_close).

    Formula:
      1. Closeness Weight (0.0 to 1.0):
         1.0 - (|yes - no| / total_cast)
         - Unanimous 7-0 vote -> closeness = 0.0 (low pivotality)
         - Split 4-3 vote     -> closeness = 0.857 (high pivotality)
      2. Legislative Type Weight (0.20 to 1.00):
         Binding ordinances and budgets carry higher weight than consent items.
      3. Combined Impact Score (0 to 100):
         (0.60 * closeness + 0.40 * type_weight) * 100
    """
    total_cast = yes_count + no_count
    margin = abs(yes_count - no_count)
    if total_cast == 0:
        return 0.0, 0, False

    closeness = 1.0 - (margin / total_cast)
    type_weight = EVENT_TYPE_WEIGHTS.get((event_type or "ordinance").lower(), 0.60)
    impact_score = round(((0.60 * closeness) + (0.40 * type_weight)) * 100.0, 1)
    is_razor_close = margin <= 2
    return impact_score, margin, is_razor_close


def is_vote_pivotal(vote_value: str, yes_count: int, no_count: int) -> int:
    """
    Returns 1 if flipping this single official's vote would have changed the outcome
    (e.g., a 'Yes' vote in a 4-3 pass, or a 'No' vote in a 3-4 fail).
    """
    if vote_value == "Yes" and yes_count > no_count and (yes_count - 1) <= (no_count + 1):
        return 1
    if vote_value == "No" and no_count >= yes_count and (no_count - 1) < (yes_count + 1):
        return 1
    return 0


def compute_legislator_metrics(actions: list) -> Dict[str, float]:
    """Aggregates auditable impact metrics for a single official."""
    votes = [a for a in actions if a["action_type"] == "vote"]
    total_votes = len(votes)
    if total_votes == 0:
        return {
            "total_votes": 0,
            "attendance_rate": 0.0,
            "pivotal_votes": 0,
            "pivotal_vote_rate": 0.0,
            "motions_made": 0,
        }

    present_votes = sum(1 for v in votes if v["value"] in ("Yes", "No", "Abstain"))
    pivotal_votes = sum(1 for v in votes if v["is_pivotal"] == 1)
    motions_made = sum(1 for a in actions if a["action_type"] == "motion")

    return {
        "total_votes": total_votes,
        "attendance_rate": round((present_votes / total_votes) * 100.0, 1),
        "pivotal_votes": pivotal_votes,
        "pivotal_vote_rate": round((pivotal_votes / total_votes) * 100.0, 1),
        "motions_made": motions_made,
    }
