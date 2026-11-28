"""Official Representative Photo & Contact Enricher (civicpulse/pipeline/enrich_rep_media.py).

Safely fetches each active jurisdiction's official `roster_url` to fill missing
`photo_url`, `email`, and `phone` fields on `entities` using strictly official
government pages. Never overwrites existing populated values.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urljoin

import requests

EMAIL_RE = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.(?:gov|org|us|com|edu)\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)


def ensure_media_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    for col in ("photo_url", "email", "phone", "website_url", "bio_summary"):
        if col not in cols:
            conn.execute(f"ALTER TABLE entities ADD COLUMN {col} TEXT DEFAULT ''")
    conn.commit()


def extract_rep_media_from_html(html: str, base_url: str, rep_name: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not html or not rep_name:
        return out

    tokens = [t for t in re.split(r"\s+", rep_name.strip()) if len(t) >= 3]
    if not tokens:
        return out
    last_name = tokens[-1]

    m = re.search(re.escape(rep_name), html, re.I) or re.search(r"\b" + re.escape(last_name) + r"\b", html, re.I)
    if not m:
        return out

    start = max(0, m.start() - 1200)
    end = min(len(html), m.end() + 1800)
    window = html[start:end]

    for img_m in IMG_TAG_RE.finditer(window):
        tag = img_m.group(0)
        src_m = re.search(r'src=["\']([^"\']+)["\']', tag, re.I)
        alt_m = re.search(r'alt=["\']([^"\']*)["\']', tag, re.I)
        if not src_m:
            continue
        src_val = src_m.group(1)
        alt_val = alt_m.group(1) if alt_m else ""
        if any(skip in src_val.lower() for skip in ("logo", "icon", "sprite", "banner", ".svg")):
            continue
        if last_name.lower() in (alt_val + " " + src_val).lower():
            out["photo_url"] = urljoin(base_url, src_val)
            break

    emails = EMAIL_RE.findall(window)
    for em in emails:
        if last_name.lower() in em.lower():
            out["email"] = em.lower()
            break

    phones = PHONE_RE.findall(window)
    if phones:
        out["phone"] = phones[0]

    return out


def enrich_all_rep_media(db_path: Path = Path("core_civic.db"), timeout: int = 12) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_media_columns(conn)

    jcols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    roster_col = "roster_url" if "roster_url" in jcols else "portal_url"

    jurs = conn.execute(
        f"SELECT ocd_division_id, name, adapter_type, {roster_col} AS roster_url, portal_url "
        "FROM jurisdictions WHERE status = 'active'"
    ).fetchall()

    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; CivicPulseBot/1.0; +https://civics-d03.pages.dev)"}
    photos_added = 0
    emails_added = 0
    phones_added = 0
    pages_checked = 0

    for j in jurs:
        jid = j["ocd_division_id"]
        url = (j["roster_url"] or "").strip()
        if not url or not url.startswith("http"):
            continue
        reps = conn.execute(
            "SELECT ocd_person_id, name, COALESCE(photo_url, '') AS photo_url, "
            "COALESCE(email, '') AS email, COALESCE(phone, '') AS phone "
            "FROM entities WHERE jurisdiction_id = ? AND COALESCE(active, 1) = 1",
            (jid,),
        ).fetchall()
        need_any = [r for r in reps if not r["photo_url"] or not r["email"]]
        if not need_any:
            continue

        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
            if resp.status_code != 200 or "html" not in (resp.headers.get("Content-Type") or "").lower():
                continue
            pages_checked += 1
            html = resp.text
        except Exception:
            continue

        for r in need_any:
            found = extract_rep_media_from_html(html, url, r["name"])
            if found.get("photo_url") and not r["photo_url"]:
                conn.execute("UPDATE entities SET photo_url = ? WHERE ocd_person_id = ?", (found["photo_url"], r["ocd_person_id"]))
                photos_added += 1
            if found.get("email") and not r["email"]:
                conn.execute("UPDATE entities SET email = ? WHERE ocd_person_id = ?", (found["email"], r["ocd_person_id"]))
                emails_added += 1
            if found.get("phone") and not r["phone"]:
                conn.execute("UPDATE entities SET phone = ? WHERE ocd_person_id = ?", (found["phone"], r["ocd_person_id"]))
                phones_added += 1

    conn.commit()
    conn.close()
    return {
        "pages_checked": pages_checked,
        "photos_added": photos_added,
        "emails_added": emails_added,
        "phones_added": phones_added,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich active reps with official .gov headshots & emails")
    parser.add_argument("--db", default="core_civic.db")
    args = parser.parse_args()
    res = enrich_all_rep_media(Path(args.db))
    print("[REP-MEDIA]", json.dumps(res))


if __name__ == "__main__":
    main()
