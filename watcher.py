"""
CPU-Only Tiered Watcher.
Polls configured jurisdictions based on poll_tier ('fast' vs 'slow'),
hashes new agendas/minutes, and queues only changed documents in SQLite.
"""
import time
from datetime import datetime
from db import get_connection, init_db, seed_fort_collins, queue_document
from adapters.civicclerk import CivicClerkAdapter
from adapters.legistar import LegistarAdapter

ADAPTER_MAP = {
    "civicclerk": CivicClerkAdapter,
    "legistar": LegistarAdapter,
}


def run_watcher_cycle(tier: str = "fast") -> int:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jurisdictions WHERE poll_tier = ?", (tier,)
    ).fetchall()
    conn.close()

    queued_count = 0
    for j in rows:
        adapter_cls = ADAPTER_MAP.get(j["adapter_type"])
        if not adapter_cls:
            print(f"[SKIP] No adapter registered for {j['adapter_type']} ({j['name']})")
            continue

        print(f"[WATCH] Polling {j['name']} via {j['adapter_type']}...")
        try:
            adapter = adapter_cls(j["portal_url"])
            docs = adapter.fetch_recent_documents(days_back=30)
            for doc in docs:
                added = queue_document(
                    jurisdiction_id=j["ocd_division_id"],
                    external_id=doc.external_id,
                    meeting_date=doc.meeting_date,
                    doc_type=doc.doc_type,
                    title=doc.title,
                    source_url=doc.source_url,
                    raw_text=doc.raw_text,
                )
                if added:
                    queued_count += 1
                    print(f"  + Queued new {doc.doc_type}: {doc.title}")

            conn = get_connection()
            conn.execute(
                "UPDATE jurisdictions SET last_polled_at = ? WHERE ocd_division_id = ?",
                (datetime.utcnow().isoformat(), j["ocd_division_id"]),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"  ! Error polling {j['name']}: {exc}")

    return queued_count


if __name__ == "__main__":
    init_db()
    seed_fort_collins()
    added = run_watcher_cycle(tier="fast")
    print(f"Watcher cycle complete. Newly queued documents: {added}")
