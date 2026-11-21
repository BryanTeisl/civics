"""
Dual-Path Watcher.
Routes all 6 platform families via adapters/dispatcher.py:
  - PDFs -> queued in `documents` for RTX 2060 worker.py
  - Structured JSON votes -> written straight to `events` & `entity_actions` with live metrics
"""
from datetime import datetime, timezone
from db import get_connection, init_db, queue_document
from adapters.dispatcher import dispatch_jurisdiction
from metrics import compute_vote_impactfulness, is_vote_pivotal


def _slugify_person(jurisdiction_id: str, name: str) -> str:
    city_slug = jurisdiction_id.split(":")[-1]
    name_slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    return f"ocd-person/{city_slug}-{name_slug}"


def save_structured_events(jurisdiction_id: str, events: list) -> int:
    conn = get_connection()
    cur = conn.cursor()
    saved = 0

    for ev in events:
        yes_c = sum(1 for v in ev.votes if v.vote == "Yes")
        no_c = sum(1 for v in ev.votes if v.vote == "No")
        abs_c = sum(1 for v in ev.votes if v.vote == "Abstain")
        absent_c = sum(1 for v in ev.votes if v.vote == "Absent")
        impact_score, margin, _ = compute_vote_impactfulness(yes_c, no_c, ev.event_type)

        cur.execute("""
            INSERT OR REPLACE INTO events
            (event_id, jurisdiction_id, meeting_date, title, event_type, topic,
             outcome, yes_count, no_count, abstain_count, absent_count,
             vote_margin, impact_score, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ev.event_id, jurisdiction_id, ev.meeting_date, ev.title, ev.event_type,
            ev.topic, ev.outcome, yes_c, no_c, abs_c, absent_c, margin,
            impact_score, ev.source_url,
        ))

        for v in ev.votes:
            person_id = _slugify_person(jurisdiction_id, v.person_name)
            # Auto-register official if not yet seeded
            cur.execute("""
                INSERT OR IGNORE INTO entities
                (ocd_person_id, jurisdiction_id, name, entity_type, role)
                VALUES (?, ?, ?, 'legislator', 'Councilmember')
            """, (person_id, jurisdiction_id, v.person_name))

            pivotal = is_vote_pivotal(v.vote, yes_c, no_c)
            cur.execute("""
                INSERT OR REPLACE INTO entity_actions
                (event_id, entity_id, action_type, value, is_pivotal, rationale_summary)
                VALUES (?, ?, 'vote', ?, ?, ?)
            """, (ev.event_id, person_id, v.vote, pivotal, v.rationale_summary))

        saved += 1

    conn.commit()
    conn.close()
    return saved


def run_watcher_cycle(tier: str = "fast") -> None:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM jurisdictions WHERE poll_tier = ?", (tier,)).fetchall()
    conn.close()

    total_docs, total_events = 0, 0
    for j in rows:
        print(f"[WATCH] {j['name']} ({j['adapter_type']})...")
        try:
            result = dispatch_jurisdiction(j["adapter_type"], j["portal_url"], days_back=30)

            for doc in result.documents:
                if queue_document(
                    j["ocd_division_id"], doc.external_id, doc.meeting_date,
                    doc.doc_type, doc.title, doc.source_url, doc.raw_text,
                ):
                    total_docs += 1

            if result.events:
                saved = save_structured_events(j["ocd_division_id"], result.events)
                total_events += saved
                print(f"  + Saved {saved} structured vote events (GPU bypassed).")

            conn = get_connection()
            conn.execute(
                "UPDATE jurisdictions SET last_polled_at = ? WHERE ocd_division_id = ?",
                (datetime.now(timezone.utc).isoformat(), j["ocd_division_id"]),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"  ! Error polling {j['name']}: {exc}")

    print(f"Watcher complete. Queued PDFs: {total_docs} | Structured Vote Events: {total_events}")


if __name__ == "__main__":
    init_db()
    run_watcher_cycle(tier="fast")