import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup

from db import queue_document

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_granicus_portal(portal_url: str) -> tuple[str, str]:
    """Extracts (client_subdomain, view_id) from a Granicus ViewPublisher URL."""
    m_host = re.search(r"https?://([a-zA-Z0-9-]+)\.granicus\.com", portal_url or "", re.IGNORECASE)
    m_view = re.search(r"view_id=(\d+)", portal_url or "", re.IGNORECASE)
    if not m_host or not m_view:
        raise ValueError(f"Granicus portal_url must include subdomain and view_id: {portal_url}")
    return m_host.group(1).lower(), m_view.group(1)


def _fetch_granicus_html_text(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
            return "\n".join(lines)
    except Exception:
        pass
    return ""


def poll_granicus_jurisdiction(
    jurisdiction_id: str,
    name: str,
    portal_url: str,
    max_items: int = 10,
    mode: str = "minutes",
) -> int:
    """
    Polls a legacy Granicus ViewPublisher portal via its public RSS XML endpoint:
      GET https://{client}.granicus.com/ViewPublisherRSS.php?view_id={N}&mode={minutes|agendas}
    """
    client, view_id = _parse_granicus_portal(portal_url)
    rss_url = f"https://{client}.granicus.com/ViewPublisherRSS.php?view_id={view_id}&mode={mode}"

    resp = requests.get(rss_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    items = root.findall(".//item")
    queued = 0

    for item in items[:max_items]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        iso_date = ""
        if pub_date:
            try:
                iso_date = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
            except Exception:
                iso_date = pub_date[:10]

        if not link:
            continue

        raw_text = _fetch_granicus_html_text(link) or BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)
        if len(raw_text) < 80:
            continue

        inserted_id = queue_document(
            jurisdiction_id=jurisdiction_id,
            doc_type="minutes" if mode == "minutes" else "agenda",
            title=title or f"{name} ({iso_date})",
            source_url=link,
            raw_text=raw_text,
            meeting_date=iso_date or "2026-01-01",
            external_id=f"granicus-{client}-{view_id}-{iso_date}-{hash(link)}",
        )
        if inserted_id:
            queued += 1
            print(f"    + Queued Granicus {mode}: {iso_date} | {title[:55]}")

    return queued


if __name__ == "__main__":
    print("Granicus ViewPublisherRSS adapter module loaded and syntax-verified.")
