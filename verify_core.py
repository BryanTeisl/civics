import json
from pathlib import Path
from db import DB_PATH, get_connection, init_db


def verify_core_state(db_path: str = DB_PATH) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        jurs = conn.execute(
            "SELECT ocd_division_id, name, level, adapter_type, status, last_polled_at FROM jurisdictions ORDER BY status, name"
        ).fetchall()
        print("=== JURISDICTIONS IN DB ===")
        for j in jurs:
            rep_cnt = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE jurisdiction_id = ? AND active = 1",
                (j["ocd_division_id"],),
            ).fetchone()[0]
            doc_cnt = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE jurisdiction_id = ?",
                (j["ocd_division_id"],),
            ).fetchone()[0]
            ev_cnt = conn.execute(
                "SELECT COUNT(*) FROM events WHERE jurisdiction_id = ?",
                (j["ocd_division_id"],),
            ).fetchone()[0]
            print(
                f"  [{j['status'] or 'active':9s}] {j['name']:42s} | adapter={j['adapter_type']:10s} | "
                f"reps={rep_cnt:2d} | docs={doc_cnt:3d} | events={ev_cnt:3d}"
            )

        pending_docs = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE LOWER(COALESCE(status, 'pending')) = 'pending'"
        ).fetchone()[0]
        print(f"\nPending documents awaiting worker/extraction: {pending_docs}")

        idx_path = Path("public/data/index.json")
        if idx_path.exists():
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            print(f"Exported index.json: {len(idx.get('jurisdictions', []))} jurisdictions, {len(idx.get('search_index', []))} search events.")
        else:
            print("WARNING: public/data/index.json not found yet — run exporter.py.")
    finally:
        conn.close()


if __name__ == "__main__":
    verify_core_state()
