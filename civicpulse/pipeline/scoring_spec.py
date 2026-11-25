"""Versioned, auditable Vote Impactfulness (0-100) scoring specification.

This module is the single source of truth for CivicPulse's Impact Score.
Any change to weights, thresholds, or components updates the deterministic
formula hash, allowing the UI and exported docs to alert users whenever
the methodology changes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

FORMULA_VERSION = "2.0.0"
FORMULA_EFFECTIVE_DATE = "2026-11-25"

LEGAL_WEIGHT_MAP: Dict[str, int] = {
    "budget": 40,
    "appropriation": 40,
    "charter": 40,
    "zoning": 38,
    "ordinance": 35,
    "resolution": 25,
    "contract": 25,
    "motion": 20,
    "appointment": 15,
    "consent": 12,
    "proclamation": 10,
    "minutes": 10,
}
DEFAULT_LEGAL_WEIGHT = 20

MAX_CONTESTEDNESS_POINTS = 40.0
MAX_TURNOUT_POINTS = 20.0

FORMULA_CHANGELOG: List[Dict[str, Any]] = [
    {
        "version": "2.0.0",
        "date": "2026-11-25",
        "summary": (
            "Published full plain-English & machine-readable formula specification; "
            "fixed committee attendance/turnout denominator so committee votes are "
            "scored against committee size rather than full-council size; added "
            "deterministic formula hash for change detection."
        ),
        "breaking": False,
    },
    {
        "version": "1.1.0",
        "date": "2026-11-23",
        "summary": (
            "Standardized 3-factor deterministic model: Legal Weight (10-40 pts) + "
            "Contestedness / Vote Margin (0-40 pts) + Body Turnout (0-20 pts)."
        ),
        "breaking": True,
    },
    {
        "version": "1.0.0",
        "date": "2026-11-21",
        "summary": "Initial prototype heuristic combining event type and yes/no closeness.",
        "breaking": False,
    },
]


@dataclass(frozen=True)
class ImpactBreakdown:
    score: float
    legal_weight: float
    contestedness: float
    turnout: float
    votes_cast: int
    expected_body_size: int
    body_type: str
    formula_version: str
    formula_hash: str
    plain_english: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_formula_parameters() -> Dict[str, Any]:
    """Returns canonical scoring constants used for hashing and export."""
    return {
        "formula_version": FORMULA_VERSION,
        "effective_date": FORMULA_EFFECTIVE_DATE,
        "scale_min": 0,
        "scale_max": 100,
        "legal_weight_map": LEGAL_WEIGHT_MAP,
        "default_legal_weight": DEFAULT_LEGAL_WEIGHT,
        "max_contestedness_points": MAX_CONTESTEDNESS_POINTS,
        "max_turnout_points": MAX_TURNOUT_POINTS,
        "pivotal_vote_rule": "Winning-side vote where |yes_count - no_count| <= 1 (or <= 2 on supermajority/split decisions).",
    }


def compute_formula_hash() -> str:
    """Deterministic short SHA-256 fingerprint of the active formula parameters."""
    canonical = json.dumps(get_formula_parameters(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def infer_legal_weight(event_type: str, title: str = "", summary: str = "") -> float:
    """Determines the 10-40 pt legal binding weight strictly from measure type & legal keywords."""
    et = (event_type or "").strip().lower()
    if et in LEGAL_WEIGHT_MAP:
        return float(LEGAL_WEIGHT_MAP[et])

    blob = f"{et} {title} {summary}".lower()
    if any(k in blob for k in ("budget", "appropriation", "mill levy", "tax rate", "capital improvement")):
        return float(LEGAL_WEIGHT_MAP["budget"])
    if any(k in blob for k in ("rezoning", "rezone", "zoning", "land use code", "annexation")):
        return float(LEGAL_WEIGHT_MAP["zoning"])
    if "ordinance" in blob or "municipal code" in blob:
        return float(LEGAL_WEIGHT_MAP["ordinance"])
    if "resolution" in blob or "contract" in blob or "iga" in blob or "intergovernmental" in blob:
        return float(LEGAL_WEIGHT_MAP["resolution"])
    if "consent" in blob:
        return float(LEGAL_WEIGHT_MAP["consent"])
    if "proclamation" in blob or "minutes" in blob:
        return float(LEGAL_WEIGHT_MAP["minutes"])
    return float(DEFAULT_LEGAL_WEIGHT)


def calculate_auditable_impact(
    event_type: str,
    yes_count: int,
    no_count: int,
    abstain_count: int = 0,
    expected_body_size: Optional[int] = None,
    body_type: str = "full_body",
    title: str = "",
    summary: str = "",
) -> ImpactBreakdown:
    """Computes the deterministic 0-100 Vote Impactfulness score with full audit breakdown.

    Committee-aware rule:
      - If body_type == 'committee', turnout is scored against the committee's own
        member count (or votes_cast if committee size isn't recorded) and scaled by
        a 0.50 committee weight cap (max 10 turnout pts) so a 4-member committee vote
        isn't penalized for having 4/13 members while still scoring below a full-council roll call.
    """
    yes_c = max(0, int(yes_count or 0))
    no_c = max(0, int(no_count or 0))
    abs_c = max(0, int(abstain_count or 0))
    deciding_votes = yes_c + no_c
    votes_cast = deciding_votes + abs_c

    legal_weight = infer_legal_weight(event_type, title, summary)

    # Component 2: Contestedness (0 to 40 pts)
    if deciding_votes == 0:
        contestedness = 0.0
        margin_desc = "No roll-call split recorded (+0 pts)"
    else:
        margin_ratio = abs(yes_c - no_c) / deciding_votes  # 1.0 = unanimous, 0.0 = tie
        contestedness = round((1.0 - margin_ratio) * MAX_CONTESTEDNESS_POINTS, 1)
        if no_c == 0 or yes_c == 0:
            margin_desc = f"Unanimous ({yes_c}-{no_c}, +0.0 split pts)"
        else:
            margin_desc = f"Split vote ({yes_c}-{no_c}, +{contestedness} split pts)"

    # Component 3: Body Turnout (0 to 20 pts, committee-aware)
    if expected_body_size and expected_body_size > 0:
        denom = max(expected_body_size, votes_cast)
    else:
        denom = votes_cast

    if denom == 0 or votes_cast == 0:
        turnout = 0.0
        turnout_desc = "Turnout unavailable (+0.0 pts)"
    else:
        ratio = min(1.0, votes_cast / denom)
        cap = MAX_TURNOUT_POINTS * 0.5 if body_type == "committee" else MAX_TURNOUT_POINTS
        turnout = round(ratio * cap, 1)
        if body_type == "committee":
            turnout_desc = f"Committee turnout {votes_cast}/{denom} (+{turnout} pts, committee cap 10)"
        else:
            turnout_desc = f"Full-body turnout {votes_cast}/{denom} (+{turnout} pts)"

    total = round(min(100.0, max(0.0, legal_weight + contestedness + turnout)), 1)
    f_hash = compute_formula_hash()

    plain = (
        f"Legal weight: {legal_weight:g} pts ({event_type or 'measure'}) | "
        f"{margin_desc} | {turnout_desc} = {total:g}/100 (Formula v{FORMULA_VERSION})"
    )

    return ImpactBreakdown(
        score=total,
        legal_weight=legal_weight,
        contestedness=contestedness,
        turnout=turnout,
        votes_cast=votes_cast,
        expected_body_size=denom,
        body_type=body_type,
        formula_version=FORMULA_VERSION,
        formula_hash=f_hash,
        plain_english=plain,
    )


def build_scoring_methodology_payload() -> Dict[str, Any]:
    """Builds the JSON payload exported to public/data/scoring_methodology.json."""
    params = get_formula_parameters()
    f_hash = compute_formula_hash()
    examples = [
        {
            "label": "Unanimous Routine Consent Item (Full Council 7-0)",
            "inputs": {"event_type": "consent", "yes_count": 7, "no_count": 0, "expected_body_size": 7},
            "result": calculate_auditable_impact("consent", 7, 0, expected_body_size=7).to_dict(),
        },
        {
            "label": "Unanimous City Ordinance (Full Council 7-0)",
            "inputs": {"event_type": "ordinance", "yes_count": 7, "no_count": 0, "expected_body_size": 7},
            "result": calculate_auditable_impact("ordinance", 7, 0, expected_body_size=7).to_dict(),
        },
        {
            "label": "Razor-Thin Zoning / Budget Vote (Full Council 4-3)",
            "inputs": {"event_type": "budget", "yes_count": 4, "no_count": 3, "expected_body_size": 7},
            "result": calculate_auditable_impact("budget", 4, 3, expected_body_size=7).to_dict(),
        },
        {
            "label": "Unanimous 4-Member Committee Recommendation (4-0)",
            "inputs": {
                "event_type": "ordinance",
                "yes_count": 4,
                "no_count": 0,
                "expected_body_size": 4,
                "body_type": "committee",
            },
            "result": calculate_auditable_impact(
                "ordinance", 4, 0, expected_body_size=4, body_type="committee"
            ).to_dict(),
        },
    ]
    return {
        "name": "CivicPulse Vote Impactfulness Formula",
        "formula_version": FORMULA_VERSION,
        "effective_date": FORMULA_EFFECTIVE_DATE,
        "formula_hash": f_hash,
        "nonpartisan_guarantee": (
            "Scores are 100% deterministic and never use political ideology, party, "
            "or subjective AI opinions. Anyone can recompute the exact score from the tally."
        ),
        "plain_english_summary": (
            "Every local measure receives a 0 to 100 score by adding three objective components: "
            "(1) Legal Weight (10-40 pts) based on whether it changes permanent law or budgets, "
            "(2) Contestedness (0-40 pts) based on how close the Yes/No vote margin was, and "
            "(3) Turnout (0-20 pts, capped at 10 pts for subcommittees) based on how many members "
            "of that body participated."
        ),
        "equation": "ImpactScore = min(100, LegalWeight + ((1 - |Yes - No| / (Yes + No)) * 40) + ((VotesCast / BodySize) * TurnoutCap))",
        "parameters": params,
        "examples": examples,
        "changelog": FORMULA_CHANGELOG,
        "downloads": {
            "markdown": "docs/civicpulse_impact_formula.md",
            "json": "docs/civicpulse_impact_formula.json",
        },
    }


def render_scoring_methodology_markdown() -> str:
    """Renders the plain-English downloadable formula document (Markdown)."""
    payload = build_scoring_methodology_payload()
    lines = [
        "# CivicPulse Vote Impactfulness Formula",
        "",
        f"- **Current Version:** `v{payload['formula_version']}`",
        f"- **Effective Date:** `{payload['effective_date']}`",
        f"- **Formula Checksum (SHA-256):** `{payload['formula_hash']}`",
        "",
        "> **Nonpartisan Guarantee:** CivicPulse's Impact Score is 100% deterministic math. "
        "It never evaluates political ideology, party affiliation, or AI sentiment. Anyone can "
        "verify a score by hand using the official vote tally.",
        "",
        "## Plain-English Summary",
        "",
        payload["plain_english_summary"],
        "",
        "## Exact Formula",
        "",
        "```text",
        "ImpactScore = min(100, LegalWeight + Contestedness + Turnout)",
        "",
        "Where:",
        "  LegalWeight   = 10 to 40 points (see table below)",
        "  Contestedness = (1 - |Yes - No| / (Yes + No)) * 40   (0 if Yes + No == 0)",
        "  Turnout       = (VotesCast / ExpectedBodySize) * Cap (Cap = 20 for full council, 10 for committee)",
        "```",
        "",
        "### Component 1: Legal Binding Weight (10 - 40 pts)",
        "",
        "| Measure Type | Points | What It Covers |",
        "| :--- | ---: | :--- |",
        "| Budget / Appropriation / Charter | 40 | Annual budgets, mill levies, tax rates, charter changes |",
        "| Zoning / Land Use | 38 | Rezonings, annexations, land-use code amendments |",
        "| Ordinance | 35 | Binding permanent changes to municipal or county code |",
        "| Resolution / Contract | 25 | Vendor contracts, grants, intergovernmental agreements, formal policy |",
        "| Motion | 20 | General floor motions and formal council directives |",
        "| Appointment | 15 | Board, commission, or officer appointments |",
        "| Consent Item | 12 | Bundled routine items approved in one motion |",
        "| Minutes / Proclamation | 10 | Approval of prior minutes or ceremonial proclamations |",
        "",
        "### Component 2: Contestedness / Vote Margin (0 - 40 pts)",
        "",
        "- **Unanimous votes** (e.g., `7-0` or `11-0`) add **0 points** because the governing body agreed without dissent.",
        "- **Close / split votes** (e.g., `4-3` or `6-5`) score near the maximum **40 points** because councilmembers disagreed and every vote mattered.",
        "",
        "### Component 3: Body Turnout (0 - 20 pts)",
        "",
        "- Full-council roll calls earn up to **20 points** proportional to members voting (`VotesCast / FullBodySize`).",
        "- **Committee votes** are measured against the **committee's own size** (not the full council roster) and capped at **10 points**, preventing misleading low-attendance penalties while distinguishing committee recommendations from full-council passage.",
        "",
        "## Worked Examples",
        "",
        "| Scenario | Legal | Split | Turnout | Final Score |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    for ex in payload["examples"]:
        r = ex["result"]
        lines.append(
            f"| {ex['label']} | {r['legal_weight']:g} | {r['contestedness']:g} | "
            f"{r['turnout']:g} | **{r['score']:g} / 100** |"
        )

    lines.extend([
        "",
        "## Formula Changelog (All Revisions)",
        "",
        "| Version | Date | Summary of Change |",
        "| :--- | :--- | :--- |",
    ])
    for ch in payload["changelog"]:
        lines.append(f"| `v{ch['version']}` | {ch['date']} | {ch['summary']} |")

    lines.append("")
    return "\n".join(lines)


def write_scoring_docs(public_dir: Path) -> Dict[str, str]:
    """Exports scoring_methodology.json + downloadable .md and .json formula files."""
    data_dir = public_dir / "data"
    docs_dir = public_dir / "docs"
    data_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    payload = build_scoring_methodology_payload()
    md_text = render_scoring_methodology_markdown()

    data_json_path = data_dir / "scoring_methodology.json"
    dl_json_path = docs_dir / "civicpulse_impact_formula.json"
    dl_md_path = docs_dir / "civicpulse_impact_formula.md"

    serialized = json.dumps(payload, indent=2) + "\n"
    data_json_path.write_text(serialized, encoding="utf-8")
    dl_json_path.write_text(serialized, encoding="utf-8")
    dl_md_path.write_text(md_text, encoding="utf-8")

    return {
        "data_json": str(data_json_path),
        "download_json": str(dl_json_path),
        "download_md": str(dl_md_path),
        "formula_version": FORMULA_VERSION,
        "formula_hash": payload["formula_hash"],
    }
