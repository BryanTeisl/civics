import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from db import DB_PATH, get_connection, init_db

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CivicPulseOnboardingBot/1.0; +https://civics-d03.pages.dev)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"


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
        url = "https://nominatim.openstreetmap.org/search"
        resp = requests.get(
            url,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": "CivicPulseGeocoder/1.0 (bryanateisl@gmail.com)"},
            timeout=15,
        )
        if resp.status_code == 200 and resp.json():
            hit = resp.json()[0]
            return float(hit["lat"]), float(hit["lon"])
    except Exception:
        pass
    return None, None


def candidate_slugs(place_name: str, state_abbr: str) -> List[str]:
    base = re.sub(
        r"\b(city|town|county|board|council|trustees|of|the)\b",
        "",
        place_name.lower(),
    )
    compact = re.sub(r"[^a-z0-9]", "", base)
    st = state_abbr.strip().lower()
    if not compact:
        return []
    return list(dict.fromkeys([
        compact,
        f"{compact}{st}",
        f"cityof{compact}",
        f"townof{compact}",
        f"{compact}colorado" if st == "co" else f"{compact}{st}",
    ]))


def probe_structured_platforms(place_name: str, state_abbr: str, year: int) -> Optional[Dict[str, Any]]:
    slugs = candidate_slugs(place_name, state_abbr)

    # 1. Probe Legistar Web API
    for slug in slugs:
        url = f"https://webapi.legistar.com/v1/{slug}/events?$top=5&$orderby=EventDate%20desc"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0:
                return {
                    "adapter_type": "legistar",
                    "portal_url": f"https://{slug}.legistar.com/",
                    "api_sample_count": len(r.json()),
                    "sample_title": (r.json()[0].get("EventBodyName") or "Legistar Event")[:70],
                }
        except Exception:
            pass

    # 2. Probe PrimeGov Public Portal API
    for slug in slugs:
        url = f"https://{slug}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0:
                return {
                    "adapter_type": "primegov",
                    "portal_url": f"https://{slug}.primegov.com/public/portal",
                    "api_sample_count": len(r.json()),
                    "sample_title": (r.json()[0].get("title") or "PrimeGov Meeting")[:70],
                }
        except Exception:
            pass

    # 3. Probe CivicClerk API
    for slug in slugs:
        url = f"https://{slug}.api.civicclerk.com/v1/Events?$top=5&$orderby=startDateTime%20desc"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                vals = r.json().get("value", [])
                if vals:
                    return {
                        "adapter_type": "civicclerk",
                        "portal_url": f"https://{slug}.portal.civicclerk.com/",
                        "api_sample_count": len(vals),
                        "sample_title": (vals[0].get("eventName") or "CivicClerk Event")[:70],
                    }
        except Exception:
            pass

    return None


def detect_platform_from_url(portal_url: str, year: int) -> Dict[str, Any]:
    low = (portal_url or "").lower()
    if ".legistar.com" in low:
        client = low.split("//", 1)[-1].split(".legistar.com")[0]
        return {"adapter_type": "legistar", "portal_url": f"https://{client}.legistar.com/", "api_sample_count": 1, "sample_title": "Provided Legistar URL"}
    if ".primegov.com" in low:
        sub = low.split("//", 1)[-1].split(".primegov.com")[0]
        return {"adapter_type": "primegov", "portal_url": f"https://{sub}.primegov.com/public/portal", "api_sample_count": 1, "sample_title": "Provided PrimeGov URL"}
    if "civicclerk.com" in low:
        host = low.split("//", 1)[-1].split("/", 1)[0]
        slug = host.split(".")[0]
        return {"adapter_type": "civicclerk", "portal_url": f"https://{slug}.portal.civicclerk.com/", "api_sample_count": 1, "sample_title": "Provided CivicClerk URL"}
    if "boarddocs.com" in low:
        return {"adapter_type": "boarddocs", "portal_url": portal_url, "api_sample_count": 1, "sample_title": "Provided BoardDocs URL"}
    if "granicus.com" in low:
        return {"adapter_type": "granicus", "portal_url": portal_url, "api_sample_count": 1, "sample_title": "Provided Granicus URL"}

    # Inspect HTML page links for embedded vendor portals
    try:
        r = requests.get(portal_url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = urljoin(portal_url, a["href"])
                hlow = href.lower()
                if any(k in hlow for k in (".legistar.com", ".primegov.com", "civicclerk.com", "boarddocs.com", "granicus.com")):
                    return detect_platform_from_url(href, year)
            return {"adapter_type": "civicplus", "portal_url": portal_url, "api_sample_count": 1, "sample_title": "Web / CivicPlus Agenda Portal"}
    except Exception:
        pass

    return {"adapter_type": "unclaimed", "portal_url": portal_url, "api_sample_count": 0, "sample_title": "Unverified portal"}


def extract_roster_with_local_llm(roster_url: str, jurisdiction_id: str, portal_url: str) -> List[Dict[str, str]]:
    """Optional zero-cost local Ollama (qwen2.5:3b) roster extractor from a city council webpage."""
    if not roster_url:
        return []
    try:
        r = requests.get(roster_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
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
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=45,
        )
        if llm_resp.status_code != 200:
            return []
        raw_json = llm_resp.json().get("response", "[]")
        parsed = json.loads(raw_json)
        if isinstance(parsed, dict):
            parsed = parsed.get("members") or parsed.get("representatives") or []
        results = []
        for item in parsed:
            name = (item.get("name") or "").strip()
            if not name or len(name.split()) < 2:
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            results.append({
                "ocd_person_id": f"ocd-person/{slugify_place(jurisdiction_id)}_{slug}",
                "name": name,
                "role": (item.get("role") or "Councilmember").strip(),
                "district": (item.get("district") or "At-Large").strip(),
                "email": (item.get("email") or "").strip(),
                "phone": (item.get("phone") or "").strip(),
                "website_url": roster_url,
                "portal_url": portal_url,
            })
        return results
    except Exception:
        return []


def onboard_jurisdiction(
    name: str,
    state: str = "CO",
    level: str = "city",
    portal_url: Optional[str] = None,
    roster_url: Optional[str] = None,
    activate: bool = True,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    init_db(db_path)
    year = datetime.now(timezone.utc).year
    div_id = build_ocd_id(name, state, level)
    lat, lng = geocode_jurisdiction(f"{name}, {state}, USA")

    print(f"[ONBOARD] Scouting {name} ({state.upper()}) -> {div_id}")
    if lat and lng:
        print(f"  + Geocoded coordinates: ({lat:.4f}, {lng:.4f})")

    if portal_url:
        probe = detect_platform_from_url(portal_url, year)
    else:
        probe = probe_structured_platforms(name, state, year) or {
            "adapter_type": "unclaimed",
            "portal_url": "",
            "api_sample_count": 0,
            "sample_title": "No structured API auto-matched; queued as unclaimed",
        }

    adapter = probe["adapter_type"]
    resolved_url = probe["portal_url"]
    is_supported_active = adapter in ("legistar", "primegov", "civicclerk", "boarddocs", "granicus") and probe["api_sample_count"] > 0
    status = "active" if (activate and is_supported_active) else "unclaimed"

    print(f"  + Platform detection: adapter={adapter} | status={status} | sample={probe['sample_title']}")

    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            "SELECT ocd_division_id FROM jurisdictions WHERE ocd_division_id = ?",
            (div_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE jurisdictions
                SET name = ?, level = ?, lat = COALESCE(?, lat), lng = COALESCE(?, lng),
                    portal_url = COALESCE(NULLIF(?, ''), portal_url),
                    adapter_type = ?, status = ?
                WHERE ocd_division_id = ?
                """,
                (name, level, lat, lng, resolved_url, adapter, status, div_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO jurisdictions
                (ocd_division_id, name, level, lat, lng, portal_url, adapter_type, poll_tier, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'standard', ?)
                """,
                (div_id, name, level, lat, lng, resolved_url, adapter, status),
            )

        roster_added = 0
        if roster_url:
            members = extract_roster_with_local_llm(roster_url, div_id, resolved_url)
            for m in members:
                conn.execute(
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
                roster_added += 1
            if roster_added:
                print(f"  + Bootstrapped {roster_added} representative(s) via local LLM from {roster_url}")

        conn.commit()
    finally:
        conn.close()

    return {
        "ocd_division_id": div_id,
        "name": name,
        "adapter_type": adapter,
        "status": status,
        "portal_url": resolved_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous CivicPulse Site Scout & Onboarding Agent")
    parser.add_argument("--name", help="Jurisdiction name, e.g. 'Longmont City Council'")
    parser.add_argument("--state", default="CO", help="Two-letter state abbreviation (default: CO)")
    parser.add_argument("--level", default="city", choices=["city", "county", "school_district"], help="Government level")
    parser.add_argument("--portal-url", default=None, help="Optional known agenda/portal URL")
    parser.add_argument("--roster-url", default=None, help="Optional council/board members webpage URL for LLM roster extraction")
    parser.add_argument("--batch-file", default=None, help="Optional JSON file listing multiple jurisdictions to onboard")
    parser.add_argument("--unclaimed-only", action="store_true", help="Seed as unclaimed instead of activating immediately")
    parser.add_argument("--run-pipeline", action="store_true", help="Automatically run watcher + JSON export after onboarding")
    args = parser.parse_args()

    if args.batch_file:
        with open(args.batch_file, "r", encoding="utf-8") as f:
            batch = json.load(f)
        for item in batch:
            onboard_jurisdiction(
                name=item["name"],
                state=item.get("state", args.state),
                level=item.get("level", "city"),
                portal_url=item.get("portal_url"),
                roster_url=item.get("roster_url"),
                activate=not args.unclaimed_only,
            )
    elif args.name:
        onboard_jurisdiction(
            name=args.name,
            state=args.state,
            level=args.level,
            portal_url=args.portal_url,
            roster_url=args.roster_url,
            activate=not args.unclaimed_only,
        )
    else:
        parser.error("Provide --name 'City Name' or --batch-file path/to/cities.json")

    if args.run_pipeline:
        print("\n[PIPELINE] Running watcher & static JSON sync...")
        from watcher import run_watcher
        from sync_json_and_index import refresh_all_json_and_index
        run_watcher()
        refresh_all_json_and_index()


if __name__ == "__main__":
    main()
