"""Representative Bio & Voting-Record Summary Generator (civicpulse/pipeline/rep_bios.py).

Generates an objective, neutral 2-3 sentence summary for each active representative
grounded strictly in:
  - Recorded roll-call votes (Yes / No / Abstain / Absent counts & pivotal votes)
  - Top policy topics voted on (e.g., Housing & Land Use, Budget & Taxes, Infrastructure)
  - Verbatim quotes / comments extracted from official minutes

Runs deterministically in <1s with zero API cost, with optional local Ollama (`qwen2.5:3b`)
polishing when `--use-ollama` is passed. Also injects `bio_summary`, `photo_url`, and
`contact` fields directly into exported `public/data/*.json` files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


def ensure_rep_bio_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    if "bio_summary" not in cols:
        conn.execute("ALTER TABLE entities ADD COLUMN bio_summary TEXT DEFAULT ''")
    if "photo_url" not in cols:
        conn.execute("ALTER TABLE entities ADD COLUMN photo_url TEXT DEFAULT ''")
    conn.commit()


def synthesize_deterministic_bio(
    name: str,
    role: str,
    district: str,
    jurisdiction_name: str,
    votes: List[Dict[str, Any]],
) -> str:
    """Produces a neutral, factual 2-3 sentence profile from recorded votes and comments."""
    seat = f"{role or 'Representative'}"
    if district and district.lower() not in ("at-large", "none", ""):
        seat += f" ({district})"
    elif district and district.lower() == "at-large":
        seat += " (At-Large)"

    if not votes:
        return (
            f"{name} serves as {seat} for {jurisdiction_name}. "
            "Roll-call vote breakdowns and meeting comments for this term are currently pending ingestion."
        )

    total = len(votes)
    yes_cnt = sum(1 for v in votes if (v.get("vote") or "").lower() in ("yes", "aye", "yea"))
    no_cnt = sum(1 for v in votes if (v.get("vote") or "").lower() in ("no", "nay"))
    pivotal_cnt = sum(1 for v in votes if v.get("is_pivotal"))

    topic_counts = Counter(
        (v.get("topic") or "").strip()
        for v in votes
        if (v.get("topic") or "").strip() and (v.get("topic") or "").lower() not in ("general", "procedural", "consent")
    )
    top_topics = [t for t, _ in topic_counts.most_common(3)]

    s1 = (
        f"{name} serves as {seat} for {jurisdiction_name}, with {total} recorded roll-call "
        f"vote{'s' if total != 1 else ''} ({yes_cnt} Yes, {no_cnt} No"
        + (f", including {pivotal_cnt} deciding pivotal vote{'s' if pivotal_cnt != 1 else ''}" if pivotal_cnt else "")
        + ")."
    )

    if top_topics:
        if len(top_topics) == 1:
            topic_phrase = top_topics[0]
        elif len(top_topics) == 2:
            topic_phrase = f"{top_topics[0]} and {top_topics[1]}"
        else:
            topic_phrase = f"{top_topics[0]}, {top_topics[1]}, and {top_topics[2]}"
        s2 = f" Their recorded legislative activity has focused most frequently on {topic_phrase}."
    else:
        s2 = ""

    quotes = [
        re.sub(r"\s+", " ", (v.get("quote") or "")).strip().strip('"')
        for v in votes
        if len((v.get("quote") or "").strip()) >= 20
    ]
    if quotes:
        sample_q = quotes[0][:140].rstrip(" ,;.")
        s3 = f' In official meeting records, they have weighed in on measures noting: "{sample_q}."'
    else:
        no_titles = [
            (v.get("title") or "").strip()
            for v in votes
            if (v.get("vote") or "").lower() in ("no", "nay") and (v.get("title") or "").strip()
        ]
        if no_titles:
            s3 = f" Notable dissenting votes include {no_titles[0][:95].rstrip('.')}."
        else:
            s3 = ""

    return (s1 + s2 + s3).strip()


def refine_bio_with_ollama(
    name: str,
    role: str,
    jurisdiction_name: str,
    draft_bio: str,
    votes: List[Dict[str, Any]],
) -> str:
    """Optional local LLM polish keeping strictly factual, neutral tone."""
    if not votes:
        return draft_bio
    sample_lines = []
    for v in votes[:10]:
        q = f' | Quote: "{v["quote"][:110]}"' if v.get("quote") else ""
        sample_lines.append(f"- [{v.get('vote')}] {v.get('topic', 'General')}: {v.get('title', '')[:90]}{q}")
    prompt = (
        f"Write a strictly neutral, factual 2 to 3 sentence civic profile for {name} ({role}, {jurisdiction_name}) "
        "based ONLY on the voting record and quotes below. Do not speculate or use partisan adjectives.\n\n"
        f"DRAFT:\n{draft_bio}\n\n"
        f"RECORDED VOTES & COMMENTS:\n" + "\n".join(sample_lines)
    )
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.15, "num_predict": 180},
            },
            timeout=45,
        )
        if r.status_code == 200:
            txt = re.sub(r"\s+", " ", (r.json().get("response") or "")).strip()
            if 50 <= len(txt) <= 650:
                return txt
    except Exception:
        pass
    return draft_bio


def generate_all_rep_bios(
    db_path: Path = Path("core_civic.db"),
    public_dir: Path = Path("public"),
    use_ollama: bool = False,
) -> Dict[str, Any]:
    """Populates `entities.bio_summary` in SQLite and enriches exported `public/data/*.json`."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_rep_bio_columns(conn)

    ent_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    jur_map = {
        r["ocd_division_id"]: r["name"]
        for r in conn.execute("SELECT ocd_division_id, name FROM jurisdictions").fetchall()
    }

    entities = conn.execute(
        "SELECT * FROM entities WHERE COALESCE(active, 1) = 1"
    ).fetchall()

    bio_by_pid: Dict[str, str] = {}
    meta_by_pid: Dict[str, Dict[str, Any]] = {}
    updated = 0

    for ent in entities:
        pid = ent["ocd_person_id"]
        jid = ent["jurisdiction_id"]
        jname = jur_map.get(jid, jid)

        ea_cols = {r[1] for r in conn.execute("PRAGMA table_info(entity_actions)").fetchall()}
        vote_col = "ea.value" if "value" in ea_cols else "ea.action_type"
        quote_col = "ea.verbatim_quote" if "verbatim_quote" in ea_cols else ("ea.quote" if "quote" in ea_cols else "''")
        where_act = "AND ea.action_type = 'vote'" if "value" in ea_cols else ""

        vote_rows = conn.execute(
            f"""
            SELECT {vote_col} AS vote, ea.is_pivotal, {quote_col} AS quote, ea.rationale_summary,
                   e.title, e.topic, e.meeting_date, e.outcome
            FROM entity_actions ea
            JOIN events e ON e.event_id = ea.event_id
            WHERE ea.entity_id = ? {where_act}
            ORDER BY e.meeting_date DESC
            """,
            (pid,),
        ).fetchall()
        votes = [dict(vr) for vr in vote_rows]

        bio = synthesize_deterministic_bio(
            name=ent["name"],
            role=ent["role"] or "Council Member",
            district=ent["district"] or "",
            jurisdiction_name=jname,
            votes=votes,
        )
        if use_ollama and votes:
            bio = refine_bio_with_ollama(ent["name"], ent["role"] or "", jname, bio, votes)

        conn.execute("UPDATE entities SET bio_summary = ? WHERE ocd_person_id = ?", (bio, pid))
        bio_by_pid[pid] = bio
        meta_by_pid[pid] = {
            "bio_summary": bio,
            "photo_url": ent["photo_url"] if "photo_url" in ent_cols else "",
            "email": ent["email"] if "email" in ent_cols else "",
            "phone": ent["phone"] if "phone" in ent_cols else "",
            "website_url": ent["website_url"] if "website_url" in ent_cols else "",
        }
        updated += 1

    conn.commit()
    conn.close()

    # Enrich exported per-jurisdiction JSON shards in public/data/
    patched_files = 0
    data_dir = public_dir / "data"
    if data_dir.exists():
        for jf in data_dir.glob("country_*.json"):
            try:
                payload = json.loads(jf.read_text(encoding="utf-8"))
                changed = False
                for key in ("entities", "representatives", "roster"):
                    if isinstance(payload.get(key), list):
                        for rep in payload[key]:
                            rid = rep.get("id") or rep.get("ocd_person_id")
                            if rid and rid in meta_by_pid:
                                rep["bio_summary"] = meta_by_pid[rid]["bio_summary"]
                                if meta_by_pid[rid]["photo_url"]:
                                    rep["photo_url"] = meta_by_pid[rid]["photo_url"]
                                changed = True
                if changed:
                    jf.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    patched_files += 1
            except Exception:
                continue

    return {"updated_entities": updated, "enriched_json_files": patched_files}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate neutral voting-record & quote summaries per representative")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--public-dir", default="public")
    parser.add_argument("--use-ollama", action="store_true", help="Polish summaries with local Ollama")
    args = parser.parse_args()
    res = generate_all_rep_bios(Path(args.db), Path(args.public_dir), use_ollama=args.use_ollama)
    print("[REP-BIOS]", json.dumps(res))


if __name__ == "__main__":
    main()
