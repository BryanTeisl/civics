import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import requests
from pydantic import BaseModel, Field, ValidationError

from db import get_connection

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
MAX_RETRIES = 3
MAX_CHARS = 12000


def calculate_impact_score(event_type: str, yes_count: int, no_count: int) -> float:
    base = {
        "ordinance": 40.0,
        "budget": 50.0,
        "zoning": 40.0,
        "resolution": 25.0,
    }.get((event_type or "").lower(), 20.0)
    total = yes_count + no_count
    if total == 0:
        return base
    margin = abs(yes_count - no_count) / total
    closeness_bonus = (1.0 - margin) * 50.0
    return round(min(100.0, base + closeness_bonus), 1)


def is_pivotal_vote(vote: str, yes_count: int, no_count: int) -> bool:
    if vote not in ("Yes", "No"):
        return False
    return abs(yes_count - no_count) <= 1 and (yes_count + no_count) > 0


class ExtractedVote(BaseModel):
    ocd_person_id: str = Field(..., description="Exact ocd_person_id from the roster, or councilor name")
    vote: str = Field(..., description="Yes, No, Abstain, or Absent")
    summary: Optional[str] = Field(None, description="Short neutral rationale if stated in minutes")
    quote: Optional[str] = Field(None, description="Direct quote if present")


class ExtractedEvent(BaseModel):
    title: str = Field(..., description="Short title of the ordinance, resolution, or motion")
    event_type: str = Field("motion", description="ordinance, resolution, budget, zoning, or motion")
    topic: Optional[str] = Field("General", description="Short topic label")
    outcome: str = Field(..., description="Passed, Adopted, Failed, or Tabled")
    votes: List[ExtractedVote] = Field(default_factory=list)


class MinutesExtraction(BaseModel):
    events: List[ExtractedEvent] = Field(default_factory=list)


def reset_failed_documents() -> int:
    """Reset all failed or retried documents back to pending."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE documents
            SET status = 'pending',
                retry_count = 0,
                error_message = NULL
            WHERE status = 'failed' OR retry_count > 0
            """
        )
        conn.commit()
        count = cursor.rowcount
        print(f"[WORKER] Reset {count} failed/retried document(s) back to 'pending'.")
        return count
    finally:
        conn.close()


def normalize_vote(raw_vote: str) -> str:
    val = (raw_vote or "").strip().lower()
    if val in ("yes", "aye", "yea", "for", "approve", "approved", "in favor"):
        return "Yes"
    if val in ("no", "nay", "against", "opposed"):
        return "No"
    if val in ("abstain", "abstained", "recused", "present"):
        return "Abstain"
    return "Absent"


def trim_for_voting_context(raw_text: str, max_chars: int = MAX_CHARS) -> str:
    """Keep paragraphs around motions/votes so long minutes don't time out on CPU."""
    text = (raw_text or "").strip()
    if len(text) <= max_chars:
        return text

    keywords = (
        "motion", "vote", "aye", "nay", "yea", "adopted", "passed",
        "failed", "roll call", "unanimous", "ordinance", "resolution",
        "consent", "seconded", "carried", "absent", "abstain",
    )
    lines = text.splitlines()
    kept = []
    for i, line in enumerate(lines):
        window = "\n".join(lines[max(0, i - 2) : i + 3]).lower()
        if any(k in window for k in keywords):
            kept.append(line)

    filtered = "\n".join(kept).strip()
    return filtered[:max_chars] if filtered else text[:max_chars]


def build_person_resolver(roster):
    valid_ids = {row["ocd_person_id"] for row in roster}
    name_to_id = {}
    for row in roster:
        full_name = row["name"].strip().lower()
        name_to_id[full_name] = row["ocd_person_id"]
        parts = full_name.split()
        if parts:
            name_to_id[parts[-1]] = row["ocd_person_id"]

    def resolve(raw_id_or_name: str) -> Optional[str]:
        if not raw_id_or_name:
            return None
        val = raw_id_or_name.strip()
        if val in valid_ids:
            return val
        lower = val.lower()
        if lower in name_to_id:
            return name_to_id[lower]
        tokens = lower.replace("-", " ").replace("/", " ").replace(",", " ").split()
        if tokens and tokens[-1] in name_to_id:
            return name_to_id[tokens[-1]]
        return None

    return resolve


def extract_votes_with_ollama(raw_text: str, roster_lines: str) -> MinutesExtraction:
    schema_json = json.dumps(MinutesExtraction.model_json_schema())
    trimmed_text = trim_for_voting_context(raw_text)

    prompt = (
        "You are a municipal legislative data extractor. Extract all formal roll-call "
        "and recorded votes from the meeting text below.\n\n"
        "RULES:\n"
        "1. Use ONLY the exact ocd_person_id values from the Official Roster below.\n"
        "2. For unanimous votes (e.g., 'Adopted 7-0' or 'Passed unanimously'), record 'Yes' for every present councilor.\n"
        "3. For shorthand like 'Adopted 6-1 (Nay: Name)', record 'No' for the named dissenter and 'Yes' for the other councilors.\n"
        "4. If no votes occurred (e.g., work session or pure discussion), return {\"events\": []}.\n"
        "5. Output ONLY valid JSON matching this schema:\n"
        f"{schema_json}\n\n"
        f"OFFICIAL ROSTER:\n{roster_lines}\n\n"
        f"MEETING TEXT:\n{trimmed_text}\n"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "num_thread": 4,
            "num_ctx": 4096,
            "temperature": 0.0,
        },
    }

    resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
    resp.raise_for_status()
    raw_json = resp.json().get("response", "{}")
    return MinutesExtraction.model_validate_json(raw_json)


def process_next_pending_document() -> bool:
    conn = get_connection()
    doc = conn.execute(
        """
        SELECT * FROM documents
        WHERE status = 'pending'
          AND retry_count < ?
          AND (
              LOWER(doc_type) IN ('minutes', 'action_agenda')
              OR LOWER(title) LIKE '%action%'
              OR LOWER(title) LIKE '%minute%'
          )
        ORDER BY created_at ASC LIMIT 1
        """,
        (MAX_RETRIES,),
    ).fetchone()

    if not doc:
        conn.close()
        return False

    roster = conn.execute(
        "SELECT ocd_person_id, name FROM entities WHERE jurisdiction_id = ?",
        (doc["jurisdiction_id"],),
    ).fetchall()

    print(f"[WORKER] Processing doc #{doc['doc_id']}: {doc['title']} ({doc['doc_type']})...")

    if not roster:
        print(f"  ! No roster found for {doc['jurisdiction_id']}; skipping doc #{doc['doc_id']}.")
        conn.execute(
            "UPDATE documents SET status = 'failed', error_message = ? WHERE doc_id = ?",
            ("No roster entities found for jurisdiction", doc["doc_id"]),
        )
        conn.commit()
        conn.close()
        return True

    roster_lines = "\n".join(f"- {r['ocd_person_id']}: {r['name']}" for r in roster)
    resolve_person_id = build_person_resolver(roster)

    try:
        extracted = extract_votes_with_ollama(doc["raw_text"] or "", roster_lines)

        inserted_events = 0
        for ev in extracted.events:
            resolved_votes = []
            seen_ids = set()
            for v in ev.votes:
                person_id = resolve_person_id(v.ocd_person_id)
                if not person_id:
                    print(f"    - Skipping unmatched voter: {v.ocd_person_id}")
                    continue
                if person_id in seen_ids:
                    continue
                seen_ids.add(person_id)
                resolved_votes.append((person_id, normalize_vote(v.vote), v.summary, v.quote))

            if not resolved_votes:
                continue

            yes_count = sum(1 for _, v_val, _, _ in resolved_votes if v_val == "Yes")
            no_count = sum(1 for _, v_val, _, _ in resolved_votes if v_val == "No")
            abstain_count = sum(1 for _, v_val, _, _ in resolved_votes if v_val == "Abstain")
            absent_count = sum(1 for _, v_val, _, _ in resolved_votes if v_val == "Absent")
            vote_margin = abs(yes_count - no_count)
            impact = calculate_impact_score(ev.event_type, yes_count, no_count)
            outcome_str = f"{ev.outcome} ({yes_count}-{no_count})"
            event_id = f"doc-{doc['doc_id']}-{uuid.uuid4().hex[:8]}"
            meeting_date = doc["meeting_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")

            conn.execute(
                """
                INSERT INTO events (
                    event_id, jurisdiction_id, doc_id, meeting_date,
                    title, event_type, topic, outcome,
                    yes_count, no_count, abstain_count, absent_count,
                    vote_margin, impact_score, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    doc["jurisdiction_id"],
                    doc["doc_id"],
                    meeting_date,
                    ev.title,
                    ev.event_type,
                    ev.topic or "General",
                    outcome_str,
                    yes_count,
                    no_count,
                    abstain_count,
                    absent_count,
                    vote_margin,
                    impact,
                    doc["source_url"],
                ),
            )

            for person_id, v_val, summary, quote in resolved_votes:
                pivotal = 1 if is_pivotal_vote(v_val, yes_count, no_count) else 0
                conn.execute(
                    """
                    INSERT OR IGNORE INTO entity_actions (
                        event_id, entity_id, action_type, value,
                        is_pivotal, rationale_summary, verbatim_quote
                    ) VALUES (?, ?, 'vote', ?, ?, ?, ?)
                    """,
                    (event_id, person_id, v_val, pivotal, summary, quote),
                )

            inserted_events += 1

        conn.execute(
            "UPDATE documents SET status = 'processed', processed_at = ? WHERE doc_id = ?",
            (datetime.now(timezone.utc).isoformat(), doc["doc_id"]),
        )
        conn.commit()
        print(f"  + Extracted {inserted_events} vote events.")

    except requests.RequestException as exc:
        conn.rollback()
        print(f"  ! Ollama connection/API error on doc #{doc['doc_id']}: {exc}")
        print("  ! Leaving document 'pending' (retry_count unchanged) and stopping worker.")
        conn.close()
        raise SystemExit(1)

    except (ValidationError, Exception) as exc:
        conn.rollback()
        conn.execute(
            """
            UPDATE documents
            SET retry_count = retry_count + 1,
                status = CASE WHEN retry_count + 1 >= ? THEN 'failed' ELSE 'pending' END,
                error_message = ?
            WHERE doc_id = ?
            """,
            (MAX_RETRIES, str(exc), doc["doc_id"]),
        )
        conn.commit()
        print(f"  ! Failed doc #{doc['doc_id']}: {exc}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return True


def run_worker(limit: Optional[int] = None):
    processed_count = 0
    while True:
        if limit is not None and processed_count >= limit:
            print(f"[WORKER] Reached limit of {limit} document(s). Stopping.")
            break
        if not process_next_pending_document():
            break
        processed_count += 1

    if processed_count == 0:
        print("Worker queue empty.")


def main():
    parser = argparse.ArgumentParser(description="Local LLM vote extraction worker.")
    parser.add_argument(
        "--reset-failed",
        action="store_true",
        help="Reset failed/retried documents back to pending before running.",
    )
    parser.add_argument(
        "--reset-only",
        action="store_true",
        help="Reset failed/retried documents back to pending and exit.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of documents to process in this run.",
    )
    args = parser.parse_args()

    if args.reset_only:
        reset_failed_documents()
        return

    if args.reset_failed:
        reset_failed_documents()

    run_worker(limit=args.limit)


if __name__ == "__main__":
    main()