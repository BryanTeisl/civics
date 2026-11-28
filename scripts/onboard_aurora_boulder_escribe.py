"""Wires the eSCRIBE adapter and activates Aurora City Council & Boulder County BOCC.

Usage:
  python scripts/onboard_aurora_boulder_escribe.py
"""
from __future__ import annotations

import py_compile
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def wire_adapter_registration() -> None:
    init_p = REPO_ROOT / "civicpulse" / "adapters" / "__init__.py"
    if init_p.exists():
        src = init_p.read_text(encoding="utf-8")
        if "escribe" not in src:
            src = src.rstrip() + "\nfrom . import escribe  # noqa: F401\n"
            init_p.write_text(src, encoding="utf-8")
            print("[PATCHED] Registered escribe in civicpulse/adapters/__init__.py")

    test_p = REPO_ROOT / "tests" / "test_adapters.py"
    if test_p.exists():
        tsrc = test_p.read_text(encoding="utf-8")
        if '"gov_web"}' in tsrc and "escribe" not in tsrc:
            tsrc = tsrc.replace('"gov_web"}', '"gov_web", "escribe"}')
            test_p.write_text(tsrc, encoding="utf-8")
            print("[PATCHED] Updated expected adapter set in tests/test_adapters.py")


def wire_autonomous_onboarder_escribe() -> None:
    p = REPO_ROOT / "civicpulse" / "pipeline" / "autonomous_onboarder.py"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    if "escribemeetings.com" in src:
        print("[OK] autonomous_onboarder.py already detects eSCRIBE portals")
        return

    anchor = '        if "boarddocs.com" in low:'
    escribe_check = (
        '        if "escribemeetings.com" in low:\n'
        '            parsed_u = urlparse(u)\n'
        '            base_u = f"{parsed_u.scheme or \'https\'}://{parsed_u.netloc}"\n'
        '            try:\n'
        '                r = requests.post(\n'
        '                    f"{base_u}/MeetingsCalendarView.aspx/GetCalendarMeetings",\n'
        '                    json={"calendarStartDate": f"{yr}-01-01", "calendarEndDate": f"{yr}-12-31"},\n'
        '                    headers={**HEADERS, "Content-Type": "application/json; charset=utf-8"},\n'
        '                    timeout=10,\n'
        '                )\n'
        '                if r.status_code == 200 and isinstance(r.json().get("d"), list):\n'
        '                    return {"status": "supported", "adapter_type": "escribe", "portal_url": base_u, "sample_count": len(r.json()["d"])}\n'
        '            except Exception:\n'
        '                pass\n'
        '            try:\n'
        '                r = requests.get(base_u, headers=HEADERS, timeout=10)\n'
        '                if r.status_code == 200:\n'
        '                    return {"status": "supported", "adapter_type": "escribe", "portal_url": base_u, "sample_count": 1}\n'
        '            except Exception:\n'
        '                pass\n'
    )
    if anchor in src:
        src = src.replace(anchor, escribe_check + "\n" + anchor, 1)
        src = src.replace(
            'f"https://{slug}.portal.civicclerk.com/",',
            'f"https://{slug}.portal.civicclerk.com/",\n            f"https://pub-{slug}.escribemeetings.com/",',
            1,
        )
        src = src.replace(
            '(".legistar.com", ".primegov.com", "civicclerk.com", "boarddocs.com")',
            '(".legistar.com", ".primegov.com", "civicclerk.com", "boarddocs.com", "escribemeetings.com")',
            1,
        )
        p.write_text(src, encoding="utf-8")
        py_compile.compile(str(p), doraise=True)
        print("[PATCHED] Added eSCRIBE discovery to civicpulse/pipeline/autonomous_onboarder.py")


def wire_v3_contact_emails() -> None:
    p = REPO_ROOT / "civicpulse" / "pipeline" / "v3_intelligence.py"
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    anchor = '"ocd-division/country:us/state:co/school_district:boulder_valley_re2": {'
    addition = (
        '"ocd-division/country:us/state:co/place:aurora": {\n'
        '        "council_email": "citycouncil@auroragov.org",\n'
        '        "clerk_url": "https://www.auroragov.org/city_hall/mayor___city_council",\n'
        '    },\n'
        '    "ocd-division/country:us/state:co/county:boulder": {\n'
        '        "council_email": "commissioners@bouldercounty.gov",\n'
        '        "clerk_url": "https://bouldercounty.gov/government/board-of-county-commissioners/",\n'
        '    },\n'
        '    '
    )
    if "place:aurora" not in src and anchor in src:
        p.write_text(src.replace(anchor, addition + anchor, 1), encoding="utf-8")
        py_compile.compile(str(p), doraise=True)
        print("[PATCHED] Added Aurora & Boulder County official emails to v3_intelligence.py")


def activate_aurora_and_boulder_county(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    ent_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}

    targets = [
        {
            "ocd_division_id": "ocd-division/country:us/state:co/place:aurora",
            "name": "Aurora City Council",
            "level": "city",
            "adapter_type": "escribe",
            "portal_url": "https://pub-auroraco.escribemeetings.com",
            "roster_url": "https://www.auroragov.org/city_hall/mayor___city_council",
            "council_email": "citycouncil@auroragov.org",
            "lat": 39.7294,
            "lng": -104.8319,
        },
        {
            "ocd_division_id": "ocd-division/country:us/state:co/county:boulder",
            "name": "Boulder County Board of Commissioners",
            "level": "county",
            "adapter_type": "escribe",
            "portal_url": "https://pub-bouldercounty.escribemeetings.com",
            "roster_url": "https://bouldercounty.gov/government/board-of-county-commissioners/",
            "council_email": "commissioners@bouldercounty.gov",
            "lat": 40.0150,
            "lng": -105.2705,
        },
    ]

    for t in targets:
        jid = t["ocd_division_id"]
        sets = ["name = ?", "level = ?", "adapter_type = ?", "portal_url = ?", "status = 'active'"]
        vals = [t["name"], t["level"], t["adapter_type"], t["portal_url"]]
        if "roster_url" in jur_cols:
            sets.append("roster_url = ?")
            vals.append(t["roster_url"])
        if "council_email" in jur_cols:
            sets.append("council_email = ?")
            vals.append(t["council_email"])
        vals.append(jid)

        cur = conn.execute(f"UPDATE jurisdictions SET {', '.join(sets)} WHERE ocd_division_id = ?", vals)
        if cur.rowcount == 0:
            cols = ["ocd_division_id", "name", "level", "adapter_type", "portal_url", "status"]
            ins_vals = [jid, t["name"], t["level"], t["adapter_type"], t["portal_url"], "active"]
            if "roster_url" in jur_cols:
                cols.append("roster_url")
                ins_vals.append(t["roster_url"])
            if "council_email" in jur_cols:
                cols.append("council_email")
                ins_vals.append(t["council_email"])
            if "lat" in jur_cols and "lng" in jur_cols:
                cols.extend(["lat", "lng"])
                ins_vals.extend([t["lat"], t["lng"]])
            if "latitude" in jur_cols and "longitude" in jur_cols:
                cols.extend(["latitude", "longitude"])
                ins_vals.extend([t["lat"], t["lng"]])
            ph = ", ".join("?" for _ in cols)
            conn.execute(f"INSERT INTO jurisdictions ({', '.join(cols)}) VALUES ({ph})", ins_vals)
        print(f"[ACTIVATED] {t['name']} -> {t['adapter_type']} ({t['portal_url']})")

    aurora_jid = "ocd-division/country:us/state:co/place:aurora"
    existing_aurora = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE jurisdiction_id = ? AND COALESCE(active, 1) = 1",
        (aurora_jid,),
    ).fetchone()[0]
    if existing_aurora == 0:
        aurora_members = [
            ("ocd-person/co-aurora-coffman", "Mike Coffman", "Mayor", "At-Large"),
            ("ocd-person/co-aurora-jurinsky", "Danielle Jurinsky", "Council Member", "At-Large"),
            ("ocd-person/co-aurora-gardner", "Curtis Gardner", "Mayor Pro Tem", "At-Large"),
            ("ocd-person/co-aurora-coombs", "Alison Coombs", "Council Member", "At-Large"),
            ("ocd-person/co-aurora-murillo", "Crystal Murillo", "Council Member", "Ward I"),
            ("ocd-person/co-aurora-sundberg", "Steve Sundberg", "Council Member", "Ward II"),
            ("ocd-person/co-aurora-medina", "Ruben Medina", "Council Member", "Ward III"),
            ("ocd-person/co-aurora-hancock", "Stephanie Hancock", "Council Member", "Ward IV"),
            ("ocd-person/co-aurora-lawson", "Angela Lawson", "Council Member", "Ward V"),
            ("ocd-person/co-aurora-bergan", "Françoise Bergan", "Council Member", "Ward VI"),
            ("ocd-person/co-aurora-kassaw", "Amsalu Kassaw", "Council Member", "At-Large"),
        ]
        for pid, name, role, dist in aurora_members:
            cols = ["ocd_person_id", "jurisdiction_id", "name", "role", "district"]
            vals = [pid, aurora_jid, name, role, dist]
            if "active" in ent_cols:
                cols.append("active")
                vals.append(1)
            ph = ", ".join("?" for _ in cols)
            conn.execute(f"INSERT OR IGNORE INTO entities ({', '.join(cols)}) VALUES ({ph})", vals)
        print("[SEEDED] Baseline Aurora City Council roster (11 seats)")

    conn.commit()
    conn.close()


def main() -> None:
    wire_adapter_registration()
    wire_autonomous_onboarder_escribe()
    wire_v3_contact_emails()
    activate_aurora_and_boulder_county(REPO_ROOT / "core_civic.db")


if __name__ == "__main__":
    main()
