import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional
import requests

from db import get_connection, init_db

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")


def call_local_llm(prompt: str, system: str, timeout: int = 35) -> Optional[str]:
    """Calls local Ollama at $0/month; returns None gracefully if Ollama is offline."""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "system": system,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.15},
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return (r.json().get("response") or "").strip()
    except Exception:
        return None


# ==============================================================================
# AGENT 1: DATA-QUALITY & PROVENANCE AUDITOR
# ==============================================================================
def audit_event_provenance(event_row: sqlite3.Row, actions: List[sqlite3.Row], doc_raw_text: str) -> Dict[str, Any]:
    """
    Deterministic + provenance verification before publishing an event:
      1. Checks that yes/no/abstain/absent counts are non-negative and match recorded vote actions.
      2. Checks that every non-empty verbatim_quote appears in the source raw_text (when available).
      3. Checks that meeting_date is present and valid YYYY-MM-DD.
    Returns {"qa_status": "verified" | "flagged", "reasons": [...]}.
    """
    reasons: List[str] = []
    yes_c = event_row["yes_count"] or 0
    no_c = event_row["no_count"] or 0
    abs_c = event_row["abstain_count"] or 0
    miss_c = event_row["absent_count"] or 0

    if min(yes_c, no_c, abs_c, miss_c) < 0:
        reasons.append("Negative vote count detected.")

    mdate = (event_row["meeting_date"] or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", mdate):
        reasons.append(f"Non-ISO or missing meeting_date: '{mdate}'.")

    # Verify recorded vote tallies reconcile with individual vote actions when actions exist
    vote_actions = [a for a in actions if (a["action_type"] or "").lower() == "vote"]
    if vote_actions:
        tally_sum = yes_c + no_c + abs_c + miss_c
        if tally_sum > 0 and abs(tally_sum - len(vote_actions)) > 2:
            reasons.append(f"Vote tally sum ({tally_sum}) diverges from recorded actions ({len(vote_actions)}).")

    # Verify verbatim quotes against source text if available
    norm_source = re.sub(r"\s+", " ", (doc_raw_text or "")).lower()
    if norm_source:
        for act in actions:
            q = (act["verbatim_quote"] or "").strip()
            if len(q) >= 15:
                norm_q = re.sub(r"\s+", " ", q).lower()
                if norm_q not in norm_source:
                    reasons.append(f"Quote not found verbatim in source text for {act['entity_id']}.")

    return {
        "qa_status": "flagged" if reasons else "verified",
        "reasons": reasons,
    }


def run_provenance_auditor() -> None:
    init_db()
    conn = get_connection()
    try:
        events = conn.execute("SELECT * FROM events").fetchall()
        verified_cnt = 0
        flagged_cnt = 0

        for ev in events:
            actions = conn.execute(
                "SELECT * FROM entity_actions WHERE event_id = ?", (ev["event_id"],)
            ).fetchall()
            doc_text = ""
            if ev["doc_id"]:
                doc_row = conn.execute(
                    "SELECT raw_text FROM documents WHERE doc_id = ?", (ev["doc_id"],)
                ).fetchone()
                if doc_row:
                    doc_text = doc_row["raw_text"] or ""

            audit = audit_event_provenance(ev, actions, doc_text)
            conn.execute(
                "UPDATE events SET qa_status = ? WHERE event_id = ?",
                (audit["qa_status"], ev["event_id"]),
            )
            if audit["qa_status"] == "verified":
                verified_cnt += 1
            else:
                flagged_cnt += 1
                print(f"  [FLAGGED] {ev['event_id']} ({ev['title'][:50]}): {'; '.join(audit['reasons'])}")

        conn.commit()
        print(f"[Agent 1 - Provenance Auditor] Verified: {verified_cnt} | Flagged: {flagged_cnt}")
    finally:
        conn.close()


# ==============================================================================
# AGENT 2: PLAIN-ENGLISH EXPLAINER & "WHAT CHANGED?" AGENT
# ==============================================================================
def deterministic_plain_summary(title: str, event_type: str, outcome: str) -> str:
    etype = (event_type or "measure").lower()
    clean_title = re.sub(r"\s+", " ", (title or "").strip())
    out_text = f" ({outcome})" if outcome else ""
    if "ordinance" in etype:
        return f"Proposed binding local law{out_text}: {clean_title[:180]}."
    if "resolution" in etype:
        return f"Council policy or contract action{out_text}: {clean_title[:180]}."
    return f"Local government measure{out_text}: {clean_title[:180]}."


def find_prior_similar_event(conn: sqlite3.Connection, ev: sqlite3.Row) -> Optional[sqlite3.Row]:
    """Finds an earlier event in the same jurisdiction sharing an ordinance/resolution number or key title words."""
    title = ev["title"] or ""
    ord_match = re.search(r"(?:ordinance|resolution|bill|no\.?)\s*#?\s*([a-zA-Z0-9-]+)", title, re.IGNORECASE)
    if ord_match:
        code = ord_match.group(1)
        prior = conn.execute(
            """
            SELECT * FROM events
            WHERE jurisdiction_id = ? AND event_id != ? AND meeting_date < ? AND title LIKE ?
            ORDER BY meeting_date DESC LIMIT 1
            """,
            (ev["jurisdiction_id"], ev["event_id"], ev["meeting_date"], f"%{code}%"),
        ).fetchone()
        if prior:
            return prior
    return None


def run_plain_english_explainer(use_llm: bool = True) -> None:
    init_db()
    conn = get_connection()
    try:
        events = conn.execute("SELECT * FROM events").fetchall()
        updated = 0

        for ev in events:
            existing_plain = (ev["plain_summary"] or "").strip()
            existing_diff = (ev["diff_summary"] or "").strip()

            plain_text = existing_plain
            if not plain_text:
                if use_llm:
                    sys_prompt = (
                        "You are a neutral civic explainer for everyday residents. "
                        "Write a concise, plain-English 2-sentence summary explaining what this local measure does "
                        "and who is affected. Do not take sides or invent facts not in the title."
                    )
                    user_prompt = (
                        f"Type: {ev['event_type']}\n"
                        f"Outcome: {ev['outcome'] or 'Recorded'}\n"
                        f"Title: {ev['title']}"
                    )
                    llm_out = call_local_llm(user_prompt, sys_prompt)
                    if llm_out:
                        plain_text = llm_out.strip()

                if not plain_text:
                    plain_text = deterministic_plain_summary(ev["title"], ev["event_type"], ev["outcome"] or "")

            diff_text = existing_diff
            prior_ev = find_prior_similar_event(conn, ev)
            if prior_ev and not diff_text:
                if use_llm:
                    sys_prompt = (
                        "Compare two related local government items from earlier and later dates. "
                        "State in 1-2 neutral sentences what changed or progressed between them."
                    )
                    user_prompt = (
                        f"Earlier ({prior_ev['meeting_date']}): {prior_ev['title']} [Outcome: {prior_ev['outcome']}]\n"
                        f"Later ({ev['meeting_date']}): {ev['title']} [Outcome: {ev['outcome']}]"
                    )
                    diff_text = call_local_llm(user_prompt, sys_prompt) or ""
                if not diff_text:
                    diff_text = f"Follows earlier item on {prior_ev['meeting_date']}: {prior_ev['title'][:120]}."

            conn.execute(
                "UPDATE events SET plain_summary = ?, diff_summary = ? WHERE event_id = ?",
                (plain_text, diff_text or None, ev["event_id"]),
            )
            updated += 1

        conn.commit()
        print(f"[Agent 2 - Plain-English & What Changed] Updated {updated} event(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    run_provenance_auditor()
    run_plain_english_explainer(use_llm=True)
