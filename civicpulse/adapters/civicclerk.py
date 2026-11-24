from __future__ import annotations

from typing import List
from urllib.parse import urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter


def _extract_slug(portal_url: str) -> str:
    host = urlparse(portal_url).netloc.lower()
    if "civicclerk.com" in host:
        return host.split(".")[0]
    return host.split(".")[0]


@register_adapter("civicclerk")
class CivicClerkAdapter(BaseAdapter):
    is_structured = True

    def normalize_portal_url(self, portal_url: str) -> str:
        slug = _extract_slug(portal_url)
        return f"https://{slug}.portal.civicclerk.com/" if slug else portal_url

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        slug = _extract_slug(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        api_url = f"https://{slug}.api.civicclerk.com/v1/Events?$top=5&$orderby=startDateTime%20desc"
        try:
            r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                vals = r.json().get("value", [])
                sample = (vals[0].get("eventName") or "CivicClerk Event") if vals else ""
                return ProbeResult(True, 200, len(vals), sample[:70], self.name, norm_url)
            return ProbeResult(False, r.status_code, 0, "HTTP error", self.name, norm_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, norm_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        slug = _extract_slug(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        api_url = f"https://{slug}.api.civicclerk.com/v1/Events?$top={limit}&$orderby=startDateTime%20desc"
        r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        events = r.json().get("value", [])

        docs: List[DocumentRecord] = []
        for ev in events:
            eid = str(ev.get("id") or "")
            title = (ev.get("eventName") or "Council Meeting").strip()
            mdate = str(ev.get("startDateTime") or "")[:10]
            # Always store the human portal URL (never raw .api.civicclerk.com stream URLs)
            human_event_url = f"https://{slug}.portal.civicclerk.com/event/{eid}/files" if eid else norm_url
            docs.append(
                DocumentRecord(
                    jurisdiction_id=jurisdiction_id,
                    external_id=f"civicclerk_{eid}",
                    meeting_date=mdate,
                    doc_type="agenda",
                    title=title,
                    source_url=human_event_url,
                )
            )
        return docs
