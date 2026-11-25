from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, is_elected_council_meeting, register_adapter

MINUTES_HINT_RE = re.compile(
    r"\b(minute|minutes|action\s+summary|action\s+agenda|summary|approved|motion)\b",
    re.IGNORECASE,
)
PACKET_HINT_RE = re.compile(r"\b(packet|full\s+agenda\s+packet|attachments?)\b", re.IGNORECASE)


def _extract_subdomain(portal_url: str) -> str:
    parsed = urlparse((portal_url or "").strip())
    host = parsed.netloc.lower()
    if ".primegov.com" in host:
        return host.split(".primegov.com")[0]
    return host.split(".")[0]


def _normalize_date(raw: str) -> str:
    val = (raw or "").strip()[:10]
    if "/" in val:
        parts = val.split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    return val


@register_adapter("primegov")
class PrimeGovAdapter(BaseAdapter):
    is_structured = True

    def normalize_portal_url(self, portal_url: str) -> str:
        sub = _extract_subdomain(portal_url)
        return f"https://{sub}.primegov.com/public/portal" if sub else portal_url

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        sub = _extract_subdomain(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        api_url = f"https://{sub}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
        try:
            r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200 and isinstance(r.json(), list):
                data = r.json()
                sample = (data[0].get("title") or "PrimeGov Meeting") if data else ""
                return ProbeResult(True, 200, len(data), sample[:70], self.name, norm_url)
            return ProbeResult(False, r.status_code, 0, "HTTP error", self.name, norm_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, norm_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        sub = _extract_subdomain(portal_url)
        base_url = f"https://{sub}.primegov.com"
        api_url = f"{base_url}/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
        r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        meetings: List[Dict[str, Any]] = r.json() if isinstance(r.json(), list) else []

        meetings.sort(
            key=lambda m: _normalize_date(str(m.get("dateTime") or m.get("date") or "")),
            reverse=True,
        )

        docs: List[DocumentRecord] = []
        matched_meetings = 0

        for mtg in meetings:
            if matched_meetings >= limit:
                break
            title = (mtg.get("title") or "").strip()
            if not is_elected_council_meeting(title):
                continue

            matched_meetings += 1
            meeting_id = str(mtg.get("id") or "")
            mdate = _normalize_date(str(mtg.get("dateTime") or mtg.get("date") or ""))
            doc_list = mtg.get("documentList") or []

            def _doc_rank(d: Dict[str, Any]) -> int:
                label = f"{d.get('templateName') or ''} {d.get('title') or ''} {d.get('documentType') or ''}"
                if MINUTES_HINT_RE.search(label):
                    return 0
                if PACKET_HINT_RE.search(label):
                    return 2
                return 1

            non_packet = [
                d for d in doc_list
                if not PACKET_HINT_RE.search((d.get("templateName") or d.get("title") or "").strip())
            ]
            # Fallback for portals like Westminster that only publish "HTML Packet" / "Packet"
            candidates = non_packet or [
                d for d in doc_list
                if "html" in ((d.get("templateName") or d.get("title") or "").lower())
            ] or doc_list

            added_for_meeting = 0
            for d in sorted(candidates, key=_doc_rank):
                label = (d.get("templateName") or d.get("title") or "").strip()
                is_minutes = bool(MINUTES_HINT_RE.search(f"{label} {d.get('documentType') or ''}"))
                doc_type = "minutes" if is_minutes else "agenda"

                doc_file_id = d.get("compiledMeetingDocumentFileId") or d.get("id") or d.get("templateId")
                if not doc_file_id:
                    continue

                if is_minutes:
                    source_url = f"{base_url}/Public/CompiledDocument/{doc_file_id}"
                else:
                    source_url = f"{base_url}/Portal/Meeting?meetingTemplateId={doc_file_id}"

                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"primegov_{sub}_{meeting_id}_{doc_file_id}_{doc_type}",
                        meeting_date=mdate,
                        doc_type=doc_type,
                        title=f"{title} — {label}" if label and label.lower() not in title.lower() else title,
                        source_url=source_url,
                    )
                )
                added_for_meeting += 1
                if added_for_meeting >= 2:
                    break

        return docs
