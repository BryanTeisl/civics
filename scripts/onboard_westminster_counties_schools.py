"""Onboards Westminster's 22 Vote Tracking PDFs + Larimer County, Boulder County,
Poudre School District, and Boulder Valley School District in CivicPulse v2.

Usage:
  python scripts/onboard_westminster_counties_schools.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def patch_primegov_westminster_vote_pdfs() -> bool:
    """Adds supplemental Vote Tracking (PDF) scraping for Westminster to primegov.py."""
    p = REPO_ROOT / "civicpulse" / "adapters" / "primegov.py"
    if not p.exists():
        print("[WARN] civicpulse/adapters/primegov.py not found; skipping patch.")
        return False

    text = p.read_text(encoding="utf-8")
    if "VOTE_TRACKING_PAGES" in text:
        print("[OK] primegov.py already has Westminster Vote Tracking PDF hook.")
        return True

    helper = """
VOTE_TRACKING_PAGES: Dict[str, str] = {
    "cityofwestminster": "https://www.westminsterco.gov/129/Meeting-Agendas",
}
VOTE_DATE_RE = re.compile(r"(\\d{1,2})/(\\d{1,2})/(\\d{4})")


def _fetch_supplemental_vote_pdfs(
    sub: str, jurisdiction_id: str, limit: int, headers: Dict[str, str], timeout: int
) -> List[DocumentRecord]:
    # Pulls official municipal Vote Tracking PDFs when PrimeGov only hosts Agenda/Packet templates
    page_url = VOTE_TRACKING_PAGES.get(sub)
    if not page_url:
        return []
    try:
        from html.parser import HTMLParser
        from urllib.parse import urljoin

        class _AnchorExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.anchors: List[tuple] = []
                self._href = ""
                self._buf: List[str] = []
                self._in_a = False

            def handle_starttag(self, tag: str, attrs: list) -> None:
                if tag.lower() == "a":
                    self._href = dict(attrs).get("href") or ""
                    self._buf = []
                    self._in_a = True

            def handle_data(self, data: str) -> None:
                if self._in_a:
                    self._buf.append(data)

            def handle_endtag(self, tag: str) -> None:
                if tag.lower() == "a" and self._in_a:
                    self.anchors.append((" ".join("".join(self._buf).split()), self._href))
                    self._in_a = False

        req_headers = dict(headers or {})
        req_headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        r = requests.get(page_url, headers=req_headers, timeout=timeout)
        if not r.ok:
            return []
        parser = _AnchorExtractor()
        parser.feed(r.text)
        results: List[DocumentRecord] = []
        seen_urls = set()
        for label, href in parser.anchors:
            if not href or not re.search(r"vote\\s*tracking", label, re.IGNORECASE):
                continue
            full_url = urljoin(page_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            m = VOTE_DATE_RE.search(label)
            mdate = f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}" if m else ""
            doc_num_m = re.search(r"/View/(\\d+)", full_url)
            doc_key = (
                doc_num_m.group(1)
                if doc_num_m
                else re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            )
            results.append(
                DocumentRecord(
                    jurisdiction_id=jurisdiction_id,
                    external_id=f"votesheet_{sub}_{doc_key}_minutes",
                    meeting_date=mdate,
                    doc_type="minutes",
                    title=f"City Council {label}",
                    source_url=full_url,
                )
            )
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []
"""

    anchor = '@register_adapter("primegov")'
    if anchor not in text:
        anchor = "@register_adapter('primegov')"
    assert anchor in text, "Could not locate @register_adapter in primegov.py"
    text = text.replace(anchor, helper + "\n\n" + anchor, 1)

    ret_anchor = "        return docs"
    assert ret_anchor in text, "Could not locate 'return docs' in primegov.py"
    text = text.replace(
        ret_anchor,
        "        docs.extend(_fetch_supplemental_vote_pdfs(sub, jurisdiction_id, limit, self.headers, self.timeout))\n"
        + ret_anchor,
        1,
    )
    p.write_text(text, encoding="utf-8")
    print("[PATCHED] Added Westminster Vote Tracking PDF scraper to civicpulse/adapters/primegov.py")
    return True


def wire_gov_web_adapter() -> None:
    """Imports gov_web in civicpulse/adapters/__init__.py and updates test_adapters.py if needed."""
    init_p = REPO_ROOT / "civicpulse" / "adapters" / "__init__.py"
    if init_p.exists():
        src = init_p.read_text(encoding="utf-8")
        if "gov_web" not in src:
            src = src.rstrip() + "\nfrom . import gov_web  # noqa: F401\n"
            init_p.write_text(src, encoding="utf-8")
            print("[PATCHED] Registered gov_web in civicpulse/adapters/__init__.py")

    test_p = REPO_ROOT / "tests" / "test_adapters.py"
    if test_p.exists():
        tsrc = test_p.read_text(encoding="utf-8")
        if '{"civicclerk", "legistar", "primegov"}' in tsrc and "gov_web" not in tsrc:
            tsrc = tsrc.replace(
                '{"civicclerk", "legistar", "primegov"}',
                '{"civicclerk", "legistar", "primegov", "gov_web"}',
            )
            test_p.write_text(tsrc, encoding="utf-8")
            print("[PATCHED] Updated expected adapter set in tests/test_adapters.py")


def upsert_jurisdictions_and_rosters(db_path: Path) -> None:
    """Seeds/activates Larimer County, Boulder County, Poudre SD, BVSD, and baseline rosters."""
    seed_file = REPO_ROOT / "config" / "jurisdictions" / "colorado_counties_and_schools.json"
    seed_data = json.loads(seed_file.read_text(encoding="utf-8"))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    ent_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}

    try:
        for j in seed_data["jurisdictions"]:
            jid = j["ocd_division_id"]
            exists = conn.execute(
                "SELECT 1 FROM jurisdictions WHERE ocd_division_id = ?", (jid,)
            ).fetchone()
            if exists:
                sets = ["name = ?", "level = ?", "adapter_type = ?", "portal_url = ?", "status = ?"]
                vals = [j["name"], j["level"], j["adapter_type"], j["portal_url"], j["status"]]
                if "roster_url" in jur_cols:
                    sets.append("roster_url = ?")
                    vals.append(j.get("roster_url", ""))
                vals.append(jid)
                conn.execute(
                    f"UPDATE jurisdictions SET {', '.join(sets)} WHERE ocd_division_id = ?",
                    vals,
                )
            else:
                cols = ["ocd_division_id", "name", "level", "adapter_type", "portal_url", "status"]
                vals = [jid, j["name"], j["level"], j["adapter_type"], j["portal_url"], j["status"]]
                if "roster_url" in jur_cols:
                    cols.append("roster_url")
                    vals.append(j.get("roster_url", ""))
                if "latitude" in jur_cols and "longitude" in jur_cols:
                    cols.extend(["latitude", "longitude"])
                    vals.extend([j.get("latitude"), j.get("longitude")])
                placeholders = ", ".join("?" for _ in cols)
                conn.execute(
                    f"INSERT INTO jurisdictions ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )

        if "roster_url" in jur_cols:
            conn.execute(
                """
                UPDATE jurisdictions
                SET roster_url = COALESCE(NULLIF(roster_url, ''), 'https://www.westminsterco.gov/158/Our-Councillors')
                WHERE ocd_division_id = 'ocd-division/country:us/state:co/place:westminster'
                """
            )

        baseline_rosters = {
            "ocd-division/country:us/state:co/place:westminster": [
                ("ocd-person/co-westminster-mcnally", "Nancy McNally", "Mayor", "At-Large"),
                ("ocd-person/co-westminster-demott", "David DeMott", "Mayor Pro Tem", "At-Large"),
                ("ocd-person/co-westminster-carmelia", "Kristine Carmelia", "Councillor", "At-Large"),
                ("ocd-person/co-westminster-emmert", "Sarah Nurmela", "Councillor", "At-Large"),
                ("ocd-person/co-westminster-ezell", "Obi Ezeadi", "Councillor", "At-Large"),
                ("ocd-person/co-westminster-hott", "Amber Hott", "Councillor", "At-Large"),
                ("ocd-person/co-westminster-ireland", "Claire Carmelia", "Councillor", "At-Large"),
            ],
            "ocd-division/country:us/state:co/county:larimer": [
                ("ocd-person/co-larimer-kefalas", "John Kefalas", "County Commissioner", "District 1"),
                ("ocd-person/co-larimer-stephens", "Kristin Stephens", "County Commissioner", "District 2"),
                ("ocd-person/co-larimer-shadduck", "Jody Shadduck-McNally", "County Commissioner", "District 3"),
            ],
            "ocd-division/country:us/state:co/county:boulder": [
                ("ocd-person/co-boulder-loachamin", "Marta Loachamin", "County Commissioner", "District 2"),
                ("ocd-person/co-boulder-levy", "Claire Levy", "County Commissioner", "District 1"),
                ("ocd-person/co-boulder-stoltzmann", "Ashley Stoltzmann", "County Commissioner", "District 3"),
            ],
            "ocd-division/country:us/state:co/school_district:poudre_r1": [
                ("ocd-person/co-psd-bicknell", "Kristen Draper", "Board President", "District C"),
                ("ocd-person/co-psd-donovan", "Carolyn Reed", "Board Vice President", "District D"),
                ("ocd-person/co-psd-brooks", "Jessica Zamora", "Board Director", "District A"),
                ("ocd-person/co-psd-peterson", "Jim Brokish", "Board Director", "District B"),
                ("ocd-person/co-psd-schonberger", "Conor Duffy", "Board Director", "District E"),
                ("ocd-person/co-psd-gorman", "Kevin Havelda", "Board Director", "District F"),
                ("ocd-person/co-psd-sullivan", "Scott Schoenbauer", "Board Director", "District G"),
            ],
            "ocd-division/country:us/state:co/school_district:boulder_valley_re2": [
                ("ocd-person/co-bvsd-gebhardt", "Lisa Sweeney-Miran", "Board President", "District E"),
                ("ocd-person/co-bvsd-raj", "Nicole Rajpal", "Board Director", "District A"),
                ("ocd-person/co-bvsd-harris", "Kitty Sargent", "Board Director", "District B"),
                ("ocd-person/co-bvsd-nielsen", "Alex Medler", "Board Director", "District C"),
                ("ocd-person/co-bvsd-azad", "Lalenia Quinlan Aweida", "Board Director", "District D"),
                ("ocd-person/co-bvsd-garcia", "Jorge Chavez", "Board Director", "District F"),
                ("ocd-person/co-bvsd-anderson", "Jason Unger", "Board Director", "District G"),
            ],
        }

        seeded_people = 0
        for jid, members in baseline_rosters.items():
            cnt = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE jurisdiction_id = ? AND COALESCE(active, 1) = 1",
                (jid,),
            ).fetchone()[0]
            if cnt > 0:
                continue
            for pid, name, role, district in members:
                cols = ["ocd_person_id", "jurisdiction_id", "name", "role", "district"]
                vals = [pid, jid, name, role, district]
                if "active" in ent_cols:
                    cols.append("active")
                    vals.append(1)
                if "party" in ent_cols:
                    cols.append("party")
                    vals.append("Nonpartisan")
                placeholders = ", ".join("?" for _ in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO entities ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
                seeded_people += 1

        conn.commit()
        print(f"[DB] Activated 4 county/school jurisdictions & seeded {seeded_people} missing roster member(s).")
    finally:
        conn.close()


def main() -> None:
    patch_primegov_westminster_vote_pdfs()
    wire_gov_web_adapter()
    db_file = REPO_ROOT / "core_civic.db"
    if db_file.exists():
        upsert_jurisdictions_and_rosters(db_file)
    else:
        print("[INFO] core_civic.db not found at repo root; skipping DB upsert.")


if __name__ == "__main__":
    main()
