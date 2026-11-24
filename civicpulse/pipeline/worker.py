from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from civicpulse.config import SETTINGS
from civicpulse.db import get_connection, init_db
from civicpulse.pipeline.metrics import compute_impact_score

MAX_PDF_PAGES = 40
MAX_RAW_TEXT_CHARS = 50_000
LLM_PROMPT_CHARS = 12_000

CIVICCLERK_EVENT_RE = re.compile(
    r"https?://([a-z0-9-]+)\.portal\.civicclerk\.com/event/(\d+)",
    re.IGNORECASE,
)


def _extract_pdf_text(content: bytes, max_pages: int = MAX_PDF_PAGES) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    chunks: List[str] = []
    for page in reader.pages[:max_pages]:
        txt = (page.extract_text() or "").strip()
        if txt:
            chunks.append(txt)
    return "\n\n".join(chunks)


def _extract_html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    return "\n".join(lines)


def _fetch_civicclerk_event_text(slug: str, event_id: str, preferred_doc_type: str) -> str:
    """Resolves a CivicClerk SPA event URL via the v1 API and fetches minutes/agenda text."""
    meta_url = f"https://{slug}.api.civicclerk.com/v1/Events/{event_id}"
    r = requests.get(meta_url, headers=SETTINGS.headers, timeout=SETTINGS.request_timeout)
    r.raise_for_status()
    data = r.json()
    files = data.get("publishedFiles") or []
    if not files:
        return ""

    def _file_rank(f: Dict[str, Any]) -> Tuple[int, int]:
        label = f"{f.get('type', '')} {f.get('name', '')}".lower()
        wants_minutes = preferred_doc_type == "minutes"
        if wants_minutes and "minute" in label:
            return (0, 0)
        if "minute" in label:
            return (1, 0)
        if "agenda" in label and "packet" not in label:
            return (2, 0)
        return (3, 0)

    chosen = sorted(files, key=_file_rank)[0]
    file_id = chosen.get("fileId") or chosen.get("id")
    if not file_id:
        return ""

    stream_url = (
        f"https://{slug}.api.civicclerk.com/v1/Meetings/"
        f"GetMeetingFileStream(fileId={file_id},plainText=true)"
    )
    fr = requests.get(stream_url, headers=SETTINGS.headers, timeout=max(30, SETTINGS.request_timeout))
    fr.raise_for_status()
    if fr.content[:5] == b"%PDF-" or "application/pdf" in fr.headers.get("Content-Type", "").lower():
        return _extract_pdf_text(fr.content)
    return fr.text.strip()


def fetch_document_text(source_url: str, doc_type: str = "agenda") -> str:
    """Downloads a PDF, HTML page, or CivicClerk event stream and returns clean plain text."""
    url = (source_url or "").strip()
    if not url:
        return ""

    cc_match = CIVICCLERK_EVENT_RE.match(url)
    if cc_match:
        slug, event_id = cc_match.group(1), cc_match.group(2)
        text = _fetch_civicclerk_event_text(slug, event_id, doc_type)
        return text[:MAX_RAW_TEXT_CHARS]

    resp = requests.get(
        url,
        headers=SETTINGS.headers,
        timeout=max(30, SETTINGS.request_timeout),
        allow_redirects=True,
    )
    resp.raise_for_status()
    ctype = (resp.headers.get("Content-Type") or "").lower()

    if "application/pdf" in ctype or resp.content[:5] == b"%PDF-" or url.lower().endswith(".pdf"):
        text = _extract_pdf_text(resp.content)
    elif "text/plain" in ctype:
        text = resp.text.strip()
    else:
        text = _extract_html_text(resp.text)

    return text[:MAX_RAW_TEXT_CHARS]


def _match_entity_id(voter_name: str, entities: List[Dict[str, str]]) -> Optional[str]:
    """Matches an extracted voter name to a real ocd_person_id in entities (exact or unique surname)."""
    target = re.sub(r"[^a-z\s]", "", (voter_name or "").lower()).strip()
    if not target:
        return None

    for ent in entities:
        ename = re.sub(r"[^a-z\s]", "", (ent["name"] or "").lower()).strip()
        if ename == target:
            return ent["ocd_person_id"]

    target_last = target.split()[-1]
    if len(target_last) < 3:
        return None
    surname_hits = [
        ent["ocd_person_id"]
        for ent in entities
        if re.sub(r"[^a-z\s]", "", (ent["name"] or "").lower()).strip().split()[-1:] == [target_last]
    ]
    return surname_hits[0] if len(surname_hits) == 1 else None


def _is_pivotal_vote(vote_val: str, outcome: str, yes_count: int, no_count: int) -> int:
    v = (vote_val or "").strip().lower()
    passed = bool(re.match(r"^(passed|adopted|approved)", (outcome or "").strip(), re.IGNORECASE))
    if passed and v == "yes" and (yes_count - no_count) <= 2:
        return 1
    if not passed and v == "no" and (no_count - yes_count) <= 1:
        return 1
    return 0


def _normalize_vote_value(raw: str) -> str:
    low = (raw or "").strip().lower()
    if low in ("yes", "aye", "yea", "for", "approve", "approved"):
        return "Yes"
    if low in ("no", "nay", "against", "opposed"):
        return "No"
    if low in ("abstain", "recused", "recuse", "present"):
        return "Abstain"
    return "Absent"


def _call_ollama_extract(
    raw_text: str,
    title: str,
    roster_names: List[str],
) -> List[Dict[str, Any]]:
    roster_hint = ", ".join(roster_names) if roster_names else "Unknown"
    prompt = (
        "You are a neutral, nonpartisan civic records extractor.\n"
        "Given the meeting document text below, extract ONLY formal legislative actions, ordinances, "
        "resolutions, budget votes, or motions actually present in the text. Do NOT invent items or votes.\n"
        "Return ONLY valid JSON with key 'events' containing a list of objects with keys:\n"
        "- title (string)\n"
        "- event_type ('ordinance'|'resolution'|'budget'|'motion'|'consent')\n"
        "- topic (short category e.g. 'Housing', 'Budget', 'Transit', 'Zoning', 'General')\n"
        "- outcome ('Passed'|'Failed'|'Tabled'|'Recorded')\n"
        "- yes_count (int), no_count (int), abstain_count (int), absent_count (int)\n"
        "- plain_summary (1-2 neutral plain-English sentences explaining what this does for residents)\n"
        "- diff_summary (brief note on what changed from prior policy, or empty string)\n"
        "- votes (optional list of objects with keys: name, vote ('Yes'|'No'|'Abstain'|'Absent'), "
        "rationale_summary, verbatim_quote — include ONLY if individual roll-call votes appear in the text)\n\n"
        f"KNOWN ROSTER: {roster_hint}\n"
        f"DOCUMENT TITLE: {title}\n"
        f"TEXT:\n{raw_text[:LLM_PROMPT_CHARS]}"
    )
    resp = requests.post(
        SETTINGS.ollama_url,
        json={"model": SETTINGS.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
        timeout=120,
    )
    resp.raise_for_status()
    payload = json.loads(resp.json().get("response", "{}"))
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return events if isinstance(events, list) else []


def run_worker(
    db_path: Optional[str] = None,
    limit: int = 10,
    max_retries: int = 3,
    jurisdiction_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    fetch_only: bool = False,
    requeue_skipped: bool = False,
) -> Dict[str, int]:
    """Fetches missing document text (PDF/HTML/CivicClerk) and extracts structured votes via local Ollama."""
    init_db(db_path)
    conn = get_connection(db_path)
    stats = {
        "fetched": 0,
        "processed": 0,
        "events_created": 0,
        "votes_created": 0,
        "failed": 0,
        "skipped": 0,
    }
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        if requeue_skipped:
            conn.execute(
                "UPDATE documents SET status = 'pending', error_message = NULL WHERE status = 'skipped'"
            )
            conn.commit()

        where_clauses = ["status = 'pending'", "COALESCE(retry_count, 0) < ?"]
        params: List[Any] = [max_retries]
        if jurisdiction_id:
            where_clauses.append("jurisdiction_id = ?")
            params.append(jurisdiction_id)
        if doc_type:
            where_clauses.append("LOWER(doc_type) = ?")
            params.append(doc_type.lower())
        params.append(limit)

        # Prioritize minutes over agendas since minutes contain final roll-call tallies
        query = f"""
            SELECT * FROM documents
            WHERE {' AND '.join(where_clauses)}
            ORDER BY CASE WHEN LOWER(doc_type) = 'minutes' THEN 0 ELSE 1 END,
                     meeting_date DESC,
                     doc_id ASC
            LIMIT ?
        """
        docs = conn.execute(query, params).fetchall()

        roster_cache: Dict[str, List[Dict[str, str]]] = {}

        for doc in docs:
            doc_id = doc["doc_id"]
            div_id = doc["jurisdiction_id"]
            raw_text = (doc["raw_text"] or "").strip()

            # Step 1: Fetch & cache raw_text if not already downloaded
            if not raw_text:
                try:
                    raw_text = fetch_document_text(doc["source_url"] or "", doc["doc_type"] or "agenda")
                    if raw_text:
                        conn.execute(
                            "UPDATE documents SET raw_text = ?, error_message = NULL WHERE doc_id = ?",
                            (raw_text, doc_id),
                        )
                        conn.commit()
                        stats["fetched"] += 1
                except Exception as exc:
                    retries = int(doc["retry_count"] or 0) + 1
                    new_status = "failed" if retries >= max_retries else "pending"
                    conn.execute(
                        "UPDATE documents SET status = ?, retry_count = ?, error_message = ? WHERE doc_id = ?",
                        (new_status, retries, f"Fetch error: {exc}"[:300], doc_id),
                    )
                    conn.commit()
                    stats["failed"] += 1
                    print(f"[WORK][WARN] doc_id={doc_id} fetch failed: {exc}")
                    continue

            if len(raw_text) < 120:
                conn.execute(
                    "UPDATE documents SET status = 'skipped', error_message = 'Insufficient text (<120 chars)', processed_at = ? WHERE doc_id = ?",
                    (now_iso, doc_id),
                )
                conn.commit()
                stats["skipped"] += 1
                continue

            if fetch_only:
                print(f"[WORK][FETCH] doc_id={doc_id} ({doc['doc_type']}): cached {len(raw_text):,} chars")
                continue

            # Step 2: Load jurisdiction roster once for roll-call matching
            if div_id not in roster_cache:
                rows = conn.execute(
                    "SELECT ocd_person_id, name FROM entities WHERE jurisdiction_id = ? AND active = 1",
                    (div_id,),
                ).fetchall()
                roster_cache[div_id] = [dict(r) for r in rows]
            roster = roster_cache[div_id]

            # Step 3: Extract events & roll-call votes via local Ollama
            try:
                extracted = _call_ollama_extract(
                    raw_text=raw_text,
                    title=doc["title"] or "",
                    roster_names=[r["name"] for r in roster],
                )
                for idx, ev in enumerate(extracted):
                    ev_title = (ev.get("title") or "").strip()
                    if not ev_title:
                        continue
                    yes_c = int(ev.get("yes_count") or 0)
                    no_c = int(ev.get("no_count") or 0)
                    abs_c = int(ev.get("abstain_count") or 0)
                    miss_c = int(ev.get("absent_count") or 0)
                    ev_type = (ev.get("event_type") or "ordinance").strip().lower()
                    outcome = (ev.get("outcome") or "Recorded").strip()
                    plain_sum = (ev.get("plain_summary") or "").strip()
                    diff_sum = (ev.get("diff_summary") or "").strip()
                    impact = compute_impact_score(ev_title, ev_type, yes_c, no_c, plain_sum)

                    ev_hash = hashlib.sha1(
                        f"{div_id}|{doc['meeting_date']}|{ev_title}|{idx}".encode("utf-8")
                    ).hexdigest()[:14]
                    event_id = f"ev_{ev_hash}"

                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO events
                        (event_id, jurisdiction_id, doc_id, meeting_date, title, plain_summary, diff_summary,
                         qa_status, event_type, topic, outcome, yes_count, no_count, abstain_count,
                         absent_count, vote_margin, impact_score, source_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            div_id,
                            doc_id,
                            doc["meeting_date"] or now_iso[:10],
                            ev_title,
                            plain_sum,
                            diff_sum,
                            ev_type,
                            (ev.get("topic") or "General").strip(),
                            outcome,
                            yes_c,
                            no_c,
                            abs_c,
                            miss_c,
                            abs(yes_c - no_c),
                            impact,
                            doc["source_url"],
                        ),
                    )
                    if cur.rowcount > 0:
                        stats["events_created"] += 1

                    # Insert individual roll-call votes matched to verified entities
                    for v in ev.get("votes") or []:
                        person_id = _match_entity_id(v.get("name") or "", roster)
                        if not person_id:
                            continue
                        vote_val = _normalize_vote_value(v.get("vote") or "")
                        pivotal = _is_pivotal_vote(vote_val, outcome, yes_c, no_c)
                        vcur = conn.execute(
                            """
                            INSERT OR IGNORE INTO entity_actions
                            (event_id, entity_id, action_type, value, is_pivotal, rationale_summary, verbatim_quote, timestamp)
                            VALUES (?, ?, 'vote', ?, ?, ?, ?, ?)
                            """,
                            (
                                event_id,
                                person_id,
                                vote_val,
                                pivotal,
                                (v.get("rationale_summary") or "").strip(),
                                (v.get("verbatim_quote") or "").strip(),
                                now_iso,
                            ),
                        )
                        if vcur.rowcount > 0:
                            stats["votes_created"] += 1

                conn.execute(
                    "UPDATE documents SET status = 'processed', processed_at = ?, error_message = NULL WHERE doc_id = ?",
                    (now_iso, doc_id),
                )
                conn.commit()
                stats["processed"] += 1
                print(
                    f"[WORK] doc_id={doc_id} ({doc['meeting_date']}): "
                    f"extracted {len(extracted)} event(s)"
                )
            except Exception as exc:
                retries = int(doc["retry_count"] or 0) + 1
                new_status = "failed" if retries >= max_retries else "pending"
                conn.execute(
                    "UPDATE documents SET status = ?, retry_count = ?, error_message = ? WHERE doc_id = ?",
                    (new_status, retries, f"LLM error: {exc}"[:300], doc_id),
                )
                conn.commit()
                stats["failed"] += 1
                print(f"[WORK][WARN] doc_id={doc_id} LLM extraction failed: {exc}")

        return stats
    finally:
        conn.close()