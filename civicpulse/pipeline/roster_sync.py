from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from civicpulse.config import SETTINGS
from civicpulse.db import get_connection, init_db
from civicpulse.pipeline.cadence import is_due

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))
COUNCIL_BODY_RE = re.compile(
    r"\b(city council|town council|town board|board of trustees|board of commissioners)\b",
    re.IGNORECASE,
)


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z\s]", "", (name or "").lower()).strip()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _extract_state_code(jurisdiction_id: str) -> str:
    m = re.search(r"state:([a-z]{2})", jurisdiction_id or "", re.IGNORECASE)
    return m.group(1).lower() if m else "us"


def _ensure_roster_columns(conn: Any) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    changed = False
    if "roster_url" not in cols:
        conn.execute("ALTER TABLE jurisdictions ADD COLUMN roster_url TEXT")
        changed = True
    if "last_roster_synced_at" not in cols:
        conn.execute("ALTER TABLE jurisdictions ADD COLUMN last_roster_synced_at TEXT")
        changed = True
    if changed:
        conn.commit()


def _extract_legistar_client(portal_url: str) -> str:
    parsed = urlparse((portal_url or "").strip())
    host = parsed.netloc.lower()
    if host == "webapi.legistar.com":
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "v1":
            return parts[1].lower()
        return parts[0].lower() if parts else ""
    if ".legistar.com" in host:
        return host.split(".legistar.com")[0]
    return host.split(".")[0]


def fetch_legistar_roster(portal_url: str) -> List[Dict[str, str]]:
    """Pulls current elected councilmembers directly from the Legistar Web API (no LLM needed)."""
    client = _extract_legistar_client(portal_url)
    if not client:
        return []

    url = f"https://webapi.legistar.com/v1/{client}/OfficeRecords"
    resp = requests.get(
        url,
        params={"$top": 300, "$orderby": "OfficeRecordStartDate desc"},
        headers=SETTINGS.headers,
        timeout=max(20, SETTINGS.request_timeout),
    )
    if resp.status_code == 500:
        resp = requests.get(
            url,
            params={"$top": 300},
            headers=SETTINGS.headers,
            timeout=max(20, SETTINGS.request_timeout),
        )
    resp.raise_for_status()
    records = resp.json()
    if not isinstance(records, list):
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_name: Dict[str, Dict[str, str]] = {}

    for rec in records:
        body = (rec.get("OfficeRecordBodyName") or "").strip()
        if not COUNCIL_BODY_RE.search(body):
            continue
        end_raw = (rec.get("OfficeRecordEndDate") or "")[:10]
        if end_raw and end_raw < today:
            continue
        name = (rec.get("OfficeRecordFullName") or "").strip()
        if not name or len(name.split()) < 2:
            continue
        key = _norm_name(name)
        if key not in by_name:
            by_name[key] = {
                "name": name,
                "role": (rec.get("OfficeRecordTitle") or "Council Member").strip(),
                "district": (rec.get("OfficeRecordExtraText") or "At-Large").strip(),
                "website_url": portal_url,
            }

    return list(by_name.values())


def _extract_roster_via_ollama(text_chunk: str, jurisdiction_name: str, source_url: str) -> List[Dict[str, str]]:
    """Uses local Ollama to extract sitting elected officials from a council webpage or minutes header."""
    prompt = (
        f"You are extracting the current elected roster for {jurisdiction_name}.\n"
        "From the text below, extract ONLY the sitting elected Mayor, Council Members, "
        "Trustees, or Commissioners. Exclude city managers, clerks, attorneys, staff, and advisory board members.\n"
        "Return ONLY valid JSON with key 'members' containing a list of objects with keys:\n"
        "- name (full name, e.g. 'Jane Doe')\n"
        "- role (e.g. 'Mayor', 'Mayor Pro Tem', 'Council Member')\n"
        "- district (e.g. 'Ward 1', 'District 2', 'At-Large')\n\n"
        f"TEXT:\n{text_chunk[:6000]}"
    )
    resp = requests.post(
        SETTINGS.ollama_url,
        json={
            "model": SETTINGS.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 4096},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    payload = json.loads(resp.json().get("response", "{}"))
    raw_members = payload.get("members", []) if isinstance(payload, dict) else []
    if not isinstance(raw_members, list):
        return []

    members: List[Dict[str, str]] = []
    seen = set()
    for item in raw_members:
        name = (item.get("name") or "").strip()
        key = _norm_name(name)
        if not key or len(key.split()) < 2 or key in seen:
            continue
        seen.add(key)
        members.append(
            {
                "name": name,
                "role": (item.get("role") or "Council Member").strip(),
                "district": (item.get("district") or "At-Large").strip(),
                "website_url": source_url,
            }
        )
    return members


def fetch_web_roster(roster_url: str, jurisdiction_name: str) -> List[Dict[str, str]]:
    """Scrapes an official municipal council webpage and extracts members via local Ollama."""
    resp = requests.get(roster_url, headers=SETTINGS.headers, timeout=max(20, SETTINGS.request_timeout))
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip())
    if len(text) < 80:
        return []
    return _extract_roster_via_ollama(text, jurisdiction_name, roster_url)


def fetch_doc_header_roster(conn: Any, jurisdiction_id: str, jurisdiction_name: str) -> List[Dict[str, str]]:
    """Fallback: extracts sitting councilmembers from the latest City/Town Council document header in SQLite."""
    row = conn.execute(
        """
        SELECT raw_text, source_url FROM documents
        WHERE jurisdiction_id = ?
          AND raw_text IS NOT NULL
          AND LENGTH(raw_text) > 200
          AND (LOWER(title) LIKE '%council%' OR LOWER(title) LIKE '%town board%')
        ORDER BY meeting_date DESC, doc_id DESC
        LIMIT 1
        """,
        (jurisdiction_id,),
    ).fetchone()
    if not row:
        return []
    return _extract_roster_via_ollama(row["raw_text"][:3000], jurisdiction_name, row["source_url"] or "")


def upsert_roster(
    conn: Any,
    jurisdiction_id: str,
    members: List[Dict[str, str]],
    deactivate_missing: bool = False,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Upserts elected officials into entities and optionally marks departed officials inactive."""
    existing_rows = conn.execute(
        "SELECT ocd_person_id, name, active FROM entities WHERE jurisdiction_id = ? AND entity_type = 'legislator'",
        (jurisdiction_id,),
    ).fetchall()
    existing_by_norm = {_norm_name(r["name"]): dict(r) for r in existing_rows}

    state_code = _extract_state_code(jurisdiction_id)
    jur_slug = _slugify(jurisdiction_id.split(":")[-1])
    seen_ids = set()
    counts = {"added": 0, "updated": 0, "deactivated": 0}

    for m in members:
        norm = _norm_name(m["name"])
        if norm in existing_by_norm:
            pid = existing_by_norm[norm]["ocd_person_id"]
            seen_ids.add(pid)
            if not dry_run:
                conn.execute(
                    """
                    UPDATE entities
                    SET role = ?, district = ?, website_url = COALESCE(NULLIF(?, ''), website_url), active = 1
                    WHERE ocd_person_id = ?
                    """,
                    (m["role"], m["district"], m.get("website_url", ""), pid),
                )
            counts["updated"] += 1
        else:
            pid = f"ocd-person/{state_code}-{jur_slug}-{_slugify(m['name'])}"
            seen_ids.add(pid)
            if not dry_run:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO entities
                    (ocd_person_id, jurisdiction_id, name, entity_type, role, district, website_url, active)
                    VALUES (?, ?, ?, 'legislator', ?, ?, ?, 1)
                    """,
                    (pid, jurisdiction_id, m["name"], m["role"], m["district"], m.get("website_url", "")),
                )
            counts["added"] += 1

    # Safety guard: only deactivate missing members when we got a plausible full council (>=3)
    if deactivate_missing and len(members) >= 3:
        for row in existing_rows:
            if row["active"] == 1 and row["ocd_person_id"] not in seen_ids:
                if not dry_run:
                    conn.execute(
                        "UPDATE entities SET active = 0 WHERE ocd_person_id = ?",
                        (row["ocd_person_id"],),
                    )
                counts["deactivated"] += 1

    if not dry_run:
        conn.commit()
    return counts


def sync_rosters(
    db_path: Optional[str] = None,
    jurisdiction_id: Optional[str] = None,
    roster_url: Optional[str] = None,
    deactivate_missing: bool = False,
    dry_run: bool = False,
    max_age_days: int = 90,
    force: bool = False,
) -> Dict[str, int]:
    """Automatically syncs elected rosters for active jurisdictions with quarterly cadence gating."""
    init_db(db_path)
    conn = get_connection(db_path)
    _ensure_roster_columns(conn)
    totals = {"synced": 0, "added": 0, "updated": 0, "deactivated": 0, "skipped": 0, "skipped_recent": 0}

    try:
        if roster_url and jurisdiction_id and not dry_run:
            conn.execute(
                "UPDATE jurisdictions SET roster_url = ? WHERE ocd_division_id = ?",
                (roster_url.strip(), jurisdiction_id),
            )
            conn.commit()

        query = (
            "SELECT ocd_division_id, name, adapter_type, portal_url, roster_url, last_roster_synced_at "
            "FROM jurisdictions WHERE status = 'active'"
        )
        params: List[Any] = []
        if jurisdiction_id:
            query += " AND ocd_division_id = ?"
            params.append(jurisdiction_id)
        jurisdictions = conn.execute(query, params).fetchall()

        for j in jurisdictions:
            jid = j["ocd_division_id"]
            jname = j["name"]
            if not force and not roster_url and max_age_days > 0 and not is_due(j["last_roster_synced_at"], max_age_days):
                print(f"[ROSTER] {jname}: synced within last {max_age_days}d (skipping)", flush=True)
                totals["skipped_recent"] += 1
                continue

            adapter = (j["adapter_type"] or "").lower()
            portal_url = j["portal_url"] or ""
            saved_roster_url = (j["roster_url"] or "").strip()
            effective_roster_url = (roster_url or "").strip() or saved_roster_url
            members: List[Dict[str, str]] = []
            source_used = "none"

            try:
                if roster_url:
                    try:
                        members = fetch_web_roster(effective_roster_url, jname)
                        source_used = "roster_url (LLM)"
                    except Exception:
                        members = fetch_doc_header_roster(conn, jid, jname)
                        source_used = "council doc header fallback (LLM)"
                elif adapter == "legistar":
                    try:
                        members = fetch_legistar_roster(portal_url)
                        source_used = "legistar API"
                    except Exception:
                        members = []
                    if not members and saved_roster_url:
                        members = fetch_web_roster(saved_roster_url, jname)
                        source_used = "saved roster_url (LLM)"
                    if not members:
                        members = fetch_doc_header_roster(conn, jid, jname)
                        source_used = "council doc header (LLM)"
                elif saved_roster_url:
                    members = fetch_web_roster(saved_roster_url, jname)
                    source_used = "saved roster_url (LLM)"
                else:
                    members = fetch_doc_header_roster(conn, jid, jname)
                    source_used = "council doc header (LLM)"
            except Exception as exc:
                print(f"[ROSTER][WARN] {jname}: sync failed ({exc})", flush=True)
                totals["skipped"] += 1
                continue

            if not members:
                print(f"[ROSTER] {jname}: 0 members found via {source_used} (skipped)", flush=True)
                totals["skipped"] += 1
                continue

            res = upsert_roster(conn, jid, members, deactivate_missing=deactivate_missing, dry_run=dry_run)
            if not dry_run:
                conn.execute(
                    "UPDATE jurisdictions SET last_roster_synced_at = ? WHERE ocd_division_id = ?",
                    (datetime.now(timezone.utc).isoformat(), jid),
                )
                conn.commit()
            totals["synced"] += 1
            totals["added"] += res["added"]
            totals["updated"] += res["updated"]
            totals["deactivated"] += res["deactivated"]
            tag = " [DRY-RUN]" if dry_run else ""
            print(
                f"[ROSTER]{tag} {jname} ({source_used}): "
                f"{len(members)} found (+{res['added']} added, {res['updated']} updated, -{res['deactivated']} inactive)",
                flush=True,
            )

        return totals
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated CivicPulse Roster Sync")
    parser.add_argument("--jurisdiction", default=None, help="Optional single ocd_division_id")
    parser.add_argument("--roster-url", default=None, help="Optional official council webpage URL")
    parser.add_argument("--deactivate-missing", action="store_true", help="Mark departed members active=0")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to SQLite")
    parser.add_argument("--max-age-days", type=int, default=90, help="Skip rosters synced within N days (default: 90)")
    parser.add_argument("--force", action="store_true", help="Ignore max-age-days and sync immediately")
    args = parser.parse_args()
    stats = sync_rosters(
        jurisdiction_id=args.jurisdiction,
        roster_url=args.roster_url,
        deactivate_missing=args.deactivate_missing,
        dry_run=args.dry_run,
        max_age_days=args.max_age_days,
        force=args.force,
    )
    print(f"[ROSTER] Done: {stats}")


if __name__ == "__main__":
    main()
