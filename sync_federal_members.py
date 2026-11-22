import json
import os
from pathlib import Path
import requests

OUTPUT_PATH = Path("public/data/federal_co.json")
API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()


def sync_co_federal_members() -> None:
    """
    Fetches current Colorado U.S. House Representatives from the free Congress.gov v3 API
    (https://api.data.gov/signup/) and writes a lightweight static lookup to public/data/federal_co.json.
    If CONGRESS_API_KEY is not set, writes official directory fallback links so the UI always works.
    """
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    districts = {}

    if API_KEY:
        url = f"https://api.congress.gov/v3/member/CO?currentMember=true&limit=50&api_key={API_KEY}"
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            members = resp.json().get("members", [])
            for m in members:
                dist = m.get("district")
                if dist is None:
                    continue
                cd_slug = "at-large" if str(dist) in ("0", "00") else str(int(dist))
                ocd_id = f"ocd-division/country:us/state:co/cd:{cd_slug}"
                districts[ocd_id] = {
                    "ocd_division_id": ocd_id,
                    "district_label": f"Colorado Congressional District {cd_slug}",
                    "representative_name": m.get("name", ""),
                    "party": m.get("partyName", ""),
                    "bioguide_id": m.get("bioguideId", ""),
                    "congress_url": f"https://www.congress.gov/member/{m.get('bioguideId', '')}" if m.get("bioguideId") else "https://www.house.gov/representatives/find-your-representative",
                    "image_url": (m.get("depiction") or {}).get("imageUrl", ""),
                }
            print(f"Fetched {len(districts)} current Colorado U.S. House member(s) from Congress.gov API.")
        except Exception as exc:
            print(f"Congress.gov API fetch failed ({exc}); writing directory fallback links.")
    else:
        print("CONGRESS_API_KEY not set; writing official Congress.gov / House.gov lookup links.")

    # Ensure all 8 Colorado districts have at least an official lookup entry
    for num in range(1, 9):
        ocd_id = f"ocd-division/country:us/state:co/cd:{num}"
        if ocd_id not in districts:
            districts[ocd_id] = {
                "ocd_division_id": ocd_id,
                "district_label": f"Colorado Congressional District {num}",
                "representative_name": "",
                "party": "",
                "bioguide_id": "",
                "congress_url": "https://www.house.gov/representatives/find-your-representative",
                "image_url": "",
            }

    OUTPUT_PATH.write_text(json.dumps({"districts": districts}, indent=2), encoding="utf-8")
    print(f"Saved federal lookup file to {OUTPUT_PATH}")


if __name__ == "__main__":
    sync_co_federal_members()
