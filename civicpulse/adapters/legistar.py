from __future__ import annotations

from typing import List
from urllib.parse import urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, is_elected_council_meeting, register_adapter


def _extract_client(portal_url: str) -> str:
    parsed = urlparse((portal_url or "").strip())
    host = parsed.netloc.lower()
    if host == "webapi.legistar.com":
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "v1":
            return parts[1].lower()
        if parts:
            return parts[0].lower()
    if ".legistar.com" in host:
        return host.split(".legistar.com")[0]
    return host.split(".")[0]


@register_adapter("legistar")
class LegistarAdapter(BaseAdapter):
    is_structured = True

    def normalize_portal_url(self, portal_url: str) -> str:
        client = _extract_client(portal_url)
        return f"https://{client}.legistar.com/" if client else portal_url

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        client = _extract_client(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        api_url = f"https://webapi.legistar.com/v1/{client}/events?$top=5&$orderby=EventDate%20desc"
        try:
            r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200 and isinstance(r.json(), list):
                data = r.json()
                sample = (data[0].get("EventBodyName") or "Legistar Event") if data else ""
                return ProbeResult(True, 200, len(data), sample[:70], self.name, norm_url)
            return ProbeResult(False, r.status_code, 0, "HTTP error", self.name, norm_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, norm_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        client = _extract_client(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        fetch_top = max(limit * 4, 100)
        api_url = f"https://webapi.legistar.com/v1/{client}/events?$top={fetch_top}&$orderby=EventDate%20desc"
        r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        events = r.json() if isinstance(r.json(), list) else []

        docs: List[DocumentRecord] = []
        matched_meetings = 0
        for ev in events:
            if matched_meetings >= limit:
                break
            body = (ev.get("EventBodyName") or "").strip()
            if not is_elected_council_meeting(body):
                continue

            matched_meetings += 1
            eid = str(ev.get("EventId") or "")
            mdate = str(ev.get("EventDate") or "")[:10]
            minutes_url = ev.get("EventMinutesFile")
            agenda_url = ev.get("EventAgendaFile")
            if minutes_url:
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"legistar_{eid}_minutes",
                        meeting_date=mdate,
                        doc_type="minutes",
                        title=f"{body} Minutes",
                        source_url=minutes_url,
                    )
                )
            if agenda_url:
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"legistar_{eid}_agenda",
                        meeting_date=mdate,
                        doc_type="agenda",
                        title=f"{body} Agenda",
                        source_url=agenda_url,
                    )
                )
            if not minutes_url and not agenda_url:
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"legistar_{eid}_event",
                        meeting_date=mdate,
                        doc_type="agenda",
                        title=body,
                        source_url=ev.get("EventInSiteURL") or norm_url,
                    )
                )
        return docs
