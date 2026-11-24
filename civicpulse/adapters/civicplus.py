from __future__ import annotations

import re
from typing import List
from urllib.parse import urljoin

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter


@register_adapter("civicplus")
class CivicPlusAdapter(BaseAdapter):
    is_structured = False

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        try:
            r = requests.get(portal_url, headers=self.headers, timeout=self.timeout, allow_redirects=True)
            has_markers = bool(re.search(r"(agenda|minutes|council|trustees|meeting)", r.text, re.IGNORECASE))
            ok = r.status_code == 200 and has_markers
            msg = "HTML agenda portal reachable" if ok else "Blocked or no agenda markers"
            return ProbeResult(ok, r.status_code, 1 if ok else 0, msg, self.name, portal_url)
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
        seen = set()

        for a in soup.find_all("a", href=True):
            href = urljoin(portal_url, a["href"])
            text = " ".join(a.get_text(" ").split()).strip()
            if not href or href in seen:
                continue
            if not re.search(r"(viewfile|agenda|minute|\.pdf)", href, re.IGNORECASE):
                continue
            seen.add(href)
            doc_type = "minutes" if re.search(r"minute", f"{text} {href}", re.IGNORECASE) else "agenda"
            date_match = re.search(r"(20\d{2}[-/]\d{2}[-/]\d{2}|\d{1,2}/\d{1,2}/20\d{2})", f"{text} {href}")
            mdate = date_match.group(1).replace("/", "-") if date_match else f"{year}-01-01"
            docs.append(
                DocumentRecord(
                    jurisdiction_id=jurisdiction_id,
                    external_id=f"civicplus_{len(docs) + 1}_{href[-24:]}",
                    meeting_date=mdate,
                    doc_type=doc_type,
                    title=text[:120] or f"Public {doc_type.title()}",
                    source_url=href,
                )
            )
            if len(docs) >= limit:
                break
        return docs
