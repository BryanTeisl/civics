from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from civicpulse.adapters import ProbeResult, get_adapter
from civicpulse.config import SETTINGS
from civicpulse.db import get_connection, init_db


def slugify_place(name: str) -> str:
    cleaned = re.sub(
        r"\b(city|town|village|borough|county|board|council|trustees|of|the|municipality|school|district)\b",
        "",
        name.lower(),
    )
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def build_ocd_id(place_name: str, state_abbr: str, level: str = "city") -> str:
    st = state_abbr.strip().lower()
    slug = slugify_place(place_name)
    if level == "county":
        return f"ocd-division/country:us/state:{st}/county:{slug}"
    if level == "school_district":
        return f"ocd-division/country:us/state:{st}/school_district:{slug}"
    return f"ocd-division/country:us/state:{st}/place:{slug}"


def geocode_jurisdiction(query: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": SETTINGS.user_agent},
            timeout=SETTINGS.request_timeout,
        )
        if resp.status_code == 200 and resp.json():
            hit = resp.json()[0]
            return float(hit["lat"]), float(hit["lon"])
    except Exception:
        pass
    return None, None


def candidate_slugs(place_name: str, state_abbr: str) -> List[str]:
    base = re.sub(r"\b(city|town|county|board|council|trustees|of|the)\b", "", place_name.lower())
    compact = re.sub(r"[^a-z0-9]", "", base)
    st = state_abbr.strip().lower()
    if not compact:
        return []
    return list(
        dict.fromkeys(
            [
                compact,
                f"{compact}{st}",
                f"cityof{compact}",
                f"townof{compact}",
                f"{compact}colorado" if st == "co" else f"{compact}{st}",
            ]
        )
    )


def detect_adapter_for_url(portal_url: str) -> str:
    low = (portal_url or "").lower()
    if ".primegov.com" in low:
        return "primegov"
    if ".legistar.com" in low:
        return "legistar"
    if "civicclerk.com" in low:
        return "civicclerk"
    if "boarddocs.com" in low:
        return "boarddocs"
    if "granicus.com" in low:
        return "granicus"
    return "civicplus"


def probe_portal(portal_url: str, year: int, preferred_adapter: Optional[str] = None) -> ProbeResult:
    adapter_name = preferred_adapter or detect_adapter_for_url(portal_url)
    adapter = get_adapter(adapter_name)
    if not adapter:
        return ProbeResult(False, "ERR", 0, "Unknown adapter", "unclaimed", portal_url)

    res = adapter.health_check(portal_url, year)
    # If a generic civicplus page embeds a structured vendor portal link, follow it automatically
    if adapter_name == "civicplus" and res.ok:
        try:
            r = requests.get(portal_url, headers=SETTINGS.headers, timeout=SETTINGS.request_timeout)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = urljoin(portal_url, a["href"])
                detected = detect_adapter_for_url(href)
                if detected != "civicplus":
                    sub_adapter = get_adapter(detected)
                    if sub_adapter:
                        sub_res = sub_adapter.health_check(href, year)
                        if sub_res.ok:
                            return sub_res
        except Exception:
            pass
    return res


def auto_discover_structured(place_name: str, state_abbr: str, year: int) -> Optional[ProbeResult]:
    slugs = candidate_slugs(place_name, state_abbr)
    probes = [
        ("legistar", lambda s: f"https://{s}.legistar.com/"),
        ("primegov", lambda s: f"https://{s}.primegov.com/public/portal"),
        ("civicclerk", lambda s: f"https://{s}.portal.civicclerk.com/"),
    ]
    for adapter_name, url_fn in probes:
        adapter = get_adapter(adapter_name)
        if not adapter:
            continue
        for slug in slugs:
            res = adapter.health_check(url_fn(slug), year)
            if res.ok and res.item_count > 0:
                return res
    return None


def extract_roster_with_local_llm(roster_url: str, div_id: str, portal_url: str) -> List[Dict[str, str]]:
    if not roster_url:
        return []
    try:
        r = requests.get(roster_url, headers=SETTINGS.headers, timeout=SETTINGS.request_timeout)
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text_chunk = "\n".join(ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip())[:6000]
        prompt = (
            "Extract current elected councilmembers, mayor, commissioners, or board trustees from the text below.\n"
            "Return ONLY valid JSON as a list of objects with keys: name, role, district, email, phone.\n"
            "Do not invent people not listed in the text.\n\n"
            f"TEXT:\n{text_chunk}"
        )
        llm_resp = requests.post(
            SETTINGS.ollama_url,
            json={"model": SETTINGS.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=45,
        )
        if llm_resp.status_code != 200:
            return []
        parsed = json.loads(llm_resp.json().get("response", "[]"))
        if isinstance(parsed, dict):
            parsed = parsed.get("members") or parsed.get("representatives") or []
        members: List[Dict[str, str]] = []
        for item in parsed:
            name = (item.get("name") or "").strip()
            if not name or len(name.split()) < 2:
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            members.append(
                {
                    "ocd_person_id": f"ocd-person/{slugify_place(div_id)}_{slug}",
                    "name": name,
                    "role": (item.get("role") or "Councilmember").strip(),
                    "district": (item.get("district") or "At-Large").strip(),
                    "email": (item.get("email") or "").strip(),
                    "phone": (item.get("phone") or "").strip(),
                    "website_url": roster_url,
                    "portal_url": portal_url,
                }
            )
        return members
    except Exception:
        return []


def onboard_jurisdiction(
    name: str,
    state: str = "CO",
    level: str = "city",
    portal_url: Optional[str] = None,
    roster_url: Optional[str] = None,
    activate: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    init_db(db_path)
    year = datetime.now(timezone.utc).year
    div_id = build_ocd_id(name, state, level)
    lat, lng = geocode_jurisdiction(f"{name}, {state}, USA")

    if portal_url:
        probe = probe_portal(portal_url, year)
    else:
        probe = auto_discover_structured(name, state, year) or ProbeResult(
            False, "N/A", 0, "No structured API auto-matched; queued as unclaimed", "unclaimed", ""
        )

    adapter_obj = get_adapter(probe.adapter_type)
    is_structured_ok = bool(adapter_obj and adapter_obj.is_structured and probe.ok and probe.item_count > 0)
    status = "active" if (activate and is_structured_ok) else "unclaimed"

    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            "SELECT ocd_division_id, status FROM jurisdictions WHERE ocd_division_id = ?",
            (div_id,),
        ).fetchone()
        if existing:
            # Never downgrade an already-active jurisdiction
            final_status = "active" if (existing["status"] or "").lower() == "active" else status
            conn.execute(
                """
                UPDATE jurisdictions
                SET name = ?, level = ?, lat = COALESCE(?, lat), lng = COALESCE(?, lng),
                    portal_url = COALESCE(NULLIF(?, ''), portal_url),
                    adapter_type = ?, status = ?
                WHERE ocd_division_id = ?
                """,
                (name, level, lat, lng, probe.normalized_portal_url, probe.adapter_type, final_status, div_id),
            )
            status = final_status
        else:
            conn.execute(
                """
                INSERT INTO jurisdictions
                (ocd_division_id, name, level, lat, lng, portal_url, adapter_type, poll_tier, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'standard', ?)
                """,
                (div_id, name, level, lat or 0.0, lng or 0.0, probe.normalized_portal_url, probe.adapter_type, status),
            )

        roster_added = 0
        if roster_url:
            for m in extract_roster_with_local_llm(roster_url, div_id, probe.normalized_portal_url):
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO entities
                    (ocd_person_id, jurisdiction_id, name, entity_type, role, district, website_url, portal_url, email, phone, active)
                    VALUES (?, ?, ?, 'legislator', ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        m["ocd_person_id"],
                        div_id,
                        m["name"],
                        m["role"],
                        m["district"],
                        m["website_url"],
                        m["portal_url"],
                        m["email"],
                        m["phone"],
                    ),
                )
                if cur.rowcount > 0:
                    roster_added += 1

        conn.commit()
        return {
            "ocd_division_id": div_id,
            "name": name,
            "adapter_type": probe.adapter_type,
            "status": status,
            "portal_url": probe.normalized_portal_url,
            "roster_added": roster_added,
        }
    finally:
        conn.close()
