"""
Adapters for CivicPlus (Agenda Center), PrimeGov, Granicus (ViewPublisher), and BoardDocs.
All four emit NormalizedDocument objects into the SQLite queue for GPU extraction.
"""
import re
from datetime import datetime, timezone
from typing import List
import requests
from adapters.base import BaseAdapter, IngestionResult, NormalizedDocument


class CivicPlusAdapter(BaseAdapter):
    """Scrapes CivicPlus /AgendaCenter HTML pages for recent Agenda & Minutes PDF links."""
    def fetch_recent(self, days_back: int = 30) -> IngestionResult:
        resp = requests.get(self.portal_url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        links = re.findall(r'href="(/AgendaCenter/ViewFile/(Minutes|Agenda)/[^"]+)"', resp.text, re.I)
        docs: List[NormalizedDocument] = []
        base = self.portal_url.split("/AgendaCenter")[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for path, kind in links[:10]:
            full_url = f"{base}{path}"
            docs.append(NormalizedDocument(
                external_id=f"civicplus-{abs(hash(path))}",
                meeting_date=today,
                doc_type="minutes" if kind.lower() == "minutes" else "agenda",
                title=f"CivicPlus {kind} ({path.split('/')[-1]})",
                source_url=full_url,
                raw_text=f"Pending PDF download from {full_url}",
            ))
        return IngestionResult(documents=docs)


class PrimeGovAdapter(BaseAdapter):
    """Polls PrimeGov's public v2/PublicPortal JSON endpoint."""
    def fetch_recent(self, days_back: int = 30) -> IngestionResult:
        url = f"{self.portal_url}/api/v2/PublicPortal/ListArchivedMeetings"
        resp = requests.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        meetings = resp.json() if isinstance(resp.json(), list) else []
        docs: List[NormalizedDocument] = []

        for m in meetings[:10]:
            m_id = str(m.get("id", ""))
            title = m.get("title", "Council Meeting")
            m_date = (m.get("dateTime") or "")[:10]
            for doc in m.get("documentList", []):
                template = (doc.get("templateName") or "").lower()
                if "minute" in template or "action" in template:
                    doc_type = "minutes"
                elif "agenda" in template:
                    doc_type = "agenda"
                else:
                    continue
                doc_url = f"{self.portal_url}/Portal/Meeting?meetingTemplateId={doc.get('id')}"
                docs.append(NormalizedDocument(
                    external_id=f"primegov-{m_id}-{doc.get('id')}",
                    meeting_date=m_date,
                    doc_type=doc_type,
                    title=f"{title} ({doc_type.title()})",
                    source_url=doc_url,
                    raw_text=f"PrimeGov document queued: {doc_url}",
                ))
        return IngestionResult(documents=docs)


class GranicusAdapter(BaseAdapter):
    """Polls legacy Granicus ViewPublisher / MediaManager pages for agenda/minutes links."""
    def fetch_recent(self, days_back: int = 30) -> IngestionResult:
        resp = requests.get(self.portal_url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        links = re.findall(r'href="(https?://[^"]*(?:AgendaViewer|MinutesViewer)[^"]+)"', resp.text, re.I)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        docs = [
            NormalizedDocument(
                external_id=f"granicus-{abs(hash(u))}",
                meeting_date=today,
                doc_type="minutes" if "minutes" in u.lower() else "agenda",
                title=f"Granicus Document ({'Minutes' if 'minutes' in u.lower() else 'Agenda'})",
                source_url=u,
                raw_text=f"Granicus document queued: {u}",
            )
            for u in list(dict.fromkeys(links))[:10]
        ]
        return IngestionResult(documents=docs)


class BoardDocsAdapter(BaseAdapter):
    """Connects to Diligent BoardDocs public meeting list endpoint (SEO/POST)."""
    def fetch_recent(self, days_back: int = 30) -> IngestionResult:
        url = f"{self.portal_url}/BD-GetMeetingsList?open"
        resp = requests.post(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        meetings = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else []
        docs: List[NormalizedDocument] = []
        for m in meetings[:10]:
            if not isinstance(m, dict) or not m.get("Unique"):
                continue
            docs.append(NormalizedDocument(
                external_id=f"boarddocs-{m['Unique']}",
                meeting_date=(m.get("Date") or "")[:10],
                doc_type="agenda",
                title=m.get("Name", "Board Meeting"),
                source_url=f"{self.portal_url}/Public",
                raw_text=f"BoardDocs meeting ID {m['Unique']} queued.",
            ))
        return IngestionResult(documents=docs)