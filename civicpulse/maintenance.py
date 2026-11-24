from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from civicpulse.adapters import get_adapter
from civicpulse.agents.scout import build_ocd_id, probe_portal
from civicpulse.db import get_connection, init_db


def load_jurisdiction_config(config_path: Path) -> List[Dict[str, Any]]:
    return json.loads(Path(config_path).read_text(encoding="utf-8"))


def seed_from_config(
    config_path: Path,
    activate_structured: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, int]:
    """Declaratively seeds jurisdictions from a JSON config file without one-off scripts."""
    init_db(db_path)
    items = load_jurisdiction_config(config_path)
    conn = get_connection(db_path)
    inserted = 0
    updated = 0
    try:
        for item in items:
            div_id = item.get("ocd_division_id") or build_ocd_id(
                item["name"], item.get("state", "CO"), item.get("level", "city")
            )
            adapter_type = (item.get("adapter_type") or item.get("platform") or "unclaimed").lower()
            adapter = get_adapter(adapter_type)
            norm_url = adapter.normalize_portal_url(item.get("portal_url", "")) if adapter else item.get("portal_url", "")
            is_structured = bool(adapter and adapter.is_structured)
            desired_status = "active" if (activate_structured and is_structured) else item.get("status", "unclaimed")

            existing = conn.execute(
                "SELECT status FROM jurisdictions WHERE ocd_division_id = ?", (div_id,)
            ).fetchone()
            if existing:
                if (existing["status"] or "").lower() == "active":
                    continue
                conn.execute(
                    """
                    UPDATE jurisdictions
                    SET name = ?, level = ?, lat = COALESCE(?, lat), lng = COALESCE(?, lng),
                        portal_url = ?, adapter_type = ?, status = ?
                    WHERE ocd_division_id = ?
                    """,
                    (
                        item["name"],
                        item.get("level", "city"),
                        item.get("lat"),
                        item.get("lng"),
                        norm_url,
                        adapter_type,
                        desired_status,
                        div_id,
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO jurisdictions
                    (ocd_division_id, name, level, lat, lng, portal_url, adapter_type, poll_tier, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'standard', ?)
                    """,
                    (
                        div_id,
                        item["name"],
                        item.get("level", "city"),
                        item.get("lat", 0.0),
                        item.get("lng", 0.0),
                        norm_url,
                        adapter_type,
                        desired_status,
                    ),
                )
                inserted += 1
        conn.commit()
        return {"inserted": inserted, "updated": updated}
    finally:
        conn.close()


def probe_config(config_path: Path, year: Optional[int] = None) -> List[Dict[str, Any]]:
    target_year = year or datetime.now(timezone.utc).year
    items = load_jurisdiction_config(config_path)
    results = []
    for item in items:
        res = probe_portal(
            portal_url=item.get("portal_url", ""),
            year=target_year,
            preferred_adapter=item.get("adapter_type") or item.get("platform"),
        )
        results.append(
            {
                "name": item["name"],
                "adapter_type": res.adapter_type,
                "ok": res.ok,
                "status_code": res.status_code,
                "item_count": res.item_count,
                "sample_title": res.sample_title,
                "portal_url": res.normalized_portal_url,
            }
        )
    return results
