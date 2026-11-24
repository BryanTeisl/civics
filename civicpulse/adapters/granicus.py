from __future__ import annotations

import re
from typing import List
from urllib.parse import urljoin

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter


@register_adapter("granicus")
class GranicusAdapter(BaseAdapter):
    is_structured = True

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        try:
            r = requests.get(portal_url, headers=self.headers, timeout=self.timeout, allow_redirects=True)
            ok = r.status_code == 200 and bool(re.search(r"(granicus|agenda|minutes|council)", r.text, re.IGNORECASE))
            return ProbeResult(ok, r.status_code, 1 if ok else 0, "Granicus portal reachable" if ok else "Unavailable", self.name, portal_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, portal_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 20
    ) -> List[DocumentRecord]:
        r = requests.get(portal_url, headers=self.headers, timeout=self.timeout, allow_redirects=True)
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        docs: List[DocumentRecord] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(portal_url, a["href"])
            if not re.search(r"(GeneratedAgendaViewer|MinutesViewer|AgendaViewer)", href, re.IGNORECASE):
                continue
            doc_type = "minutes" if "minutes" in href.lower() else "agenda"
            title = " ".join(a.get_text(" ").split()).strip() or f"Granicus {doc_type.title()}"
            docs.append(
                DocumentRecord(
                    jurisdiction_id=jurisdiction_id,
                    external_id=f"granicus_{len(docs) + 1}_{href[-20:]}",
                    meeting_date=f"{year}-01-01",
                    doc_type=doc_type,
                    title=title[:120],
                    source_url=href,
                )
            )
            if len(docs) >= limit:
                break
        return docs
