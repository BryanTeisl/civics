import re
import sqlite3
from pathlib import Path

DB_PATH = Path("core_civic.db")
WATCHER_PATH = Path("watcher.py")

LEGACY_UNCLAIMED_ADAPTERS = ("civicplus", "primegov", "granicus", "boarddocs")


def mark_legacy_test_jurisdictions_unclaimed() -> None:
    if not DB_PATH.exists():
        print("core_civic.db not found; skipping DB cleanup.")
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """
            UPDATE jurisdictions
            SET status = 'unclaimed'
            WHERE adapter_type IN ('civicplus', 'primegov', 'granicus', 'boarddocs')
              AND (
                  SELECT COUNT(*) FROM events WHERE events.jurisdiction_id = jurisdictions.ocd_division_id
              ) = 0
            """
        )
        conn.commit()
        print(f"Marked {cur.rowcount} inactive test jurisdiction(s) as 'unclaimed' in {DB_PATH}.")
    finally:
        conn.close()


def patch_watcher_active_filter() -> None:
    if not WATCHER_PATH.exists():
        print("watcher.py not found in current directory; skipping watcher patch.")
        return

    src = WATCHER_PATH.read_text(encoding="utf-8")
    if "status = 'active'" in src or "status IS NULL OR status = 'active'" in src:
        print("watcher.py already filters for active jurisdictions.")
        return

    # Patch standard SELECT * FROM jurisdictions query
    pattern = re.compile(r"SELECT\s+\*\s+FROM\s+jurisdictions(?!\s+WHERE)", re.IGNORECASE)
    new_src, count = pattern.subn(
        "SELECT * FROM jurisdictions WHERE (status IS NULL OR status = 'active')",
        src,
        count=1,
    )
    if count > 0:
        WATCHER_PATH.write_text(new_src, encoding="utf-8")
        print("Patched watcher.py to poll ONLY active jurisdictions.")
    else:
        print("Could not auto-locate 'SELECT * FROM jurisdictions' in watcher.py; add WHERE (status IS NULL OR status = 'active') manually.")


if __name__ == "__main__":
    mark_legacy_test_jurisdictions_unclaimed()
    patch_watcher_active_filter()
