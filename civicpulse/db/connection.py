from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from civicpulse.config import SETTINGS


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target = db_path or SETTINGS.db_path
    conn = sqlite3.connect(target, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def backup_database(
    db_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
) -> Optional[Path]:
    """Uses SQLite's online backup API to write a clean snapshot outside OneDrive locks."""
    target_dir = backup_dir if backup_dir is not None else SETTINGS.onedrive_backup_dir
    if not target_dir:
        return None
    out_dir = Path(target_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_path = out_dir / f"core_civic_{stamp}.db"

    src = get_connection(db_path)
    dst = sqlite3.connect(str(dest_path))
    try:
        src.backup(dst)
        return dest_path
    finally:
        dst.close()
        src.close()
