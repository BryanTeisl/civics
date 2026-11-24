import argparse
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
import requests

from db import DB_PATH, get_connection, init_db

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CivicPulseBot/1.0; +https://civics-d03.pages.dev)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}

# Cities & towns along the Denver <-> Fort Collins Front Range corridor (I-25 / US-287 / US-36 / I-76)
FRONT_RANGE_CORRIDOR_TARGETS: List[Dict[str, Any]] = [
    # --- PrimeGov Portals ---
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:longmont",
        "name": "Longmont City Council",
        "level": "city",
        "lat": 40.1672,
        "lng": -105.1019,
        "platform": "primegov",
        "portal_url": "https://longmont.primegov.com/public/portal",
        "subdomain": "longmont",
        "tier": "mid_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:westminster",
        "name": "Westminster City Council",
        "level": "city",
        "lat": 39.8367,
        "lng": -105.0372,
        "platform": "primegov",
        "portal_url": "https://cityofwestminster.primegov.com/public/portal",
        "subdomain": "cityofwestminster",
        "tier": "large_suburb",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:boulder",
        "name": "Boulder City Council",
        "level": "city",
        "lat": 40.0150,
        "lng": -105.2705,
        "platform": "primegov",
        "portal_url": "https://bouldercolorado.primegov.com/public/portal",
        "subdomain": "bouldercolorado",
        "tier": "mid_city",
    },
    # --- Legistar Portals ---
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:erie",
        "name": "Erie Town Council",
        "level": "city",
        "lat": 40.0503,
        "lng": -105.0499,
        "platform": "legistar",
        "portal_url": "https://erie.legistar.com/",
        "client": "erie",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:denver",
        "name": "Denver City Council",
        "level": "city",
        "lat": 39.7392,
        "lng": -104.9903,
        "platform": "legistar",
        "portal_url": "https://denver.legistar.com/",
        "client": "denver",
        "tier": "major_metro",
    },
    # --- CivicClerk Portals ---
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:windsor",
        "name": "Windsor Town Board",
        "level": "city",
        "lat": 40.4775,
        "lng": -104.9014,
        "platform": "civicclerk",
        "portal_url": "https://windsorco.portal.civicclerk.com/",
        "slug": "windsorco",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:fort_collins",
        "name": "Fort Collins City Council",
        "level": "city",
        "lat": 40.5853,
        "lng": -105.0844,
        "platform": "civicclerk",
        "portal_url": "https://fortcollinsco.portal.civicclerk.com/",
        "slug": "fortcollinsco",
        "tier": "mid_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:greeley",
        "name": "Greeley City Council",
        "level": "city",
        "lat": 40.4233,
        "lng": -104.7091,
        "platform": "civicclerk",
        "portal_url": "https://greeleyco.portal.civicclerk.com/",
        "slug": "greeleyco",
        "tier": "mid_city",
    },
    # --- CivicPlus / Web Portal Corridor Municipalities (HTML / RSS / AgendaCenter) ---
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:loveland",
        "name": "Loveland City Council",
        "level": "city",
        "lat": 40.3978,
        "lng": -105.0750,
        "platform": "civicplus",
        "portal_url": "https://cilovelandco.civicweb.net/Portal/",
        "tier": "mid_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:johnstown",
        "name": "Johnstown Town Council",
        "level": "city",
        "lat": 40.3369,
        "lng": -104.9122,
        "platform": "civicplus",
        "portal_url": "https://johnstownco.gov/311/Agendas-and-Minutes",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:frederick",
        "name": "Frederick Board of Trustees",
        "level": "city",
        "lat": 40.0992,
        "lng": -104.9372,
        "platform": "civicplus",
        "portal_url": "https://www.frederickco.gov/1100/Agenda-Portal",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:louisville",
        "name": "Louisville City Council",
        "level": "city",
        "lat": 39.9778,
        "lng": -105.1319,
        "platform": "civicplus",
        "portal_url": "https://www.louisvilleco.gov/departments/city-council/council-meetings-agendas-and-minutes/",
        "tier": "small_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:lafayette",
        "name": "Lafayette City Council",
        "level": "city",
        "lat": 39.9936,
        "lng": -105.0897,
        "platform": "civicplus",
        "portal_url": "https://www.lafayetteco.gov/AgendaCenter",
        "tier": "small_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:berthoud",
        "name": "Berthoud Board of Trustees",
        "level": "city",
        "lat": 40.3083,
        "lng": -105.0811,
        "platform": "civicplus",
        "portal_url": "https://www.berthoud.org/AgendaCenter",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:timnath",
        "name": "Timnath Town Council",
        "level": "city",
        "lat": 40.5292,
        "lng": -104.9853,
        "platform": "civicplus",
        "portal_url": "https://timnath.org/town-council/",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:wellington",
        "name": "Wellington Board of Trustees",
        "level": "city",
        "lat": 40.7039,
        "lng": -105.0086,
        "platform": "civicplus",
        "portal_url": "https://www.wellingtoncolorado.gov/AgendaCenter",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:thornton",
        "name": "Thornton City Council",
        "level": "city",
        "lat": 39.8680,
        "lng": -104.9719,
        "platform": "primegov",
        "portal_url": "https://thorntonco.primegov.com/public/portal",
        "subdomain": "thorntonco",
        "tier": "large_suburb",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:northglenn",
        "name": "Northglenn City Council",
        "level": "city",
        "lat": 39.8855,
        "lng": -104.9811,
        "platform": "civicplus",
        "portal_url": "https://webdocs.northglenn.org/",
        "tier": "small_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:broomfield",
        "name": "Broomfield City Council",
        "level": "city",
        "lat": 39.9205,
        "lng": -105.0867,
        "platform": "civicplus",
        "portal_url": "https://www.broomfield.org/4079/Broomfield-Council-Meetings",
        "tier": "mid_city",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:firestone",
        "name": "Firestone Board of Trustees",
        "level": "city",
        "lat": 40.1125,
        "lng": -104.9366,
        "platform": "civicplus",
        "portal_url": "https://www.firestoneco.gov/AgendaCenter",
        "tier": "growing_town",
    },
    {
        "ocd_division_id": "ocd-division/country:us/state:co/place:dacono",
        "name": "Dacono City Council",
        "level": "city",
        "lat": 40.0847,
        "lng": -104.9394,
        "platform": "civicplus",
        "portal_url": "https://www.daconoco.gov/AgendaCenter/City-Council-1/",
        "tier": "growing_town",
    },
]


def probe_target(target: Dict[str, Any], year: int = 2026) -> Dict[str, Any]:
    platform = target["platform"]
    try:
        if platform == "primegov":
            sub = target["subdomain"]
            url = f"https://{sub}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                sample = (data[0].get("title") or "") if data else ""
                return {"ok": True, "status": 200, "count": len(data), "sample": sample[:60]}
            return {"ok": False, "status": r.status_code, "count": 0, "sample": "HTTP error"}

        if platform == "legistar":
            client = target["client"]
            url = f"https://webapi.legistar.com/v1/{client}/events?$top=5&$orderby=EventDate%20desc"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                sample = (data[0].get("EventBodyName") or "") if data else ""
                return {"ok": True, "status": 200, "count": len(data), "sample": sample[:60]}
            return {"ok": False, "status": r.status_code, "count": 0, "sample": "HTTP error"}

        if platform == "civicclerk":
            slug = target["slug"]
            url = f"https://{slug}.api.civicclerk.com/v1/Events?$top=5&$orderby=startDateTime%20desc"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json().get("value", [])
                sample = (data[0].get("eventName") or "") if data else ""
                return {"ok": True, "status": 200, "count": len(data), "sample": sample[:60]}
            return {"ok": False, "status": r.status_code, "count": 0, "sample": "HTTP error"}

        # CivicPlus / general HTML agenda center probe
        r = requests.get(target["portal_url"], headers=HEADERS, timeout=15, allow_redirects=True)
        has_agenda_markers = bool(
            re.search(r"(agenda|minutes|council|trustees|meeting)", r.text, re.IGNORECASE)
        )
        ok = r.status_code == 200 and has_agenda_markers
        return {
            "ok": ok,
            "status": r.status_code,
            "count": 1 if ok else 0,
            "sample": "HTML agenda portal reachable" if ok else "Blocked or no agenda markers",
        }
    except Exception as exc:
        return {"ok": False, "status": "ERR", "count": 0, "sample": str(exc)[:60]}


def seed_corridor_into_db(
    results: List[tuple[Dict[str, Any], Dict[str, Any]]],
    activate_structured: bool = False,
    db_path: str = DB_PATH,
) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    inserted = 0
    updated = 0
    try:
        for target, res in results:
            div_id = target["ocd_division_id"]
            existing = conn.execute(
                "SELECT status, adapter_type FROM jurisdictions WHERE ocd_division_id = ?",
                (div_id,),
            ).fetchone()

            is_structured = target["platform"] in ("primegov", "legistar", "civicclerk") and res["ok"]
            desired_status = "active" if (activate_structured and is_structured) else "unclaimed"
            adapter_type = target["platform"] if res["ok"] else "unclaimed"

            if existing:
                # Never downgrade an already-active jurisdiction
                if (existing["status"] or "").lower() == "active":
                    continue
                conn.execute(
                    """
                    UPDATE jurisdictions
                    SET portal_url = ?, adapter_type = ?, status = ?, lat = COALESCE(lat, ?), lng = COALESCE(lng, ?)
                    WHERE ocd_division_id = ?
                    """,
                    (target["portal_url"], adapter_type, desired_status, target["lat"], target["lng"], div_id),
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
                        target["name"],
                        target["level"],
                        target["lat"],
                        target["lng"],
                        target["portal_url"],
                        adapter_type,
                        desired_status,
                    ),
                )
                inserted += 1
        conn.commit()
        print(f"\n[DB SYNC] Inserted {inserted} new corridor jurisdictions, updated {updated} unclaimed entries.")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Denver <-> Fort Collins Front Range Corridor portals.")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="Target year for PrimeGov queries")
    parser.add_argument("--seed-unclaimed", action="store_true", help="Insert/update verified corridor cities into core_civic.db as unclaimed")
    parser.add_argument("--activate-structured", action="store_true", help="Also set verified PrimeGov/Legistar/CivicClerk corridor cities to active")
    args = parser.parse_args()

    print(f"=== Front Range Corridor Multi-Platform Probe (Denver <-> Fort Collins, year={args.year}) ===")
    results: List[tuple[Dict[str, Any], Dict[str, Any]]] = []
    for target in FRONT_RANGE_CORRIDOR_TARGETS:
        res = probe_target(target, year=args.year)
        results.append((target, res))
        flag = "PASS" if res["ok"] else "FAIL"
        print(
            f"[{flag}] {target['name']:30s} | {target['platform']:10s} | "
            f"HTTP={str(res['status']):4s} | items={res['count']:2d} | {res['sample']}"
        )

    passed = sum(1 for _, r in results if r["ok"])
    print(f"\nSummary: {passed}/{len(results)} Front Range corridor endpoints reachable.")

    if args.seed_unclaimed or args.activate_structured:
        seed_corridor_into_db(results, activate_structured=args.activate_structured)


if __name__ == "__main__":
    main()
