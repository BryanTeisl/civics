from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from civicpulse.db import get_connection, init_db


def is_due(last_ts: Optional[str], min_days: int, now: Optional[datetime] = None) -> bool:
    """Returns True if min_days <= 0, last_ts is missing/unparseable, or at least min_days have elapsed."""
    if min_days <= 0 or not last_ts:
        return True
    ref_now = now or datetime.now(timezone.utc)
    try:
        raw = last_ts.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (ref_now - dt).total_seconds() >= (min_days * 86400)
    except Exception:
        return True


def get_due_watch_jurisdictions(
    db_path: Optional[str] = None,
    min_interval_days: int = 0,
    jurisdiction_id: Optional[str] = None,
    force: bool = False,
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Returns (due_jurisdictions, skipped_names) for active jurisdictions based on last_polled_at."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        query = "SELECT ocd_division_id, name, last_polled_at FROM jurisdictions WHERE status = 'active'"
        params: List[Any] = []
        if jurisdiction_id:
            query += " AND ocd_division_id = ?"
            params.append(jurisdiction_id)
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    due: List[Dict[str, str]] = []
    skipped: List[str] = []
    for r in rows:
        if force or min_interval_days <= 0 or is_due(r["last_polled_at"], min_interval_days):
            due.append({"ocd_division_id": r["ocd_division_id"], "name": r["name"]})
        else:
            skipped.append(r["name"])
    return due, skipped


def compute_work_batch_limit(
    db_path: Optional[str] = None,
    limit: int = 10,
    jurisdiction_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    pct_per_day: Optional[float] = None,
    max_per_day: Optional[int] = None,
) -> Dict[str, int]:
    """Computes effective batch size from pending backlog, pct_per_day, and max_per_day."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        where = ["status = 'pending'"]
        params: List[Any] = []
        if jurisdiction_id:
            where.append("jurisdiction_id = ?")
            params.append(jurisdiction_id)
        if doc_type:
            where.append("LOWER(doc_type) = LOWER(?)")
            params.append(doc_type)

        pending_total = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE {' AND '.join(where)}",
            params,
        ).fetchone()[0]

        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        done_where = ["status = 'processed'", "processed_at LIKE ?"]
        done_params: List[Any] = [f"{today_prefix}%"]
        if jurisdiction_id:
            done_where.append("jurisdiction_id = ?")
            done_params.append(jurisdiction_id)
        if doc_type:
            done_where.append("LOWER(doc_type) = LOWER(?)")
            done_params.append(doc_type)

        done_today = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE {' AND '.join(done_where)}",
            done_params,
        ).fetchone()[0]
    finally:
        conn.close()

    effective = max(0, limit)
    if pct_per_day is not None and pct_per_day > 0:
        pct_cap = max(1, math.ceil(pending_total * (pct_per_day / 100.0))) if pending_total > 0 else 0
        effective = min(effective, pct_cap)

    if max_per_day is not None and max_per_day > 0:
        remaining_today = max(0, max_per_day - done_today)
        effective = min(effective, remaining_today)

    return {
        "pending_total": int(pending_total),
        "done_today": int(done_today),
        "effective_limit": int(max(0, effective)),
    }
