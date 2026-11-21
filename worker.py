"""
RTX 2060 + Ollama Sequential Extraction Worker.
Processes pending 'minutes' documents one at a time, enforces Pydantic JSON,
computes Vote Impactfulness, and writes normalized rows to SQLite.
"""
import json
import os
from datetime import datetime
from typing import List, Literal, Optional
import requests
from pydantic import BaseModel, Field, ValidationError
from db import get_connection
from metrics import compute_vote_impactfulness, is_vote_pivotal

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
# Default to 4-bit Llama 3.1 8B (fits 6GB RTX 2060 VRAM); swap to 'qwen2.5:3b' for faster speed
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
MAX_RETRIES = 2


class ExtractedVote(BaseModel):
    entity_id: str
    vote: Literal["Yes", "No", "Abstain", "Absent"]
    made_motion: bool = False
    seconded_motion: bool = False
    rationale_summary: str = Field(default="Recorded via official minutes.")
    verbatim_quote: Optional[str] = None


class ExtractedEvent(BaseModel):
    item_code: str
    title: str
    event_type: Literal["ordinance", "resolution", "budget", "motion", "consent"] = "ordinance"
    topic: str = "General"
    outcome: Literal["Passed", "Failed", "Tabled"]
    votes: List[ExtractedVote]


class MinutesExtraction(BaseModel):
    events: List[ExtractedEvent]


def call_ollama_structured(raw_text: str, roster: list) -> MinutesExtraction:
    roster_str = "\n".join(f"- {r['name']}: {r['ocd_person_id']}" for r in roster)    
    schema_json = json.dumps(MinutesExtraction.model_json_schema())
    # Truncate very long packets to keep RTX 2060 6GB VRAM from spilling heavily into CPU RAM
    trimmed_text = raw_text[:14000]
    prompt = f"""You are a strictly factual municipal clerk assistant.
Extract all roll-call vote items from the official meeting minutes below.
Use ONLY these exact entity_id values:
{roster_str}

Rules:
- Only include items with an explicit roll-call or recorded vote.
- Do not invent quotes. Set verbatim_quote to null if no direct quote is in the minutes.
- Return ONLY valid JSON matching this schema: {schema_json}

Official Minutes Text:
{trimmed_text}
"""

    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0, "num_ctx": 4096},
        },
        timeout=180,
    )
    resp.raise_for_status()
    raw_json = resp.json()["response"]
    return MinutesExtraction.model_validate_json(raw_json)


def process_next_pending_document() -> bool:
    conn = get_connection()
    doc = conn.execute("""
        SELECT * FROM documents
        WHERE status = 'pending' AND doc_type = 'minutes' AND retry_count < ?
        ORDER BY created_at ASC LIMIT 1
    """, (MAX_RETRIES,)).fetchone()

    if not doc:
        conn.close()
        return False

    roster = conn.execute(
        "SELECT ocd_person_id, name FROM entities WHERE jurisdiction_id = ?",
        (doc["jurisdiction_id"],),
    ).fetchall()

    print(f"[WORKER] Processing doc #{doc['doc_id']}: {doc['title']}...")
    try:
        extracted = call_ollama_structured(doc["raw_text"], roster)
        cur = conn.cursor()

        for ev in extracted.events:
            event_id = f"{doc['meeting_date']}-{ev.item_code}".lower().replace(" ", "-")
            yes_c = sum(1 for v in ev.votes if v.vote == "Yes")
            no_c = sum(1 for v in ev.votes if v.vote == "No")
            abs_c = sum(1 for v in ev.votes if v.vote == "Abstain")
            absent_c = sum(1 for v in ev.votes if v.vote == "Absent")

            impact_score, margin, _ = compute_vote_impactfulness(yes_c, no_c, ev.event_type)

            cur.execute("""
                INSERT OR REPLACE INTO events
                (event_id, jurisdiction_id, doc_id, meeting_date, title, event_type, topic,
                 outcome, yes_count, no_count, abstain_count, absent_count, vote_margin, impact_score, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, doc["jurisdiction_id"], doc["doc_id"], doc["meeting_date"],
                ev.title, ev.event_type, ev.topic, ev.outcome,
                yes_c, no_c, abs_c, absent_c, margin, impact_score, doc["source_url"],
            ))

            for v in ev.votes:
                pivotal = is_vote_pivotal(v.vote, yes_c, no_c)
                cur.execute("""
                    INSERT OR REPLACE INTO entity_actions
                    (event_id, entity_id, action_type, value, is_pivotal, rationale_summary, verbatim_quote)
                    VALUES (?, ?, 'vote', ?, ?, ?, ?)
                """, (event_id, v.entity_id, v.vote, pivotal, v.rationale_summary, v.verbatim_quote))

                if v.made_motion:
                    cur.execute("""
                        INSERT OR IGNORE INTO entity_actions (event_id, entity_id, action_type, value)
                        VALUES (?, ?, 'motion', 'Mover')
                    """, (event_id, v.entity_id))

        cur.execute(
            "UPDATE documents SET status = 'processed', processed_at = ? WHERE doc_id = ?",
            (datetime.utcnow().isoformat(), doc["doc_id"]),
        )
        conn.commit()
        print(f"  + Extracted {len(extracted.events)} vote events.")
    except (ValidationError, Exception) as exc:
        conn.execute("""
            UPDATE documents
            SET retry_count = retry_count + 1,
                status = CASE WHEN retry_count + 1 >= ? THEN 'failed' ELSE 'pending' END,
                error_message = ?
            WHERE doc_id = ?
        """, (MAX_RETRIES, str(exc), doc["doc_id"]))
        conn.commit()
        print(f"  ! Failed doc #{doc['doc_id']}: {exc}")
    finally:
        conn.close()

    return True


if __name__ == "__main__":
    while process_next_pending_document():
        pass
    print("GPU worker queue empty.")
