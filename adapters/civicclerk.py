"""
CivicClerk Platform Adapter (Fort Collins Pilot + ~13% of mid-sized US cities).
Targets Agendas and Minutes PDFs/plain-text streams first; transcripts are secondary.
"""
import io
from datetime import datetime, timedelta
from typing import List
import requests
from pypdf import PdfReader
from adapters.base import BaseAdapter, NormalizedDocument


class CivicClerkAdapter(BaseAdapter):
    HEADERS = {
        "User-Agent": "CivicCoreAggregator/1.0 (+https://github.com/your-org/civic-core)"
    }

    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "
".join(pages).strip()

    def fetch_recent_documents(self, days_back: int = 30) -> List[NormalizedDocument]:
        since_iso = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
        url = f"{self.portal_url}/Events"
        params = {
            "$filter": f"startDateTime ge {since_iso}",
            "$orderby": "startDateTime desc",
            "$top": 20,
        }

        resp = requests.get(url, params=params, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        events = resp.json().get("value", [])

        docs: List[NormalizedDocument] = []
        for ev in events:
            event_id = str(ev.get("id", ""))
            event_name = ev.get("eventName", "Council Meeting")
            meeting_date = (ev.get("startDateTime") or "")[:10]

            # Look for published Agenda and Minutes files attached to the event
            for pub_file in ev.get("publishedFiles", []):
                file_type = (pub_file.get("type") or "").lower()
                if "minute" in file_type:
                    doc_type = "minutes"
                elif "agenda" in file_type:
                    doc_type = "agenda"
                else:
                    continue

                file_id = pub_file.get("fileId")
                if not file_id:
                    continue

                file_url = f"{self.portal_url}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)"
                file_resp = requests.get(file_url, headers=self.HEADERS, timeout=30)
                if file_resp.status_code != 200:
                    continue

                raw_text = self._extract_pdf_text(file_resp.content)
                if len(raw_text) < 50:
                    continue  # Skip empty or un-OCR'd image-only stubs for now

                docs.append(
                    NormalizedDocument(
                        external_id=f"{event_id}-{file_id}",
                        meeting_date=meeting_date,
                        doc_type=doc_type,
                        title=f"{event_name} ({doc_type.title()})",
                        source_url=file_url,
                        raw_text=raw_text,
                    )
                )

        return docs
