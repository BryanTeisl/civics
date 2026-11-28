"""eSCRIBE WebPortal Adapter for CivicPulse (civicpulse/adapters/escribe.py).

Supports municipalities and counties hosted on eSCRIBE (`pub-{client}.escribemeetings.com`),
including Aurora City Council (410k pop — #3 city in Colorado) and Boulder County Board of
Commissioners.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .base import BaseAdapter, DocumentRecord, ProbeResult, register_adapter

GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])(?:T|\b)")
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

SKIP_BODY_RE = re.compile(
    r"\b(art\s+in\s+public|youth\s+commission|library\s+board|golf|tree\s+board|"
    r"historic\s+preservation|senior\s+advisory|parks\s+advisory|cultural\s+affairs)\b",
    re.IGNORECASE,
)


class _EscribeAnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: List[Tuple[str, str]] = []
        self._in_a = False
        self._href = ""
        self._buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            self._in_a = True
            self._href = dict(attrs).get("href") or ""
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._in_a:
            txt = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if self._href:
                self.anchors.append((self._href, txt))
            self._in_a = False
            self._href = ""
            self._buf = []


def normalize_escribe_base(portal_url: str) -> str:
    raw = (portal_url or "").strip()
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = f"https://{raw}"
    p = urlparse(raw)
    host = p.netloc.lower()
    if not host:
        return ""
    return f"{p.scheme or 'https'}://{host}"


def _parse_escribe_date(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return ""
    ms_m = re.search(r"/Date\((-?\d+)\)/", s)
    if ms_m:
        try:
            dt = datetime.fromtimestamp(int(ms_m.group(1)) / 1000.0, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    m_iso = ISO_DATE_RE.search(s)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    m_mon = MONTH_NAME_RE.search(s)
    if m_mon:
        mon = MONTH_MAP[m_mon.group(1)[:3].lower()]
        return f"{int(m_mon.group(3)):04d}-{mon:02d}-{int(m_mon.group(2)):02d}"
    return ""


def parse_escribe_calendar_json(
    payload: Any,
    base_url: str,
    jurisdiction_id: str,
    year: Optional[int] = None,
    limit: int = 40,
) -> List[DocumentRecord]:
    """Parses eSCRIBE `GetCalendarMeetings` JSON response into normalized DocumentRecords."""
    if isinstance(payload, dict):
        meetings = payload.get("d") if isinstance(payload.get("d"), list) else payload.get("meetings") or []
    elif isinstance(payload, list):
        meetings = payload
    else:
        meetings = []

    base = normalize_escribe_base(base_url)
    host_slug = re.sub(r"[^a-z0-9]+", "_", urlparse(base).netloc.lower()).strip("_") or "escribe"
    docs: List[DocumentRecord] = []
    seen_ext = set()

    for m in meetings:
        if not isinstance(m, dict):
            continue
        title = re.sub(r"\s+", " ", str(m.get("MeetingName") or m.get("Title") or m.get("MeetingType") or "")).strip()
        if not title or SKIP_BODY_RE.search(title):
            continue

        mdate = _parse_escribe_date(str(m.get("StartDate") or m.get("MeetingDate") or m.get("FormattedStartDate") or ""))
        if year and mdate and not mdate.startswith(str(year)):
            continue

        mid = str(m.get("ID") or m.get("MeetingId") or "").strip()
        links = m.get("MeetingDocumentLink") or m.get("Documents") or []

        has_minutes = False
        has_agenda = False
        if isinstance(links, list):
            for lk in links:
                if not isinstance(lk, dict):
                    continue
                ltype = str(lk.get("Type") or lk.get("Title") or lk.get("DocumentType") or "").lower()
                raw_u = str(lk.get("Url") or lk.get("Link") or "").strip()
                if not raw_u:
                    continue
                full_u = urljoin(base + "/", raw_u)
                is_min = "minute" in ltype or "postminutes" in full_u.lower() or "action" in ltype
                is_ag = "agenda" in ltype or "packet" in ltype
                if not (is_min or is_ag):
                    continue
                dtype = "minutes" if is_min else "agenda"
                if dtype == "minutes":
                    has_minutes = True
                else:
                    has_agenda = True

                # Prefer Meeting.aspx HTML over FileStream.ashx (which eSCRIBE protects behind 403 WAF)
                if mid and "filestream.ashx" in full_u.lower():
                    suffix = "PostMinutes" if dtype == "minutes" else "Agenda"
                    full_u = f"{base}/Meeting.aspx?Id={mid}&Agenda={suffix}&lang=English"

                doc_key = mid or re.sub(r"[^a-z0-9]+", "_", full_u.lower())[-20:]
                ext_id = f"escribe_{host_slug}_{doc_key}_{dtype}"
                if ext_id in seen_ext:
                    continue
                seen_ext.add(ext_id)
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=ext_id,
                        meeting_date=mdate,
                        doc_type=dtype,
                        title=title[:160],
                        source_url=full_u,
                    )
                )

        if mid and not (has_minutes or has_agenda):
            for dtype, suffix in (("minutes", "PostMinutes"), ("agenda", "Agenda")):
                ext_id = f"escribe_{host_slug}_{mid}_{dtype}"
                if ext_id in seen_ext:
                    continue
                seen_ext.add(ext_id)
                docs.append(
                    DocumentRecord(
                        jurisdiction_id=jurisdiction_id,
                        external_id=ext_id,
                        meeting_date=mdate,
                        doc_type=dtype,
                        title=title[:160],
                        source_url=f"{base}/Meeting.aspx?Id={mid}&Agenda={suffix}&lang=English",
                    )
                )

        if len(docs) >= limit:
            break

    docs.sort(key=lambda d: (0 if d.doc_type == "minutes" else 1, d.meeting_date or "0000-00-00"))
    docs.sort(key=lambda d: d.meeting_date or "0000-00-00", reverse=True)
    return docs[:limit]


def parse_escribe_html_fallback(
    html: str,
    base_url: str,
    jurisdiction_id: str,
    year: Optional[int] = None,
    limit: int = 40,
) -> List[DocumentRecord]:
    """Parses eSCRIBE homepage HTML when JSON calendar endpoint is disabled."""
    base = normalize_escribe_base(base_url)
    host_slug = re.sub(r"[^a-z0-9]+", "_", urlparse(base).netloc.lower()).strip("_") or "escribe"
    parser = _EscribeAnchorParser()
    parser.feed(html or "")

    docs: List[DocumentRecord] = []
    seen = set()
    for raw_href, txt in parser.anchors:
        if "meeting.aspx" not in raw_href.lower() and "filestream.ashx" not in raw_href.lower():
            continue
        full_u = urljoin(base + "/", raw_href)
        qs = parse_qs(urlparse(full_u).query)
        mid = (qs.get("Id") or qs.get("id") or [""])[0]
        if not mid:
            gm = GUID_RE.search(full_u)
            mid = gm.group(0) if gm else ""

        ag_mode = (qs.get("Agenda") or qs.get("agenda") or [""])[0].lower()
        is_min = "minute" in ag_mode or "minute" in txt.lower()
        dtype = "minutes" if is_min else "agenda"
        mdate = _parse_escribe_date(txt)
        if year and mdate and not mdate.startswith(str(year)):
            continue

        title = txt if len(txt) >= 6 else f"eSCRIBE {dtype.title()}"
        if SKIP_BODY_RE.search(title):
            continue

        key = mid or full_u
        ext_id = f"escribe_{host_slug}_{key}_{dtype}"
        if ext_id in seen:
            continue
        seen.add(ext_id)
        docs.append(
            DocumentRecord(
                jurisdiction_id=jurisdiction_id,
                external_id=ext_id,
                meeting_date=mdate,
                doc_type=dtype,
                title=title[:160],
                source_url=full_u,
            )
        )
        if len(docs) >= limit:
            break

    docs.sort(key=lambda d: d.meeting_date or "0000-00-00", reverse=True)
    return docs


@register_adapter("escribe")
class EscribeAdapter(BaseAdapter):
    is_structured = False

    def _headers(self, base: str) -> Dict[str, str]:
        h = dict(getattr(self, "headers", {}) or {})
        h.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        h.setdefault("Referer", f"{base}/")
        return h

    def normalize_portal_url(self, portal_url: str) -> str:
        return normalize_escribe_base(portal_url)

    def _query_calendar(self, base: str, year: int) -> List[DocumentRecord]:
        ep = f"{base}/MeetingsCalendarView.aspx/GetCalendarMeetings"
        hdrs = self._headers(base)
        hdrs["Content-Type"] = "application/json; charset=utf-8"
        hdrs["Accept"] = "application/json, text/javascript, */*; q=0.01"
        hdrs["X-Requested-With"] = "XMLHttpRequest"
        body = {"calendarStartDate": f"{year}-01-01", "calendarEndDate": f"{year}-12-31"}
        r = requests.post(ep, json=body, headers=hdrs, timeout=self.timeout)
        if r.status_code == 200:
            return parse_escribe_calendar_json(r.json(), base, "probe", year=year, limit=40)
        return []

    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        base = self.normalize_portal_url(portal_url)
        if not base:
            return ProbeResult(False, "ERR", 0, "Invalid eSCRIBE URL", self.name, portal_url)
        try:
            docs = self._query_calendar(base, year)
            if docs:
                return ProbeResult(True, 200, len(docs), docs[0].title[:70], self.name, base)
            r = requests.get(f"{base}/", headers=self._headers(base), timeout=self.timeout)
            if r.status_code == 200:
                hdocs = parse_escribe_html_fallback(r.text, base, "probe", year=year, limit=10)
                sample = hdocs[0].title if hdocs else "eSCRIBE portal reachable"
                return ProbeResult(True, 200, len(hdocs), sample[:70], self.name, base)
            return ProbeResult(False, r.status_code, 0, f"HTTP {r.status_code}", self.name, base)
        except Exception as exc:
            return ProbeResult(False, "ERR", 0, str(exc)[:70], self.name, base)

    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 40
    ) -> List[DocumentRecord]:
        base = self.normalize_portal_url(portal_url)
        if not base:
            return []
        try:
            docs = self._query_calendar(base, year)
            if docs:
                for d in docs:
                    d.jurisdiction_id = jurisdiction_id
                return docs[:limit]
        except Exception:
            pass

        try:
            r = requests.get(f"{base}/", headers=self._headers(base), timeout=self.timeout)
            if r.status_code in (403, 404, 429):
                print(f"[WATCH][INFO] {jurisdiction_id} eSCRIBE returned HTTP {r.status_code}; skipping cleanly.")
                return []
            r.raise_for_status()
            return parse_escribe_html_fallback(r.text, base, jurisdiction_id, year=year, limit=limit)
        except requests.RequestException as exc:
            print(f"[WATCH][WARN] {jurisdiction_id} eSCRIBE fetch error: {exc}")
            return []
