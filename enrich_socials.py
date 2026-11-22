import json
import re
import time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

from db import get_connection, init_db

HEADERS = {"User-Agent": "CivicPulseBot/1.0 (+https://civics-d03.pages.dev)"}

SOCIAL_DOMAINS = {
    "x.com": "x",
    "twitter.com": "x",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
}


def extract_social_urls(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        raw_href = a.get("href")
        if not isinstance(raw_href, str):
            continue
        href = raw_href.strip()
        if not href.startswith("http"):
            continue
        netloc = urlparse(href).netloc.lower().replace("www.", "")
        # Skip generic share/portal footer links
        if any(skip in href.lower() for skip in ("/share", "intent/tweet", "sharer.php", "ballotpedia", "fcgov", "denvergov", "larimer")):
            continue
        for domain, key in SOCIAL_DOMAINS.items():
            if netloc == domain or netloc.endswith("." + domain):
                if key not in found:
                    found[key] = href
    return found

def enrich_all_profiles() -> None:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.ocd_person_id, e.name, e.website_url, e.social_links_json
            FROM entities e
            JOIN jurisdictions j ON e.jurisdiction_id = j.ocd_division_id
            WHERE e.active = 1 AND (j.status IS NULL OR j.status = 'active')
            """
        ).fetchall()

        updated = 0
        for row in rows:
            pid = row["ocd_person_id"]
            name = row["name"].strip()
            existing = json.loads(row["social_links_json"] or "{}")

            # 1. Check canonical Ballotpedia URL (e.g., https://ballotpedia.org/Emily_Francis)
            bp_slug = re.sub(r"\s+", "_", name)
            bp_url = f"https://ballotpedia.org/{bp_slug}"
            try:
                resp = requests.get(bp_url, headers=HEADERS, timeout=12)
                if resp.status_code == 200 and name.split()[-1].lower() in resp.text.lower():
                    existing["ballotpedia"] = bp_url
                    bp_socials = extract_social_urls(resp.text)
                    for k, v in bp_socials.items():
                        existing.setdefault(k, v)
            except Exception:
                pass

            # 2. Check official municipal/county bio URL if present
            if row["website_url"]:
                try:
                    w_resp = requests.get(row["website_url"], headers=HEADERS, timeout=12)
                    if w_resp.status_code == 200:
                        web_socials = extract_social_urls(w_resp.text)
                        for k, v in web_socials.items():
                            existing.setdefault(k, v)
                except Exception:
                    pass

            conn.execute(
                "UPDATE entities SET social_links_json = ? WHERE ocd_person_id = ?",
                (json.dumps(existing), pid),
            )
            updated += 1
            print(f"[{name}] -> {existing}")
            time.sleep(0.5)  # Polite rate limit

        conn.commit()
        print(f"Enriched {updated} active legislator profile(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    enrich_all_profiles()