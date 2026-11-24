from __future__ import annotations

from typing import List
from urllib.parse import urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter


def _extract_subdomain(portal_url: str) -> str:
    host = urlparse(portal_url).netloc.lower()
    if ".primegov.com" in host:
        return host.split(".primegov.com")[0]
    return host.split(".")[0]


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
            if r.status_code == 200:
                data = r.json()
                sample = (data[0].get("title") or "PrimeGov Meeting") if isinstance(data, list) and data else ""
                return ProbeResult(True, 200, len(data) if isinstance(data, list) else 0, sample[:70], self.name, norm_url)
            return ProbeResult(False, r.status_code, 0, "HTTP error", self.name, norm_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, norm_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        sub = _extract_subdomain(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        api_url = f"https://{sub}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
        r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        meetings = r.json() if isinstance(r.json(), list) else []

        docs: List[DocumentRecord] = []
        for m in meetings[:limit]:
            mid = str(m.get("id") or "")
            title = (m.get("title") or "Council Meeting").strip()
            raw_date = str(m.get("dateTime") or m.get("date") or "")[:10]
            doc_list = m.get("documentList") or []
            if doc_list:
                for d in doc_list:
                    did = str(d.get("id") or mid)
                    template_name = (d.get("templateName") or "agenda").lower()
                    doc_type = "minutes" if "minute" in template_name else "agenda"
                    doc_url = f"https://{sub}.primegov.com/Portal/Meeting?meetingTemplateId={did}"
                    docs.append(
                        DocumentRecord(
                            jurisdiction_id=jurisdiction_id,
                            external_id=f"primegov_{mid}_{did}",
                            meeting_date=raw_date,
                            doc_type=doc_type,
                            title=title,
                            source_url=doc_url,
                        )
                    )
            else:
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"primegov_{mid}",
                        meeting_date=raw_date,
                        doc_type="agenda",
                        title=title,
                        source_url=norm_url,
                    )
                )
        return docs
