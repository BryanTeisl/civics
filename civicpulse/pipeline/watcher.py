from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from civicpulse.adapters import get_adapter
from civicpulse.db import get_connection, init_db


def run_watcher(
    db_path: Optional[str] = None,
    year: Optional[int] = None,
    limit_per_jur: int = 25,
    jurisdiction_id: Optional[str] = None,
) -> Dict[str, int]:
    """Polls all active jurisdictions using the unified adapter registry."""
    init_db(db_path)
    target_year = year or datetime.now(timezone.utc).year
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(db_path)
    stats = {"polled": 0, "inserted": 0, "skipped_adapters": 0, "errors": 0}
    try:
        if jurisdiction_id:
            jurs = conn.execute(
                "SELECT * FROM jurisdictions WHERE ocd_division_id = ? AND LOWER(COALESCE(status, 'active')) = 'active'",
                (jurisdiction_id,),
            ).fetchall()
        else:
            jurs = conn.execute(
                "SELECT * FROM jurisdictions WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY name ASC"
            ).fetchall()

        for jur in jurs:
            div_id = jur["ocd_division_id"]
            adapter_name = (jur["adapter_type"] or "").lower()
            adapter = get_adapter(adapter_name)
            if not adapter:
                stats["skipped_adapters"] += 1
                continue

            stats["polled"] += 1
            try:
                docs = adapter.fetch_documents(
                    jurisdiction_id=div_id,
                    portal_url=jur["portal_url"] or "",
                    year=target_year,
                    limit=limit_per_jur,
                )
                for doc in docs:
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO documents
                        (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, raw_text, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                        """,
                        (
                            doc.jurisdiction_id,
                            doc.external_id,
                            doc.meeting_date,
                            doc.doc_type,
                            doc.title,
                            doc.source_url,
                            doc.content_hash,
                            doc.raw_text,
                        ),
                    )
                    if cur.rowcount > 0:
                        stats["inserted"] += 1
                conn.execute(
                    "UPDATE jurisdictions SET last_polled_at = ? WHERE ocd_division_id = ?",
                    (now_iso, div_id),
                )
                conn.commit()
                print(f"[WATCH] {jur['name']} ({adapter_name}): fetched {len(docs)} doc(s)")
            except Exception as exc:
                stats["errors"] += 1
                print(f"[WATCH][WARN] {jur['name']} ({adapter_name}) failed: {exc}")
        return stats
    finally:
        conn.close()
