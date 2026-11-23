import re
import time
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from db import queue_document


def _normalize_boarddocs_base(portal_url: str) -> str:
    """
    Normalizes a BoardDocs portal URL to its `.../Board.nsf` base path.
    Example: https://go.boarddocs.com/co/psdschools/Board.nsf/Public -> https://go.boarddocs.com/co/psdschools/Board.nsf
    """
    m = re.search(r"(https?://go\.boarddocs\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/Board\.nsf)", portal_url or "", re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid BoardDocs portal_url: {portal_url}")
    return m.group(1)


def _discover_committee_id(session: requests.Session, base_url: str, headers: Dict[str, str]) -> str:
    """
    Fetches the public landing page to establish session cookies and extract the active
    `current_committee_id` (falls back to 'A' if not explicitly embedded).
    """
    try:
        r = session.get(f"{base_url}/Public", headers=headers, timeout=15)
        if r.status_code == 200:
            m = re.search(r'current_committee_id["\']?\s*[:=]\s*["\']([A-Za-z0-9_-]+)["\']', r.text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "A"


def _extract_clean_agenda_html(html: str) -> tuple[str, str, str]:
    """Parses BoardDocs PRINT-AgendaDetailed HTML into (meeting_date_iso, meeting_title, clean_text)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    date_el = soup.find("div", {"class": "print-meeting-date"})
    title_el = soup.find("div", {"class": "print-meeting-name"})
    raw_date = date_el.get_text(strip=True) if date_el else ""
    raw_title = title_el.get_text(strip=True) if title_el else "Board of Education Meeting"

    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    return raw_date, raw_title, "\n".join(lines)


def poll_boarddocs_jurisdiction(
    jurisdiction_id: str,
    name: str,
    portal_url: str,
    max_meetings: int = 8,
    committee_id: Optional[str] = None,
) -> int:
    """
    Polls a public BoardDocs portal via its two Lotus Domino AJAX POST endpoints:
      1. POST {base_url}/BD-GetMeetingsList?open  (body: current_committee_id=...)
      2. POST {base_url}/PRINT-AgendaDetailed     (body: id=...&current_committee_id=...)
    """
    base_url = _normalize_boarddocs_base(portal_url)
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://go.boarddocs.com",
        "Referer": f"{base_url}/Public",
    }

    cid = committee_id or _discover_committee_id(session, base_url, headers)
    list_url = f"{base_url}/BD-GetMeetingsList?open"
    resp = session.post(list_url, headers=headers, data=f"current_committee_id={cid}", timeout=20)
    resp.raise_for_status()

    meetings: List[Dict[str, Any]] = resp.json()
    if not isinstance(meetings, list):
        return 0

    queued = 0
    for mtg in meetings[:max_meetings]:
        meeting_id = (mtg.get("unique") or mtg.get("unid") or "").strip()
        if not meeting_id:
            continue

        num_date = str(mtg.get("numberdate") or "").strip()  # YYYYMMDD format in BoardDocs
        iso_date = f"{num_date[:4]}-{num_date[4:6]}-{num_date[6:8]}" if len(num_date) == 8 and num_date.isdigit() else ""

        detail_url = f"{base_url}/PRINT-AgendaDetailed"
        detail_headers = dict(headers)
        detail_headers["Accept"] = "text/html, */*; q=0.01"
        payload = f"id={meeting_id}&current_committee_id={cid}"

        d_resp = session.post(detail_url, headers=detail_headers, data=payload, timeout=20)
        if d_resp.status_code != 200 or len(d_resp.text) < 300:
            continue

        _, parsed_title, clean_text = _extract_clean_agenda_html(d_resp.text)
        if len(clean_text) < 200:
            continue

        source_url = f"{base_url}/goto?open&id={meeting_id}"
        inserted_id = queue_document(
            jurisdiction_id=jurisdiction_id,
            doc_type="minutes",
            title=parsed_title,
            source_url=source_url,
            raw_text=clean_text,
            meeting_date=iso_date or "2026-01-01",
            external_id=f"boarddocs-{meeting_id}",
        )
        if inserted_id:
            queued += 1
            print(f"    + Queued BoardDocs item: {iso_date} | {parsed_title[:55]}")
        time.sleep(0.4)

    return queued


if __name__ == "__main__":
    try:
        n = poll_boarddocs_jurisdiction(
            jurisdiction_id="ocd-division/country:us/state:co/school_district:poudre_r1",
            name="Poudre School District Board of Education",
            portal_url="https://go.boarddocs.com/co/psdschools/Board.nsf/Public",
            max_meetings=4,
        )
        print(f"BoardDocs test complete. Queued {n} new document(s).")
    except Exception as exc:
        print(f"BoardDocs test encountered protection/error: {exc}")
