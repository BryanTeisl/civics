from datetime import datetime, timedelta, timezone

from civicpulse.db import get_connection, init_db
from civicpulse.pipeline.cadence import compute_work_batch_limit, get_due_watch_jurisdictions, is_due


def test_is_due_handles_intervals_and_missing():
    now = datetime.now(timezone.utc)
    assert is_due(None, 90, now=now) is True
    assert is_due((now - timedelta(days=10)).isoformat(), 90, now=now) is False
    assert is_due((now - timedelta(days=91)).isoformat(), 90, now=now) is True
    assert is_due((now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"), 7, now=now) is False
    assert is_due((now - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), 7, now=now) is True
    assert is_due((now - timedelta(days=1)).isoformat(), 0, now=now) is True


def test_due_watch_jurisdictions_respects_weekly_interval(tmp_path):
    db_file = str(tmp_path / "cadence.db")
    init_db(db_file)
    conn = get_connection(db_file)
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO jurisdictions (ocd_division_id, name, level, lat, lng, adapter_type, portal_url, status, last_polled_at)
        VALUES (?, ?, 'municipal', 40.0, -105.0, 'legistar', 'https://a.legistar.com/', 'active', ?)
        """,
        ("ocd-division/country:us/state:co/place:recent", "Recent City", (now - timedelta(days=2)).isoformat()),
    )
    conn.execute(
        """
        INSERT INTO jurisdictions (ocd_division_id, name, level, lat, lng, adapter_type, portal_url, status, last_polled_at)
        VALUES (?, ?, 'municipal', 40.0, -105.0, 'legistar', 'https://b.legistar.com/', 'active', ?)
        """,
        ("ocd-division/country:us/state:co/place:stale", "Stale City", (now - timedelta(days=10)).isoformat()),
    )
    conn.commit()
    conn.close()

    due, skipped = get_due_watch_jurisdictions(db_path=db_file, min_interval_days=7)
    assert [d["name"] for d in due] == ["Stale City"]
    assert skipped == ["Recent City"]


def test_work_batch_limit_enforces_pct_and_daily_cap(tmp_path):
    db_file = str(tmp_path / "caps.db")
    init_db(db_file)
    conn = get_connection(db_file)
    conn.execute(
        """
        INSERT INTO jurisdictions (ocd_division_id, name, level, lat, lng, adapter_type, portal_url, status)
        VALUES ('ocd-division/country:us/state:co/place:test', 'Test City', 'municipal', 40.0, -105.0, 'legistar', 'https://t.legistar.com/', 'active')
        """
    )
    today_iso = datetime.now(timezone.utc).isoformat()
    for i in range(12):
        conn.execute(
            """
            INSERT INTO documents (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, status)
            VALUES ('ocd-division/country:us/state:co/place:test', ?, '2026-11-01', 'minutes', 'City Council Minutes', 'https://example.com', ?, 'pending')
            """,
            (f"p-{i}", f"hash-p-{i}"),
        )
    for i in range(6):
        conn.execute(
            """
            INSERT INTO documents (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, status, processed_at)
            VALUES ('ocd-division/country:us/state:co/place:test', ?, '2026-11-01', 'minutes', 'City Council Minutes', 'https://example.com', ?, 'processed', ?)
            """,
            (f"d-{i}", f"hash-d-{i}", today_iso),
        )
    conn.commit()
    conn.close()

    res = compute_work_batch_limit(db_path=db_file, limit=10, doc_type="minutes", pct_per_day=25, max_per_day=8)
    assert res["pending_total"] == 12
    assert res["done_today"] == 6
    assert res["effective_limit"] == 2
