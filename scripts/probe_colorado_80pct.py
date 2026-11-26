"""Benchmarks CivicPulse population coverage across Colorado's Top 20 Cities
(U.S. Census Vintage 2025) and verifies zero-code-ready expansion targets:
  - Arvada (122,901) — CivicClerk
  - Pueblo (110,404) — CivicClerk
  - Commerce City (72,345) — Legistar
  - Grand Junction (71,827) — CivicClerk

Usage:
  python scripts/probe_colorado_80pct.py
  python scripts/probe_colorado_80pct.py --seed-passing
"""
from __future__ import annotations

import argparse
import sqlite3
from typing import Dict, List, Tuple

import requests

HEADERS = {"User-Agent": "CivicPulseBot/3.1 (+https://civics-d03.pages.dev)"}

COLORADO_TOTAL_POP_2025 = 6_012_561

TOP_20_CITIES: List[Dict] = [
    {"ocd": "ocd-division/country:us/state:co/place:denver", "name": "Denver City Council", "pop": 740_613, "adapter": "legistar", "portal": "https://denver.legistar.com/", "roster": "https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Denver-City-Council", "lat": 39.7392, "lng": -104.9903},
    {"ocd": "ocd-division/country:us/state:co/place:colorado_springs", "name": "Colorado Springs City Council", "pop": 494_743, "adapter": "legistar", "portal": "https://coloradosprings.legistar.com/", "roster": "https://coloradosprings.gov/city-council", "lat": 38.8339, "lng": -104.8214},
    {"ocd": "ocd-division/country:us/state:co/place:aurora", "name": "Aurora City Council", "pop": 410_053, "adapter": "escribemeetings", "portal": "https://www.auroragov.org/city_hall/mayor___city_council/council_meetings", "roster": "https://www.auroragov.org/city_hall/mayor___city_council/council_members", "lat": 39.7294, "lng": -104.8319},
    {"ocd": "ocd-division/country:us/state:co/place:fort_collins", "name": "Fort Collins City Council", "pop": 171_500, "adapter": "civicclerk", "portal": "https://fortcollinsco.portal.civicclerk.com/", "roster": "https://www.fcgov.com/council/", "lat": 40.5853, "lng": -105.0844},
    {"ocd": "ocd-division/country:us/state:co/place:lakewood", "name": "Lakewood City Council", "pop": 156_927, "adapter": "lakewoodspeaks", "portal": "https://www.lakewoodco.gov/Local-Government/Upcoming-City-Meetings", "roster": "https://www.lakewoodco.gov/Local-Government/City-Council", "lat": 39.7047, "lng": -105.0814},
    {"ocd": "ocd-division/country:us/state:co/place:thornton", "name": "Thornton City Council", "pop": 147_766, "adapter": "primegov", "portal": "https://thorntonco.primegov.com/public/portal", "roster": "https://www.thorntonco.gov/government/mayor-council", "lat": 39.8680, "lng": -104.9719},
    {"ocd": "ocd-division/country:us/state:co/place:arvada", "name": "Arvada City Council", "pop": 122_901, "adapter": "civicclerk", "portal": "https://arvadaco.portal.civicclerk.com/", "roster": "https://www.arvadaco.gov/212/City-Council", "lat": 39.8028, "lng": -105.0875},
    {"ocd": "ocd-division/country:us/state:co/place:westminster", "name": "Westminster City Council", "pop": 116_182, "adapter": "primegov", "portal": "https://cityofwestminster.primegov.com/public/portal", "roster": "https://www.westminsterco.gov/158/Our-Councillors", "lat": 39.8367, "lng": -105.0372},
    {"ocd": "ocd-division/country:us/state:co/place:greeley", "name": "Greeley City Council", "pop": 115_073, "adapter": "civicclerk", "portal": "https://greeleyco.portal.civicclerk.com/", "roster": "https://greeleyco.gov/city-council/", "lat": 40.4233, "lng": -104.7091},
    {"ocd": "ocd-division/country:us/state:co/place:pueblo", "name": "Pueblo City Council", "pop": 110_404, "adapter": "civicclerk", "portal": "https://puebloco.portal.civicclerk.com/", "roster": "https://www.pueblo.us/102/City-Council", "lat": 38.2544, "lng": -104.6091},
    {"ocd": "ocd-division/country:us/state:co/place:centennial", "name": "Centennial City Council", "pop": 108_658, "adapter": "onbase", "portal": "https://www.centennialco.gov/Government/Mayor-Council/City-Council-Meetings/Agendas-Minutes", "roster": "https://www.centennialco.gov/Government/Mayor-Council", "lat": 39.5807, "lng": -104.8772},
    {"ocd": "ocd-division/country:us/state:co/place:boulder", "name": "Boulder City Council", "pop": 105_689, "adapter": "primegov", "portal": "https://bouldercolorado.primegov.com/public/portal", "roster": "https://bouldercolorado.gov/government/city-council", "lat": 40.0150, "lng": -105.2705},
    {"ocd": "ocd-division/country:us/state:co/place:longmont", "name": "Longmont City Council", "pop": 100_109, "adapter": "primegov", "portal": "https://longmont.primegov.com/public/portal", "roster": "https://longmontcolorado.gov/government/mayor-city-council-members/", "lat": 40.1672, "lng": -105.1019},
    {"ocd": "ocd-division/country:us/state:co/place:castle_rock", "name": "Castle Rock Town Council", "pop": 83_815, "adapter": "unclaimed", "portal": "https://www.crgov.com/1600/Town-Council", "roster": "", "lat": 39.3722, "lng": -104.8561},
    {"ocd": "ocd-division/country:us/state:co/place:loveland", "name": "Loveland City Council", "pop": 81_387, "adapter": "civicplus_403", "portal": "https://www.lovgov.org/city-government/city-council", "roster": "", "lat": 40.3978, "lng": -105.0750},
    {"ocd": "ocd-division/country:us/state:co/place:broomfield", "name": "Broomfield City Council", "pop": 79_174, "adapter": "civicplus_403", "portal": "https://www.broomfield.org/4079/Broomfield-Council-Meetings", "roster": "", "lat": 39.9205, "lng": -105.0867},
    {"ocd": "ocd-division/country:us/state:co/place:commerce_city", "name": "Commerce City Council", "pop": 72_345, "adapter": "legistar", "portal": "https://commerce.legistar.com/", "roster": "https://www.c3gov.com/Government/City-Council", "lat": 39.8083, "lng": -104.9339},
    {"ocd": "ocd-division/country:us/state:co/place:grand_junction", "name": "Grand Junction City Council", "pop": 71_827, "adapter": "civicclerk", "portal": "https://grandjunctionco.portal.civicclerk.com/", "roster": "https://www.gjcity.org/180/City-Council", "lat": 39.0639, "lng": -108.5506},
    {"ocd": "ocd-division/country:us/state:co/place:parker", "name": "Parker Town Council", "pop": 65_985, "adapter": "unclaimed", "portal": "https://www.parkerco.gov/181/Town-Council", "roster": "", "lat": 39.5186, "lng": -104.7614},
    {"ocd": "ocd-division/country:us/state:co/place:littleton", "name": "Littleton City Council", "pop": 46_246, "adapter": "unclaimed", "portal": "https://www.littletonco.gov/Government/City-Council", "roster": "", "lat": 39.6133, "lng": -105.0166},
]

READY_CANDIDATES = {"arvada", "pueblo", "commerce_city", "grand_junction"}


def probe_endpoint(adapter: str, portal: str) -> Tuple[bool, str]:
    try:
        if adapter == "civicclerk":
            tenant = portal.split("//")[1].split(".")[0]
            r = requests.get(f"https://{tenant}.api.civicclerk.com/v1/Events?$top=3", headers=HEADERS, timeout=12)
            return r.status_code == 200, f"HTTP {r.status_code} ({len(r.json().get('value', [])) if r.ok else 0} events)"
        if adapter == "legistar":
            client = portal.split("//")[1].split(".")[0]
            r = requests.get(f"https://webapi.legistar.com/v1/{client}/Events?$top=3", headers=HEADERS, timeout=12)
            return r.status_code == 200, f"HTTP {r.status_code} ({len(r.json()) if r.ok else 0} events)"
    except Exception as exc:
        return False, str(exc)[:60]
    return False, "skipped"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Colorado 80% population coverage & probe ready cities.")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--seed-passing", action="store_true", help="Insert & activate passing ready-now cities into DB")
    args = parser.parse_args()

    top20_total = sum(c["pop"] for c in TOP_20_CITIES)
    conn = sqlite3.connect(args.db)
    active_ids = {
        r[0] for r in conn.execute("SELECT ocd_division_id FROM jurisdictions WHERE COALESCE(status,'active')='active'").fetchall()
    }
    jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}

    active_top20_pop = sum(c["pop"] for c in TOP_20_CITIES if c["ocd"] in active_ids)
    print(f"=== COLORADO TOP-20 MUNICIPAL POPULATION COVERAGE (2025 Census) ===")
    print(f"Top-20 Cities Combined Population: {top20_total:,}")
    print(f"Currently Active in DB:            {active_top20_pop:,} ({active_top20_pop / top20_total * 100:.1f}% of Top-20)\n")

    print("=== PROBING 4 ZERO-CODE-READY CITIES (Arvada, Pueblo, Commerce City, Grand Junction) ===")
    passing = []
    for c in TOP_20_CITIES:
        slug = c["ocd"].split(":")[-1]
        if slug not in READY_CANDIDATES:
            continue
        ok, detail = probe_endpoint(c["adapter"], c["portal"])
        print(f"  [{'PASS' if ok else 'FAIL'}] {c['name']:30s} | pop={c['pop']:7,} | {c['adapter']:10s} | {detail}")
        if ok:
            passing.append(c)

    if args.seed_passing and passing:
        for c in passing:
            cols = ["ocd_division_id", "name", "level", "adapter_type", "portal_url", "status"]
            vals = [c["ocd"], c["name"], "city", c["adapter"], c["portal"], "active"]
            if "roster_url" in jur_cols:
                cols.append("roster_url")
                vals.append(c["roster"])
            if "latitude" in jur_cols and "longitude" in jur_cols:
                cols.extend(["latitude", "longitude"])
                vals.extend([c["lat"], c["lng"]])
            placeholders = ", ".join("?" for _ in cols)
            conn.execute(
                f"INSERT OR REPLACE INTO jurisdictions ({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
        conn.commit()
        new_pop = active_top20_pop + sum(c["pop"] for c in passing if c["ocd"] not in active_ids)
        print(f"\n[SEEDED] Activated {len(passing)} cities! Top-20 coverage is now {new_pop:,} ({new_pop / top20_total * 100:.1f}%).")
    conn.close()


if __name__ == "__main__":
    main()
