"""Data normalization, resident/commercial topic classification, committee
attendance detection, and AI extraction QA validation for CivicPulse v2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Canonical Jurisdiction Levels (fixes city vs municipal, school_board vs school_district)
# ---------------------------------------------------------------------------
LEVEL_ALIASES: Dict[str, str] = {
    "city": "city",
    "municipal": "city",
    "municipality": "city",
    "town": "city",
    "county": "county",
    "school_district": "school_district",
    "school_board": "school_district",
    "school": "school_district",
    "special_district": "special_district",
    "state": "state",
    "federal": "federal",
}

CANONICAL_LEVELS = ("city", "county", "school_district", "special_district", "state", "federal")


def normalize_level(raw_level: Optional[str], ocd_division_id: str = "") -> str:
    """Maps mixed level labels to canonical frontend-matched values."""
    key = (raw_level or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in LEVEL_ALIASES:
        return LEVEL_ALIASES[key]
    div = (ocd_division_id or "").lower()
    if "/school_district:" in div or "/sd:" in div:
        return "school_district"
    if "/county:" in div:
        return "county"
    if "/place:" in div:
        return "city"
    if "/cd:" in div:
        return "federal"
    return "city"


# ---------------------------------------------------------------------------
# 2. Outcome & Tally Normalization (fixes "Adopted 7-0 (7-0)", "Approved by Consent")
# ---------------------------------------------------------------------------
TALLY_RE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})(?:\s*[-:]\s*(\d{1,2}))?\b")


@dataclass(frozen=True)
class NormalizedOutcome:
    status: str           # Passed | Failed | Tabled | Withdrawn | Pending | Recorded
    passage_method: str   # Roll Call | Consent | Voice Vote | Unanimous | Unknown
    tally: str            # e.g. "7-0" or ""
    yes_count: int
    no_count: int
    abstain_count: int


def normalize_outcome(
    raw_outcome: Optional[str],
    yes_count: int = 0,
    no_count: int = 0,
    abstain_count: int = 0,
    individual_vote_count: int = 0,
) -> NormalizedOutcome:
    """Normalizes messy clerk/LLM outcomes into canonical status + separate tally."""
    text = (raw_outcome or "").strip()
    low = text.lower()

    y = max(0, int(yes_count or 0))
    n = max(0, int(no_count or 0))
    a = max(0, int(abstain_count or 0))

    # Extract embedded tally if DB counts are missing
    if y == 0 and n == 0:
        m = TALLY_RE.search(text)
        if m:
            y = int(m.group(1))
            n = int(m.group(2))
            if m.group(3):
                a = int(m.group(3))

    # Canonical status
    if any(k in low for k in ("fail", "denied", "deny", "rejected", "defeated", "lost")):
        status = "Failed"
    elif any(k in low for k in ("table", "postpon", "continu", "defer")):
        status = "Tabled"
    elif any(k in low for k in ("withdraw", "pulled", "removed")):
        status = "Withdrawn"
    elif any(k in low for k in ("pending", "scheduled", "first reading", "upcoming", "introduced")):
        status = "Pending"
    elif any(k in low for k in ("pass", "adopt", "approv", "carried", "enacted", "confirmed")):
        status = "Passed"
    elif y > 0 and y > n:
        status = "Passed"
    elif n > 0 and n >= y:
        status = "Failed"
    else:
        status = "Recorded"

    # Passage method (important for distinguishing voice/consent votes from roll-call votes)
    if "consent" in low:
        method = "Consent"
    elif "voice" in low:
        method = "Voice Vote"
    elif individual_vote_count > 0:
        method = "Roll Call"
    elif "unanim" in low or (y > 0 and n == 0):
        method = "Unanimous"
    elif y > 0 or n > 0:
        method = "Tally Only"
    else:
        method = "Unknown"

    tally = ""
    if y > 0 or n > 0:
        tally = f"{y}-{n}-{a}" if a > 0 else f"{y}-{n}"

    return NormalizedOutcome(
        status=status,
        passage_method=method,
        tally=tally,
        yes_count=y,
        no_count=n,
        abstain_count=a,
    )


# ---------------------------------------------------------------------------
# 3. Resident + Commercial Topic Taxonomy (eliminates vague "General" tags)
# ---------------------------------------------------------------------------
TOPIC_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    (
        "Zoning & Land Use",
        (
            "zoning", "rezone", "rezoning", "land use", "pud", "planned unit",
            "annexation", "annex", "plat", "subdivision", "variance", "setback",
            "comprehensive plan", "master plan", "urban renewal", "metro district",
            "metropolitan district", "easement", "right-of-way", "right of way",
        ),
    ),
    (
        "Housing & Development",
        (
            "housing", "affordable", "multifamily", "multi-family", "residential",
            "short-term rental", "str ", "tenant", "eviction", "homeless",
            "shelter", "development agreement", "site plan", "building code",
        ),
    ),
    (
        "Taxes, Fees & Utilities",
        (
            "tax", "mill levy", "sales tax", "lodging tax", "impact fee",
            "fee schedule", "utility rate", "water rate", "electric rate",
            "stormwater fee", "sewer rate", "wastewater", "tariff", "rate increase",
            "assessment", "gid", "general improvement district",
        ),
    ),
    (
        "Budget & Finance",
        (
            "budget", "appropriation", "supplemental appropriation", "bond",
            "certificate of participation", "cop ", "grant", "fund transfer",
            "capital improvement", "cip", "audit", "financial", "fiscal",
            "debt", "treasury", "reserve fund",
        ),
    ),
    (
        "Contracts & Procurement",
        (
            "contract", "agreement", "rfp", "procurement", "bid", "vendor",
            "amendment to agreement", "intergovernmental agreement", "iga",
            "memorandum of understanding", "mou", "lease", "leases", "purchase order", "master purchase order",
            "professional services", "on-call services", "contractor",
        ),
    ),
    (
        "Permits & Licensing",
        (
            "license", "licensing", "liquor", "marijuana", "cannabis",
            "permit", "business license", "vending", "food truck", "sign code",
            "commercial permit", "special event permit",
        ),
    ),
    (
        "Infrastructure & Transit",
        (
            "transit", "bus", "rail", "traffic", "road", "street", "bridge",
            "highway", "sidewalk", "bike", "bicycle", "mobility", "parking",
            "airport", "broadband", "fiber", "paving", "intersection", "corridor",
        ),
    ),
    (
        "Public Safety",
        (
            "police", "fire", "ems", "emergency", "sheriff", "public safety",
            "court", "municipal court", "code enforcement", "wildfire",
            "hazard", "dispatch", "911", "crime", "mental health co-responder",
        ),
    ),
    (
        "Parks, Water & Environment",
        (
            "park", "open space", "trail", "recreation", "water rights",
            "reservoir", "river", "climate", "solar", "renewable", "energy",
            "sustainability", "recycling", "compost", "plastic", "wildlife", "oil and gas",
        ),
    ),
    (
        "Education & Schools",
        (
            "school", "student", "curriculum", "superintendent", "teacher",
            "charter school", "district", "campus", "enrollment", "library",
        ),
    ),
    (
        "Governance & Elections",
        (
            "election", "ballot", "charter", "appointment", "board member", "reauthorization of boards", "boards and commissions",
            "commissioner", "council rules", "ethics", "campaign finance",
            "redistricting", "minutes", "proclamation", "executive session",
            "city manager", "city attorney",
        ),
    ),
]

COMMERCIAL_TOPICS = frozenset({
    "Zoning & Land Use",
    "Housing & Development",
    "Taxes, Fees & Utilities",
    "Contracts & Procurement",
    "Permits & Licensing",
    "Infrastructure & Transit",
})

VAGUE_TOPICS = frozenset({"", "general", "other", "misc", "miscellaneous", "bill", "resolution", "ordinance"})


COMPILED_TOPIC_RULES: List[Tuple[str, List[re.Pattern]]] = [
    (
        topic_name,
        [re.compile(r"\b" + re.escape(kw.strip()) + r"\b", re.IGNORECASE) for kw in keywords if kw.strip()],
    )
    for topic_name, keywords in TOPIC_RULES
]


def classify_topic(
    title: str,
    summary: str = "",
    existing_topic: Optional[str] = None,
) -> str:
    """Assigns a specific, browsable topic label using whole-word boundaries & 2x title weighting."""
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
    return best_topic


def is_business_relevant(topic: str) -> bool:
    return topic in COMMERCIAL_TOPICS


# ---------------------------------------------------------------------------
# 4. Committee Detection (fixes 4/13 = 31% attendance distortion)
# ---------------------------------------------------------------------------
COMMITTEE_RE = re.compile(
    r"\b("
    r"committee|subcommittee|task force|working group|"
    r"luti|land use, transportation|finance & governance|finance and governance|"
    r"business, arts, workforce|safety, housing, education|"
    r"south platte river committee|budget committee"
    r")\b",
    re.IGNORECASE,
)


def detect_body_type(title: str, doc_title: str = "", votes_cast: int = 0, full_roster_size: int = 0) -> str:
    """Returns 'committee' or 'full_body' so attendance denominators stay accurate."""
    combined = f"{doc_title or ''} {title or ''}"
    if COMMITTEE_RE.search(combined):
        return "committee"
    return "full_body"


# ---------------------------------------------------------------------------
# 5. AI Extraction QA Validation Gate (validates roster & tally math before 'verified')
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QAValidationResult:
    qa_status: str   # "verified" | "needs_review" | "flagged"
    issues: Tuple[str, ...]


def validate_extracted_event(
    outcome_status: str,
    yes_count: int,
    no_count: int,
    abstain_count: int,
    absent_count: int,
    matched_votes: List[Dict[str, Any]],
    unmatched_voter_names: Iterable[str],
    roster_size: int,
    capture_method: str = "ai_minutes_pdf",
    body_type: str = "full_body",
) -> QAValidationResult:
    """Validates AI-extracted votes against the roster and tally arithmetic before marking verified."""
    issues: List[str] = []

    unmatched = [u for u in unmatched_voter_names if (u or "").strip()]
    if unmatched:
        issues.append(f"Unmatched voter name(s) not in active roster: {', '.join(unmatched[:5])}")

    # Check duplicate voters in the same event
    seen_ids = set()
    dup_ids = []
    for v in matched_votes:
        eid = v.get("entity_id")
        if eid in seen_ids:
            dup_ids.append(eid)
        seen_ids.add(eid)
    if dup_ids:
        issues.append(f"Duplicate vote entries for {len(dup_ids)} representative(s)")

    # Check individual roll-call votes sum matches headline counts (when roll-call votes were extracted)
    if matched_votes:
        rc_yes = sum(1 for v in matched_votes if (v.get("value") or "").lower() == "yes")
        rc_no = sum(1 for v in matched_votes if (v.get("value") or "").lower() == "no")
        rc_abs = sum(1 for v in matched_votes if (v.get("value") or "").lower() == "abstain")
        if (yes_count > 0 or no_count > 0) and (rc_yes != yes_count or rc_no != no_count):
            issues.append(
                f"Roll-call vote mismatch: extracted {rc_yes} Yes / {rc_no} No "
                f"vs reported tally {yes_count}-{no_count}"
            )
        if abstain_count > 0 and rc_abs != abstain_count:
            issues.append(f"Abstain mismatch: extracted {rc_abs} vs reported {abstain_count}")

    # Check total votes do not exceed known active roster size
    total_reported = max(0, yes_count) + max(0, no_count) + max(0, abstain_count)
    if roster_size > 0 and total_reported > roster_size:
        issues.append(f"Reported votes ({total_reported}) exceed active roster size ({roster_size})")

    # Check outcome direction agrees with tally
    if outcome_status == "Passed" and no_count > yes_count and (yes_count + no_count) > 0:
        issues.append(f"Outcome says Passed but No votes ({no_count}) exceed Yes votes ({yes_count})")
    if outcome_status == "Failed" and yes_count > no_count and no_count == 0 and yes_count > 0:
        issues.append(f"Outcome says Failed despite unanimous Yes ({yes_count}-0)")

    if not issues:
        return QAValidationResult(qa_status="verified", issues=())

    # Severe structural contradiction -> flagged; minor mismatch -> needs_review
    severe = any(
        ("exceed active roster" in i) or ("Outcome says Passed" in i) or ("Duplicate vote" in i)
        for i in issues
    )
    return QAValidationResult(
        qa_status="flagged" if severe else "needs_review",
        issues=tuple(issues),
    )
