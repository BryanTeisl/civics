"""Zero-LLM official representative contact enrichment (emails, phones, websites).

Closes the thin-roster contact gap (17/85 -> high official .gov coverage) using:
  1. Legistar Web API (/v1/{client}/Persons) for Denver, Colorado Springs, and Erie
  2. Polite HTML mailto:/tel: extraction from each jurisdiction's official roster_url
     matched by councilmember last name / full name, with optional council-wide
     contact email fallback only when explicitly labeled.

Usage:
  python scripts/enrich_contacts.py --db core_civic.db --dry-run
  python scripts/enrich_contacts.py --db core_civic.db --apply
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
GENERIC_EMAIL_PREFIXES = (
    "info", "webmaster", "noreply", "no-reply", "communications", "clerk",
    "cityclerk", "support", "contact", "feedback", "accessibility", "privacy",
)


class _ContactPageParser(HTMLParser):
    """Collects (email, surrounding_text) and (phone, surrounding_text) from official pages."""

    def __init__(self) -> None:
        super().__init__()
        self.emails: List[Tuple[str, str]] = []
        self.phones: List[Tuple[str, str]] = []
        self._recent_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            href = (dict(attrs).get("href") or "").strip()
            ctx = " ".join(self._recent_text[-12:])
            if href.lower().startswith("mailto:"):
                addr = href[7:].split("?")[0].strip()
                if EMAIL_RE.fullmatch(addr):
                    self.emails.append((addr.lower(), ctx))
            elif href.lower().startswith("tel:"):
                ph = href[4:].strip()
                if len(re.sub(r"\D", "", ph)) >= 10:
                    self.phones.append((ph, ctx))

    def handle_data(self, data: str) -> None:
        txt = " ".join(data.split()).strip()
        if not txt:
            return
        self._recent_text.append(txt)
        if len(self._recent_text) > 30:
            self._recent_text = self._recent_text[-30:]
        ctx = " ".join(self._recent_text[-8:])
        for em in EMAIL_RE.findall(txt):
            self.emails.append((em.lower(), ctx))
        for ph in PHONE_RE.findall(txt):
            self.phones.append((ph.strip(), ctx))


def _name_tokens(name: str) -> Tuple[str, str]:
    cleaned = re.sub(r"[^a-z\s-]", "", (name or "").lower()).strip()
    parts = [p for p in cleaned.split() if p not in ("mayor", "pro", "tem", "councilmember", "councillor", "commissioner", "dr", "jr", "sr", "ii", "iii")]
    if not parts:
        return "", ""
    return parts[0], parts[-1]


def match_contacts_from_html(
    html: str,
    entities: List[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    """Matches discovered emails/phones on a roster page to entity ocd_person_ids."""
    parser = _ContactPageParser()
    parser.feed(html or "")

    # Deduplicate emails preserving first context
    email_items: List[Tuple[str, str]] = []
    seen_em = set()
    for em, ctx in parser.emails:
        if em not in seen_em:
            seen_em.add(em)
            email_items.append((em, ctx.lower()))

    phone_items: List[Tuple[str, str]] = []
    seen_ph = set()
    for ph, ctx in parser.phones:
        digits = re.sub(r"\D", "", ph)[-10:]
        if len(digits) == 10 and digits not in seen_ph:
            seen_ph.add(digits)
            formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            phone_items.append((formatted, ctx.lower()))

    matches: Dict[str, Dict[str, str]] = {}
    for ent in entities:
        pid = ent["ocd_person_id"]
        first, last = _name_tokens(ent["name"])
        if not last or len(last) < 3:
            continue

        found: Dict[str, str] = {}
        # 1. Prefer direct local-part match (e.g., efrancis@fcgov.com or jane.doe@city.gov)
        for em, ctx in email_items:
            local = em.split("@")[0]
            if any(local.startswith(g) for g in GENERIC_EMAIL_PREFIXES):
                continue
            if last in local or (first and first in local and last[:3] in local):
                found["email"] = em
                break
        # 2. Fallback: email appearing right next to representative's name in page HTML
        if "email" not in found:
            for em, ctx in email_items:
                local = em.split("@")[0]
                if any(local.startswith(g) for g in GENERIC_EMAIL_PREFIXES):
                    continue
                if last in ctx and (not first or first in ctx):
                    found["email"] = em
                    break

        for ph, ctx in phone_items:
            if last in ctx and (not first or first in ctx):
                found["phone"] = ph
                break

        if found:
            matches[pid] = found

    return matches


def _legistar_client_from_url(portal_url: str) -> str:
    host = urlparse((portal_url or "").strip()).netloc.lower()
    if ".legistar.com" in host:
        return host.split(".legistar.com")[0]
    return ""


def fetch_legistar_person_contacts(
    client: str, entities: List[Dict[str, str]], timeout: int = 15
) -> Dict[str, Dict[str, str]]:
    """Queries Legistar /v1/{client}/Persons for official emails, phones, and websites."""
    if not client:
        return {}
    url = f"https://webapi.legistar.com/v1/{client}/Persons"
    try:
        r = requests.get(url, params={"$filter": "PersonActiveFlag eq 1"}, headers=HEADERS, timeout=timeout)
        if not r.ok:
            return {}
        persons = r.json() if isinstance(r.json(), list) else []
    except Exception:
        return {}

    by_name: Dict[str, Dict[str, str]] = {}
    by_last: Dict[str, List[Dict[str, str]]] = {}
    for p in persons:
        full = (p.get("PersonFullName") or "").strip().lower()
        em = (p.get("PersonEmail") or "").strip()
        ph = (p.get("PersonPhone") or "").strip()
        www = (p.get("PersonWWW") or "").strip()
        rec: Dict[str, str] = {}
        if em and EMAIL_RE.fullmatch(em):
            rec["email"] = em.lower()
        if ph and len(re.sub(r"\D", "", ph)) >= 10:
            d = re.sub(r"\D", "", ph)[-10:]
            rec["phone"] = f"({d[:3]}) {d[3:6]}-{d[6:]}"
        if www.startswith("http"):
            rec["portal_url"] = www
        if not rec or not full:
            continue
        by_name[full] = rec
        last = full.split()[-1]
        by_last.setdefault(last, []).append(rec)

    matches: Dict[str, Dict[str, str]] = {}
    for ent in entities:
        pid = ent["ocd_person_id"]
        full_l = (ent["name"] or "").strip().lower()
        if full_l in by_name:
            matches[pid] = by_name[full_l]
            continue
        _, last = _name_tokens(ent["name"])
        if last in by_last and len(by_last[last]) == 1:
            matches[pid] = by_last[last][0]
    return matches


def enrich_database_contacts(db_path: str, apply: bool = False) -> Dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {"jurisdictions_checked": 0, "emails_added": 0, "phones_added": 0, "urls_added": 0}

    jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    ent_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    roster_col = "roster_url" if "roster_url" in jur_cols else "'' AS roster_url"

    try:
        jurs = conn.execute(
            f"""
            SELECT ocd_division_id, name, adapter_type, portal_url, {roster_col}
            FROM jurisdictions
            WHERE COALESCE(status, 'active') = 'active'
            ORDER BY name ASC
            """
        ).fetchall()

        for j in jurs:
            jid = j["ocd_division_id"]
            ents = [
                dict(r)
                for r in conn.execute(
                    "SELECT ocd_person_id, name, COALESCE(email, '') AS email, COALESCE(phone, '') AS phone, COALESCE(portal_url, '') AS portal_url "
                    "FROM entities WHERE jurisdiction_id = ? AND COALESCE(active, 1) = 1",
                    (jid,),
                ).fetchall()
            ]
            missing = [e for e in ents if not e["email"] or not e["phone"]]
            if not missing:
                continue

            stats["jurisdictions_checked"] += 1
            discovered: Dict[str, Dict[str, str]] = {}

            if (j["adapter_type"] or "").lower() == "legistar":
                client = _legistar_client_from_url(j["portal_url"] or "")
                discovered.update(fetch_legistar_person_contacts(client, missing))

            r_url = (j["roster_url"] or "").strip()
            if r_url.startswith("http"):
                try:
                    resp = requests.get(r_url, headers=HEADERS, timeout=15)
                    if resp.ok:
                        html_matches = match_contacts_from_html(resp.text, missing)
                        for pid, vals in html_matches.items():
                            discovered.setdefault(pid, {}).update(
                                {k: v for k, v in vals.items() if k not in discovered.get(pid, {})}
                            )
                except requests.RequestException:
                    pass

            for e in missing:
                pid = e["ocd_person_id"]
                upd = discovered.get(pid)
                if not upd:
                    continue
                sets, vals = [], []
                if not e["email"] and upd.get("email") and "email" in ent_cols:
                    sets.append("email = ?")
                    vals.append(upd["email"])
                    stats["emails_added"] += 1
                if not e["phone"] and upd.get("phone") and "phone" in ent_cols:
                    sets.append("phone = ?")
                    vals.append(upd["phone"])
                    stats["phones_added"] += 1
                if not e["portal_url"] and upd.get("portal_url") and "portal_url" in ent_cols:
                    sets.append("portal_url = ?")
                    vals.append(upd["portal_url"])
                    stats["urls_added"] += 1

                if sets and apply:
                    vals.append(pid)
                    conn.execute(f"UPDATE entities SET {', '.join(sets)} WHERE ocd_person_id = ?", vals)

        if apply:
            conn.commit()
        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich official representative emails and phone numbers.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--apply", action="store_true", help="Persist discovered contacts to SQLite")
    args = parser.parse_args()
    res = enrich_database_contacts(args.db, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[CONTACTS:{mode}] {res}")


if __name__ == "__main__":
    main()
