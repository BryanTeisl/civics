"""Polite HTML link-discovery adapter for county & school board .gov/.org portals.

Upgraded for v2 Clean Baseline:
  - Uses Python stdlib html.parser (zero extra runtime dependencies)
  - Supports bounded 1-hop same-domain sub-page discovery (max 3 agenda/minutes hub
    links) when the landing portal_url is a board overview page (e.g., Boulder County
    BOCC or Boulder Valley School District).
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter

DOC_LINK_RE = re.compile(
    r"\b(agenda|minutes|packet|vote\s*tracking|action\s+summary|regular\s+meeting|board\s+meeting|hearing|work\s+session)\b",
    re.IGNORECASE,
)
SUBPAGE_HUB_RE = re.compile(
    r"\b(agendas?|minutes|meetings?|public\s+hearings?|hearings?|board\s+docs|calendar|records|archive)\b",
    re.IGNORECASE,
)
MINUTES_HINT_RE = re.compile(
    r"\b(minute|minutes|vote\s*tracking|action\s+summary|approved\s+summary)\b",
    re.IGNORECASE,
)
EXCLUDE_LINK_RE = re.compile(
    r"\b(calendar\s+subscribe|rss|privacy|accessibility|login|sign\s+in|facebook|twitter|youtube|instagram|mailto:|tel:|javascript:)\b",
    re.IGNORECASE,
)

ISO_DATE_RE = re.compile(r"\b(20\d{2})[-_/](0?[1-9]|1[0-2])[-_/](0?[1-9]|[12]\d|3[01])\b")
US_DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])[-/](20\d{2})\b")
COMPACT_DATE_RE = re.compile(r"\b(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(20\d{2})\b")
MONTH_NAME_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[.,]?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
    re.IGNORECASE,
)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class _LinkContextParser(HTMLParser):
    BLOCK_TAGS = {"li", "tr", "div", "p", "article", "section", "td"}

    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str, str]] = []
        self._in_a = False
        self._cur_href = ""
        self._cur_a_text: List[str] = []
        self._block_text: List[str] = []
        self._pending_indices: List[int] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t in self.BLOCK_TAGS:
            self._flush_block()
        elif t == "a":
            href = (dict(attrs).get("href") or "").strip()
            if href:
                self._in_a = True
                self._cur_href = href
                self._cur_a_text = []

    def handle_data(self, data: str) -> None:
        txt = data.strip()
        if not txt:
            return
        self._block_text.append(txt)
        if self._in_a:
            self._cur_a_text.append(txt)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "a" and self._in_a:
            a_text = " ".join(self._cur_a_text).strip()
            idx = len(self.links)
            self.links.append((self._cur_href, a_text, ""))
            self._pending_indices.append(idx)
            self._in_a = False
            self._cur_href = ""
            self._cur_a_text = []
        elif t in self.BLOCK_TAGS:
            self._flush_block()

    def _flush_block(self) -> None:
        if self._pending_indices:
            ctx = " ".join(self._block_text).strip()[:220]
            for idx in self._pending_indices:
                href, a_text, _ = self.links[idx]
                self.links[idx] = (href, a_text, ctx)
            self._pending_indices = []
        self._block_text = []

    def close(self) -> None:
        super().close()
        self._flush_block()


def extract_date_from_text(text: str) -> str:
    s = text or ""
    m_iso = ISO_DATE_RE.search(s)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    m_us = US_DATE_RE.search(s)
    if m_us:
        return f"{int(m_us.group(3)):04d}-{int(m_us.group(1)):02d}-{int(m_us.group(2)):02d}"
    m_mon = MONTH_NAME_RE.search(s)
    if m_mon:
        mon_num = MONTH_MAP[m_mon.group(1)[:3].lower()]
        return f"{int(m_mon.group(3)):04d}-{mon_num:02d}-{int(m_mon.group(2)):02d}"
    m_comp = COMPACT_DATE_RE.search(s)
    if m_comp:
        return f"{int(m_comp.group(3)):04d}-{int(m_comp.group(1)):02d}-{int(m_comp.group(2)):02d}"
    return ""


def discover_meeting_subpages(html: str, base_url: str, max_subpages: int = 3) -> List[str]:
    """Finds up to N same-domain sub-pages likely to list agendas/minutes PDFs."""
    parser = _LinkContextParser()
    parser.feed(html or "")
    parser.close()

    base_parsed = urlparse(base_url)
    base_host = base_parsed.netloc.lower()
    seen = {base_url.rstrip("/")}
    candidates: List[Tuple[int, str]] = []

    for raw_href, link_text, _ in parser.links:
        if not raw_href or raw_href.startswith("#") or EXCLUDE_LINK_RE.search(raw_href):
            continue
        full_url = urljoin(base_url, raw_href).split("#")[0]
        p = urlparse(full_url)
        if p.scheme not in ("http", "https") or p.netloc.lower() != base_host:
            continue
        if full_url.lower().endswith(".pdf") or "/documentcenter/view/" in full_url.lower():
            continue
        norm = full_url.rstrip("/")
        if norm in seen:
            continue
        blob = f"{link_text} {p.path}"
        if SUBPAGE_HUB_RE.search(blob):
            seen.add(norm)
            # Prioritize links that explicitly mention agenda/minutes over generic meetings
            score = 2 if re.search(r"agenda|minute|hearing", blob, re.IGNORECASE) else 1
            candidates.append((score, full_url))

    candidates.sort(key=lambda x: -x[0])
    return [u for _, u in candidates[:max_subpages]]


def parse_gov_page_links(
    html: str,
    base_url: str,
    jurisdiction_id: str,
    year: Optional[int] = None,
    limit: int = 25,
) -> List[DocumentRecord]:
    """Parses direct agenda/minutes document links from an HTML page."""
    parser = _LinkContextParser()
    parser.feed(html or "")
    parser.close()

    host_slug = re.sub(r"[^a-z0-9]+", "_", urlparse(base_url).netloc.lower()).strip("_") or "gov"
    seen_urls = set()
    docs: List[DocumentRecord] = []

    for raw_href, link_text, parent_text in parser.links:
        if not raw_href or raw_href.startswith("#") or EXCLUDE_LINK_RE.search(raw_href):
            continue

        full_url = urljoin(base_url, raw_href)
        if full_url in seen_urls:
            continue

        combined = f"{link_text} {parent_text} {raw_href}"
        is_pdf = ".pdf" in full_url.lower() or "/documentcenter/view/" in full_url.lower()
        mdate = extract_date_from_text(f"{link_text} {raw_href}") or extract_date_from_text(parent_text)

        # Require either a document file (PDF/DocumentCenter) OR a dated agenda/minutes link
        if not (is_pdf or (mdate and DOC_LINK_RE.search(combined))):
            continue

        if year and mdate and not mdate.startswith(str(year)):
            continue

        seen_urls.add(full_url)
        is_minutes = bool(MINUTES_HINT_RE.search(f"{link_text} {raw_href}"))
        doc_type = "minutes" if is_minutes else "agenda"

        clean_title = link_text if len(link_text) >= 6 else parent_text[:100]
        clean_title = re.sub(r"\s+", " ", clean_title).strip() or f"Official {doc_type.title()}"

        url_hash = hashlib.sha1(full_url.encode("utf-8")).hexdigest()[:12]
        docs.append(
            DocumentRecord(
                jurisdiction_id=jurisdiction_id,
                external_id=f"govweb_{host_slug}_{url_hash}_{doc_type}",
                meeting_date=mdate,
                doc_type=doc_type,
                title=clean_title[:160],
                source_url=full_url,
            )
        )
        if len(docs) >= limit:
            break

    docs.sort(key=lambda d: d.meeting_date or "0000-00-00", reverse=True)
    return docs


@register_adapter("gov_web")
class GovWebAdapter(BaseAdapter):
    is_structured = False

    def _browser_headers(self) -> Dict[str, str]:
        merged = dict(getattr(self, "headers", {}) or {})
        merged.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        merged.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        return merged

    def normalize_portal_url(self, portal_url: str) -> str:
        return (portal_url or "").strip()

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        url = self.normalize_portal_url(portal_url)
        try:
            r = requests.get(url, headers=self._browser_headers(), timeout=self.timeout)
            if r.status_code == 200:
                parsed = parse_gov_page_links(r.text, url, "probe", year=year, limit=5)
                sample = parsed[0].title if parsed else "HTML portal reachable"
                return ProbeResult(True, 200, len(parsed), sample[:70], self.name, url)
            return ProbeResult(False, r.status_code, 0, f"HTTP {r.status_code}", self.name, url)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, url)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        url = self.normalize_portal_url(portal_url)
        if not url:
            return []
        headers = self._browser_headers()
        try:
            r = requests.get(url, headers=headers, timeout=self.timeout)
            if r.status_code in (403, 404, 429):
                print(f"[WATCH][INFO] {jurisdiction_id} returned HTTP {r.status_code} on {url}; skipping cleanly.")
                return []
            r.raise_for_status()

            docs = parse_gov_page_links(r.text, url, jurisdiction_id, year=year, limit=limit)

            # Bounded 1-hop follow when landing page is an overview page with few direct PDFs
            if len(docs) < 3:
                seen_urls = {d.source_url for d in docs}
                for sub_url in discover_meeting_subpages(r.text, url, max_subpages=3):
                    try:
                        sr = requests.get(sub_url, headers=headers, timeout=self.timeout)
                        if not sr.ok:
                            continue
                        sub_docs = parse_gov_page_links(
                            sr.text, sub_url, jurisdiction_id, year=year, limit=limit
                        )
                        for sd in sub_docs:
                            if sd.source_url not in seen_urls:
                                seen_urls.add(sd.source_url)
                                docs.append(sd)
                                if len(docs) >= limit:
                                    break
                    except requests.RequestException:
                        continue
                    if len(docs) >= limit:
                        break

            docs.sort(key=lambda d: d.meeting_date or "0000-00-00", reverse=True)
            return docs[:limit]
        except requests.RequestException as exc:
            print(f"[WATCH][WARN] {jurisdiction_id} web fetch error on {url}: {exc}")
            return []
