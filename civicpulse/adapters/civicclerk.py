from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, is_elected_council_meeting, register_adapter

MINUTES_HINT_RE = re.compile(
    r"\b(minute|minutes|action\s+agenda|action\s+summary|summary\s+agenda|summary)\b",
    re.IGNORECASE,
)
PACKET_HINT_RE = re.compile(r"\b(packet|full\s+agenda\s+packet)\b", re.IGNORECASE)
CANCELLED_RE = re.compile(r"\b(cancel+ed)\b", re.IGNORECASE)


def _extract_tenant(portal_url: str) -> str:
    parsed = urlparse((portal_url or "").strip())
    host = parsed.netloc.lower()
    if ".civicclerk.com" in host:
        return host.split(".")[0]
    return host.split(".")[0]


@register_adapter("civicclerk")
class CivicClerkAdapter(BaseAdapter):
    is_structured = True

    def normalize_portal_url(self, portal_url: str) -> str:
        tenant = _extract_tenant(portal_url)
        return f"https://{tenant}.portal.civicclerk.com/" if tenant else portal_url

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        tenant = _extract_tenant(portal_url)
        norm_url = self.normalize_portal_url(portal_url)
        api_url = f"https://{tenant}.api.civicclerk.com/v1/Events?$top=5&$orderby=startDateTime%20desc"
        try:
            r = requests.get(api_url, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200 and isinstance(r.json(), dict) and "value" in r.json():
                vals = r.json().get("value") or []
                sample = (vals[0].get("eventName") or "CivicClerk Event") if vals else ""
                return ProbeResult(True, 200, len(vals), sample[:70], self.name, norm_url)
            return ProbeResult(False, r.status_code, 0, "HTTP error", self.name, norm_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, norm_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        tenant = _extract_tenant(portal_url)
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59Z")
        api_url = f"https://{tenant}.api.civicclerk.com/v1/Events"

        # 1. Server-side council filter so advisory boards don't crowd out past council minutes
        council_filter = (
            f"startDateTime le {today_iso} and ("
            "contains(eventName, 'Council') or "
            "contains(eventName, 'Town Board') or "
            "contains(eventName, 'Trustees') or "
            "contains(eventName, 'Commissioners'))"
        )
        events: List[Dict[str, Any]] = []
        r = requests.get(
            api_url,
            params={"$top": max(limit * 2, 50), "$orderby": "startDateTime desc", "$filter": council_filter},
            headers=self.headers,
            timeout=self.timeout,
        )
        if r.ok:
            events = (r.json() or {}).get("value") or []

        # 2. Fallback to unfiltered past events if tenant rejects contains() or returns empty
        if not events:
            fetch_top = max(limit * 4, 100)
            r = requests.get(
                api_url,
                params={"$top": fetch_top, "$orderby": "startDateTime desc", "$filter": f"startDateTime le {today_iso}"},
                headers=self.headers,
                timeout=self.timeout,
            )
            if not r.ok:
                r = requests.get(
                    api_url,
                    params={"$top": fetch_top, "$orderby": "startDateTime desc"},
                    headers=self.headers,
                    timeout=self.timeout,
                )
            r.raise_for_status()
            events = (r.json() or {}).get("value") or []

        docs: List[DocumentRecord] = []
        matched_meetings = 0

        for ev in events:
            if matched_meetings >= limit:
                break
            title = (ev.get("eventName") or "").strip()
            if CANCELLED_RE.search(title):
                continue
            category = (ev.get("categoryName") or "").strip()
            combined_name = f"{title} {category}".strip()
            if not is_elected_council_meeting(combined_name):
                continue

            files = ev.get("publishedFiles") or []
            if not files:
                continue

            matched_meetings += 1
            eid = str(ev.get("id") or "")
            mdate = str(ev.get("startDateTime") or "")[:10]

            has_minutes = False
            has_agenda = False
            for f in files:
                fname = (f.get("name") or "").strip()
                ftype = (f.get("type") or "").strip()
                label = f"{ftype} {fname}".strip()
                if PACKET_HINT_RE.search(label):
                    continue
                if MINUTES_HINT_RE.search(label):
                    has_minutes = True
                else:
                    has_agenda = True

            if has_minutes:
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"civicclerk_{tenant}_{eid}_minutes",
                        meeting_date=mdate,
                        doc_type="minutes",
                        title=f"{title} (Minutes)",
                        source_url=f"https://{tenant}.portal.civicclerk.com/event/{eid}/files#minutes",
                    )
                )
            if has_agenda or not has_minutes:
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=f"civicclerk_{tenant}_{eid}_agenda",
                        meeting_date=mdate,
                        doc_type="agenda",
                        title=f"{title} (Agenda)",
                        source_url=f"https://{tenant}.portal.civicclerk.com/event/{eid}/files",
                    )
                )

        return docs
