import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import requests

from db import queue_document

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CivicPulseBot/1.0; +https://civics-d03.pages.dev)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}


def extract_subdomain(portal_url: str) -> str:
    m = re.search(r"https?://([a-zA-Z0-9-]+)\.primegov\.com", portal_url or "")
    if not m:
        raise ValueError(f"Invalid PrimeGov portal_url: {portal_url}")
    return m.group(1).lower()


def extract_clean_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    return "\n".join(lines)


def fetch_primegov_document_text(base_url: str, doc_entry: Dict[str, Any]) -> tuple[str, str]:
    comp_id = (
        doc_entry.get("compiledMeetingDocumentFileId")
        or doc_entry.get("documentId")
        or doc_entry.get("id")
    )
    tmpl_id = doc_entry.get("templateId")
    meeting_id = doc_entry.get("meetingId")

    if comp_id:
        html_url = f"{base_url}/Portal/Meeting?compiledMeetingDocumentFileId={comp_id}"
        try:
            r = requests.get(html_url, headers=HEADERS, timeout=20)
            if r.status_code == 200 and len(r.text) > 500 and "text/html" in r.headers.get("Content-Type", ""):
                txt = extract_clean_text_from_html(r.text)
                if len(txt) > 250:
                    return txt, html_url
        except Exception:
            pass

    if tmpl_id and meeting_id:
        html_url = f"{base_url}/Portal/Meeting?meetingTemplateId={tmpl_id}&meetingId={meeting_id}"
        try:
            r = requests.get(html_url, headers=HEADERS, timeout=20)
            if r.status_code == 200 and len(r.text) > 500:
                txt = extract_clean_text_from_html(r.text)
                if len(txt) > 250:
                    return txt, html_url
        except Exception:
            pass

    return "", f"{base_url}/Public/CompiledDocument/{comp_id}" if comp_id else base_url


def poll_primegov_jurisdiction(
    jurisdiction_id: str,
    name: str,
    portal_url: str,
    year: Optional[int] = None,
    max_meetings: int = 12,
    body_filter: Optional[str] = "Council",
) -> int:
    target_year = year or datetime.now().year
    subdomain = extract_subdomain(portal_url)
    base_url = f"https://{subdomain}.primegov.com"
    api_url = f"{base_url}/api/v2/PublicPortal/ListArchivedMeetings?year={target_year}"

    resp = requests.get(api_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    meetings: List[Dict[str, Any]] = resp.json()

    queued_count = 0
    inspected = 0

    for mtg in meetings:
        if inspected >= max_meetings:
            break
        title = (mtg.get("title") or "").strip()
        if body_filter and body_filter.lower() not in title.lower():
            continue
        inspected += 1

        meeting_id = mtg.get("id")
        raw_date = str(mtg.get("dateTime") or mtg.get("date") or "")[:10]
        if "/" in raw_date:
            parts = raw_date.split("/")
            if len(parts) == 3 and len(parts[2]) == 4:
                raw_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"

        doc_list = mtg.get("documentList") or []
        if not doc_list:
            continue

        def doc_priority(d: Dict[str, Any]) -> int:
            t = (d.get("templateName") or d.get("title") or "").lower()
            if "minute" in t or "action" in t or "summary" in t:
                return 0
            if "packet" in t:
                return 2
            return 1

        for doc in sorted(doc_list, key=doc_priority)[:2]:
            doc_title = (doc.get("templateName") or doc.get("title") or title).strip()
            doc_lower = doc_title.lower()
            if "packet" in doc_lower:
                continue
            doc_type = "minutes" if ("minute" in doc_lower or "summary" in doc_lower or "action" in doc_lower) else "agenda"

            doc_copy = dict(doc)
            doc_copy["meetingId"] = meeting_id
            raw_text, source_url = fetch_primegov_document_text(base_url, doc_copy)
            if not raw_text:
                continue

            inserted_id = queue_document(
                jurisdiction_id=jurisdiction_id,
                doc_type=doc_type,
                title=f"{title} — {doc_title}",
                source_url=source_url,
                raw_text=raw_text,
                meeting_date=raw_date,
                external_id=f"primegov-{subdomain}-{meeting_id}-{doc.get('templateId', 'doc')}",
            )
            if inserted_id:
                queued_count += 1
                print(f"    + Queued PrimeGov {doc_type}: {raw_date} | {doc_title[:55]}")

    return queued_count
