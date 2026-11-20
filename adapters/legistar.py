"""
Granicus Legistar OData REST API Adapter (~20% of US cities, ~70% of major cities).
Because Legistar exposes structured JSON for events and votes, this adapter
can ingest agendas/minutes directly with minimal GPU overhead.
"""
from datetime import datetime, timedelta
from typing import List
import requests
from adapters.base import BaseAdapter, NormalizedDocument


class LegistarAdapter(BaseAdapter):
    """
    portal_url example: https://webapi.legistar.com/v1/denver
    """
    HEADERS = {
        "User-Agent": "CivicCoreAggregator/1.0 (+https://github.com/your-org/civic-core)"
    }

    def fetch_recent_documents(self, days_back: int = 30) -> List[NormalizedDocument]:
        since_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        url = f"{self.portal_url}/events"
        params = {
            "$filter": f"EventDate ge datetime'{since_date}'",
            "$orderby": "EventDate desc",
            "$top": 20,
        }
        resp = requests.get(url, params=params, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        events = resp.json()

        docs: List[NormalizedDocument] = []
        for ev in events:
            event_id = str(ev.get("EventId", ""))
            body = ev.get("EventBodyName", "City Council")
            meeting_date = (ev.get("EventDate") or "")[:10]
            minutes_url = ev.get("EventMinutesFile")
            agenda_url = ev.get("EventAgendaFile")

            # Store structured summary text or link for downstream processing
            if minutes_url:
                docs.append(
                    NormalizedDocument(
                        external_id=f"legistar-{event_id}-minutes",
                        meeting_date=meeting_date,
                        doc_type="minutes",
                        title=f"{body} Minutes ({meeting_date})",
                        source_url=minutes_url,
                        raw_text=f"Legistar EventId={event_id}. Fetch structured votes via {self.portal_url}/events/{event_id}/eventitems",
                    )
                )
            elif agenda_url:
                docs.append(
                    NormalizedDocument(
                        external_id=f"legistar-{event_id}-agenda",
                        meeting_date=meeting_date,
                        doc_type="agenda",
                        title=f"{body} Agenda ({meeting_date})",
                        source_url=agenda_url,
                        raw_text=f"Legistar EventId={event_id}. Agenda posted at {agenda_url}",
                    )
                )
        return docs
