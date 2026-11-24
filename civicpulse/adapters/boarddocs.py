from __future__ import annotations

import re
from typing import List

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter


@register_adapter("boarddocs")
class BoardDocsAdapter(BaseAdapter):
    is_structured = True

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        try:
            r = requests.get(portal_url, headers=self.headers, timeout=self.timeout, allow_redirects=True)
            ok = r.status_code == 200 and bool(re.search(r"(boarddocs|meeting|agenda)", r.text, re.IGNORECASE))
            return ProbeResult(ok, r.status_code, 1 if ok else 0, "BoardDocs portal reachable" if ok else "Unavailable", self.name, portal_url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, portal_url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 15
    ) -> List[DocumentRecord]:
        return [
            DocumentRecord(
                jurisdiction_id=jurisdiction_id,
                external_id=f"boarddocs_portal_{year}",
                meeting_date=f"{year}-01-01",
                doc_type="agenda",
                title="BoardDocs Public Meeting Archive",
                source_url=portal_url,
            )
        ]
