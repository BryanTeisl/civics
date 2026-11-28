"""Hands-Off Autonomous Jurisdiction Request Intake & Provisioning Agent.

Designed to run automatically inside `scripts/run_daily.ps1` with $0/month cost:
  1. Intake (Zero-Backend):
     - Polls public GitHub Issues labeled `jurisdiction-request` (via unauthenticated
       GitHub REST API for `BryanTeisl/civics`, or configurable `--github-repo`)
     - Also reads local `onboarding_requests` SQLite queue (`status = 'pending'`)
       so CLI / CSV / local requests use the exact same pipeline.
  2. Autonomous Scout & Multi-Platform Probe:
     - Resolves canonical `ocd_division_id`, level, and coordinates from `core_civic.db`
       or `public/geo/boundaries.geojson`.
     - Probes Legistar (with `$orderby` fallback), PrimeGov, CivicClerk, BoardDocs,
       Granicus, and official `.gov`/`.org` meeting pages (`gov_web`).
     - Detects WAF / Cloudflare / Akamai HTTP 403 blocks immediately and parks the
       jurisdiction cleanly as `unclaimed` (`status = 'blocked_waf'`) so daily
       runs never stall on blocked sites.
  3. Autonomous Provisioning (for verified open portals):
     - Updates `jurisdictions` to `status = 'active'` with discovered `adapter_type`,
       `portal_url`, `roster_url`, and `council_email`.
     - Triggers initial roster sync (`roster_sync.py`) and initial document discovery
       (`watch`) so the daily `work` step begins extracting minutes immediately.
  4. Auditability & Rate Guardrails:
     - Caps new onboardings per daily run (`--max-per-run 2`) so CPU/network stay bounded.
     - Exports `public/data/onboarding_status.json` showing recently onboarded and
       queued communities.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

DEFAULT_GITHUB_REPO = "BryanTeisl/civics"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CivicPulseAutonomousAgent/1.0; +https://civics-d03.pages.dev)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}

OCD_RE = re.compile(r"ocd-division/country:us/state:[a-z]{2}/[a-z_]+:[a-z0-9_]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(?:gov|org|us)\b", re.IGNORECASE)
GENERIC_EMAIL_PREFIXES = ("webmaster@", "noreply@", "no-reply@", "donotreply@", "support@", "privacy@", "accessibility@")


class _AnchorExtractor(HTMLParser):
    """Lightweight stdlib HTML anchor extractor (zero external parser deps)."""

    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str]] = []
        self._in_a = False
        self._href = ""
        self._text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            self._in_a = True
            self._href = dict(attrs).get("href") or ""
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._in_a:
            txt = re.sub(r"\s+", " ", "".join(self._text_parts)).strip()
            if self._href:
                self.links.append((self._href, txt))
            self._in_a = False
            self._href = ""
            self._text_parts = []


def _extract_links(html_text: str) -> List[Tuple[str, str]]:
    parser = _AnchorExtractor()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass
    return parser.links


def ensure_onboarding_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS onboarding_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT UNIQUE,
            source_type TEXT DEFAULT 'github_issue',
            raw_title TEXT,
            jurisdiction_name TEXT,
            ocd_division_id TEXT,
            state TEXT DEFAULT 'CO',
            level TEXT DEFAULT 'city',
            submitted_portal_url TEXT,
            status TEXT DEFAULT 'pending',
            detected_adapter TEXT,
            resolved_portal_url TEXT,
            resolved_roster_url TEXT,
            council_email TEXT,
            notes TEXT,
            created_at TEXT,
            processed_at TEXT
        );
        """
    )
    jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}
    if "roster_url" not in jur_cols:
        conn.execute("ALTER TABLE jurisdictions ADD COLUMN roster_url TEXT DEFAULT ''")
    if "council_email" not in jur_cols:
        conn.execute("ALTER TABLE jurisdictions ADD COLUMN council_email TEXT DEFAULT ''")
    conn.commit()


def slugify_place(name: str) -> str:
    cleaned = re.sub(
        r"\b(city|town|village|borough|county|board|council|trustees|of|the|municipality|school|district|public|schools|re-\d+|r-\d+|\d+j?)\b",
        "",
        (name or "").lower(),
    )
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned or re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def build_ocd_id(place_name: str, state_abbr: str = "CO", level: str = "city") -> str:
    st = (state_abbr or "CO").strip().lower()
    slug = slugify_place(place_name)
    if level == "county":
        return f"ocd-division/country:us/state:{st}/county:{slug}"
    if level == "school_district":
        return f"ocd-division/country:us/state:{st}/school_district:{slug}"
    return f"ocd-division/country:us/state:{st}/place:{slug}"


def infer_level(name: str, explicit_level: Optional[str] = None) -> str:
    if explicit_level and explicit_level.lower() in ("city", "county", "school_district"):
        return explicit_level.lower()
    low = (name or "").lower()
    if "school" in low or "board of education" in low:
        return "school_district"
    if "county" in low or "commissioner" in low:
        return "county"
    return "city"


def candidate_slugs(place_name: str, state_abbr: str = "CO") -> List[str]:
    base = re.sub(
        r"\b(city|town|county|board|council|trustees|of|the|school|district|public|schools)\b",
        "",
        (place_name or "").lower(),
    )
    compact = re.sub(r"[^a-z0-9]", "", base)
    st = (state_abbr or "CO").strip().lower()
    if not compact:
        return []
    return list(
        dict.fromkeys(
            [
                compact,
                f"{compact}{st}",
                f"cityof{compact}",
                f"townof{compact}",
                f"{compact}county" if "county" in (place_name or "").lower() else f"{compact}{st}",
            ]
        )
    )


def parse_github_issue_request(issue: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts structured jurisdiction metadata from a GitHub issue title + body."""
    num = issue.get("number")
    title = (issue.get("title") or "").strip()
    body = (issue.get("body") or "").strip()
    combined = f"{title}\n{body}"

    ocd_match = OCD_RE.search(combined)
    ocd_id = ocd_match.group(0).lower() if ocd_match else ""

    name_m = re.search(r"(?:jurisdiction|city|county|district|name)\s*:\s*([^\r\n]+)", body, re.IGNORECASE)
    url_m = re.search(r"(?:portal|meeting|website)?\s*url\s*:\s*(https?://[^\s\r\n]+)", body, re.IGNORECASE)
    if not url_m:
        url_m = re.search(r"(https?://[^\s\r\n)]+)", body)

    cleaned_title = re.sub(
        r"^\[?(?:request|coverage|track|onboard|jurisdiction)\]?\s*:?\s*",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    jur_name = (name_m.group(1).strip() if name_m else cleaned_title) or ocd_id
    if not jur_name and not ocd_id:
        return None

    level = infer_level(f"{jur_name} {ocd_id}")
    if not ocd_id:
        ocd_id = build_ocd_id(jur_name, "CO", level)

    return {
        "source_key": f"gh_issue_{num}",
        "source_type": "github_issue",
        "raw_title": title[:200],
        "jurisdiction_name": jur_name[:160],
        "ocd_division_id": ocd_id,
        "state": "CO",
        "level": level,
        "submitted_portal_url": (url_m.group(1).strip() if url_m else "")[:300],
    }


def sync_github_issue_requests(
    conn: sqlite3.Connection,
    github_repo: str = DEFAULT_GITHUB_REPO,
    label: str = "jurisdiction-request",
    timeout: int = 15,
) -> int:
    """Polls public GitHub Issues with label `jurisdiction-request` into `onboarding_requests`."""
    if not github_repo:
        return 0
    url = f"https://api.github.com/repos/{github_repo}/issues"
    try:
        r = requests.get(
            url,
            params={"state": "open", "labels": label, "per_page": 30},
            headers=HEADERS,
            timeout=timeout,
        )
        if r.status_code != 200 or not isinstance(r.json(), list):
            return 0
    except Exception:
        return 0

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    inserted = 0
    for issue in r.json():
        if "pull_request" in issue:
            continue
        parsed = parse_github_issue_request(issue)
        if not parsed:
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO onboarding_requests
            (source_key, source_type, raw_title, jurisdiction_name, ocd_division_id,
             state, level, submitted_portal_url, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                parsed["source_key"],
                parsed["source_type"],
                parsed["raw_title"],
                parsed["jurisdiction_name"],
                parsed["ocd_division_id"],
                parsed["state"],
                parsed["level"],
                parsed["submitted_portal_url"],
                now_iso,
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    conn.commit()
    return inserted


def resolve_from_local_db_or_geo(
    conn: sqlite3.Connection,
    ocd_id: str,
    jur_name: str,
    geo_path: Path = Path("public/geo/boundaries.geojson"),
) -> Dict[str, Any]:
    """Looks up existing unclaimed record in SQLite or `boundaries.geojson` so TIGERweb
    coordinates and canonical names are preserved."""
    row = conn.execute(
        "SELECT ocd_division_id, name, level, lat, lng, portal_url, status FROM jurisdictions WHERE ocd_division_id = ?",
        (ocd_id,),
    ).fetchone()
    if row:
        return {
            "ocd_division_id": row[0],
            "name": row[1] or jur_name,
            "level": row[2] or infer_level(jur_name),
            "lat": float(row[3] or 0.0),
            "lng": float(row[4] or 0.0),
            "portal_url": row[5] or "",
            "existing_status": row[6] or "unclaimed",
        }

    if geo_path.exists():
        try:
            geo = json.loads(geo_path.read_text(encoding="utf-8"))
            for feat in geo.get("features", []):
                p = feat.get("properties") or {}
                if (p.get("ocd_division_id") or "").lower() == ocd_id.lower():
                    return {
                        "ocd_division_id": p["ocd_division_id"],
                        "name": p.get("name") or jur_name,
                        "level": p.get("level") or infer_level(jur_name),
                        "lat": float(p.get("latitude") or 0.0),
                        "lng": float(p.get("longitude") or 0.0),
                        "portal_url": p.get("portal_url") or "",
                        "existing_status": "unclaimed",
                    }
        except Exception:
            pass

    return {
        "ocd_division_id": ocd_id,
        "name": jur_name,
        "level": infer_level(jur_name),
        "lat": 0.0,
        "lng": 0.0,
        "portal_url": "",
        "existing_status": "new",
    }


def probe_portal_candidates(
    jur_name: str,
    state_abbr: str = "CO",
    submitted_url: str = "",
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """Probes structured APIs & official meeting URLs, detecting WAF 403 blocks cleanly."""
    yr = year or datetime.now(timezone.utc).year
    waf_blocked = False

    def _inspect_url(url: str) -> Optional[Dict[str, Any]]:
        nonlocal waf_blocked
        u = (url or "").strip()
        if not u:
            return None
        low = u.lower()
        if ".legistar.com" in low:
            client = low.split("//", 1)[-1].split(".legistar.com")[0]
            for ep in (
                f"https://webapi.legistar.com/v1/{client}/events?$top=5&$orderby=EventDate%20desc",
                f"https://webapi.legistar.com/v1/{client}/events?$top=5",
            ):
                try:
                    r = requests.get(ep, headers=HEADERS, timeout=10)
                    if r.status_code == 200 and isinstance(r.json(), list) and r.json():
                        return {"status": "supported", "adapter_type": "legistar", "portal_url": f"https://{client}.legistar.com/", "sample_count": len(r.json())}
                except Exception:
                    pass
        if ".primegov.com" in low:
            sub = low.split("//", 1)[-1].split(".primegov.com")[0]
            try:
                r = requests.get(f"https://{sub}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={yr}", headers=HEADERS, timeout=10)
                if r.status_code == 200 and isinstance(r.json(), list) and r.json():
                    return {"status": "supported", "adapter_type": "primegov", "portal_url": f"https://{sub}.primegov.com/public/portal", "sample_count": len(r.json())}
            except Exception:
                pass
        if "civicclerk.com" in low:
            slug = low.split("//", 1)[-1].split(".")[0]
            try:
                r = requests.get(f"https://{slug}.api.civicclerk.com/v1/Events?$top=5&$orderby=startDateTime%20desc", headers=HEADERS, timeout=10)
                if r.status_code == 200 and r.json().get("value"):
                    return {"status": "supported", "adapter_type": "civicclerk", "portal_url": f"https://{slug}.portal.civicclerk.com/", "sample_count": len(r.json()["value"])}
            except Exception:
                pass
        if "escribemeetings.com" in low:
            parsed_u = urlparse(u)
            base_u = f"{parsed_u.scheme or 'https'}://{parsed_u.netloc}"
            try:
                r = requests.post(
                    f"{base_u}/MeetingsCalendarView.aspx/GetCalendarMeetings",
                    json={"calendarStartDate": f"{yr}-01-01", "calendarEndDate": f"{yr}-12-31"},
                    headers={**HEADERS, "Content-Type": "application/json; charset=utf-8"},
                    timeout=10,
                )
                if r.status_code == 200 and isinstance(r.json().get("d"), list):
                    return {"status": "supported", "adapter_type": "escribe", "portal_url": base_u, "sample_count": len(r.json()["d"])}
            except Exception:
                pass
            try:
                r = requests.get(base_u, headers=HEADERS, timeout=10)
                if r.status_code == 200:
                    return {"status": "supported", "adapter_type": "escribe", "portal_url": base_u, "sample_count": 1}
            except Exception:
                pass

        if "boarddocs.com" in low:
            return {"status": "supported", "adapter_type": "boarddocs", "portal_url": u, "sample_count": 1}

        try:
            r = requests.get(u, headers=HEADERS, timeout=12)
            if r.status_code in (403, 429):
                waf_blocked = True
                return None
            if r.status_code == 200:
                links = _extract_links(r.text)
                for raw_href, _ in links:
                    href = urljoin(u, raw_href)
                    hlow = href.lower()
                    if any(k in hlow for k in (".legistar.com", ".primegov.com", "civicclerk.com", "boarddocs.com", "escribemeetings.com")):
                        sub_hit = _inspect_url(href)
                        if sub_hit:
                            return sub_hit
                doc_links = [
                    href for href, _ in links
                    if ".pdf" in href.lower() or "agenda" in href.lower() or "minutes" in href.lower()
                ]
                if len(doc_links) >= 2:
                    return {"status": "supported", "adapter_type": "gov_web", "portal_url": u, "sample_count": len(doc_links)}
        except Exception:
            pass
        return None

    if submitted_url:
        hit = _inspect_url(submitted_url)
        if hit:
            return hit

    slugs = candidate_slugs(jur_name, state_abbr)
    for slug in slugs:
        for url in (
            f"https://{slug}.legistar.com/",
            f"https://{slug}.primegov.com/public/portal",
            f"https://{slug}.portal.civicclerk.com/",
            f"https://pub-{slug}.escribemeetings.com/",
        ):
            hit = _inspect_url(url)
            if hit:
                return hit

    if waf_blocked:
        return {
            "status": "blocked_waf",
            "adapter_type": "unclaimed",
            "portal_url": submitted_url,
            "sample_count": 0,
            "reason": "Portal returned HTTP 403/429 WAF protection; kept unclaimed to avoid daily pipeline errors.",
        }

    return {
        "status": "unverified",
        "adapter_type": "unclaimed",
        "portal_url": submitted_url,
        "sample_count": 0,
        "reason": "No open structured API or meeting archive auto-detected yet.",
    }


def discover_gov_roster_and_email(
    jur_name: str,
    portal_url: str,
    state_abbr: str = "CO",
) -> Tuple[str, str]:
    """Scouts the municipality's main `.gov`/`.org` website for its Council/Board roster URL
    and official council/clerk public-comment email."""
    slugs = candidate_slugs(jur_name, state_abbr)
    candidate_homes: List[str] = []
    if portal_url and (".gov" in portal_url.lower() or ".org" in portal_url.lower()):
        parsed = urlparse(portal_url)
        candidate_homes.append(f"{parsed.scheme}://{parsed.netloc}/")
    for s in slugs[:3]:
        candidate_homes.extend([f"https://www.{s}.gov/", f"https://{s}.gov/", f"https://www.{s}.org/"])

    roster_url = ""
    council_email = ""

    for home in dict.fromkeys(candidate_homes):
        try:
            r = requests.get(home, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            for raw_href, txt in _extract_links(r.text):
                low_txt = txt.lower()
                href = urljoin(home, raw_href)
                if not roster_url and any(
                    k in low_txt
                    for k in ("city council", "town board", "board of trustees", "commissioners", "board of education", "mayor & council")
                ):
                    roster_url = href
                if not council_email and raw_href.lower().startswith("mailto:"):
                    em = raw_href.split(":", 1)[1].split("?", 1)[0].strip().lower()
                    if EMAIL_RE.match(em) and not em.startswith(GENERIC_EMAIL_PREFIXES):
                        council_email = em
            if not council_email:
                for m in EMAIL_RE.findall(r.text):
                    em = m.lower()
                    if not em.startswith(GENERIC_EMAIL_PREFIXES) and any(k in em for k in ("council", "board", "clerk", "commission", "leaders")):
                        council_email = em
                        break
            if roster_url or council_email:
                break
        except Exception:
            continue

    return roster_url, council_email


def process_pending_onboarding_requests(
    db_path: Path = Path("core_civic.db"),
    public_dir: Path = Path("public"),
    github_repo: str = DEFAULT_GITHUB_REPO,
    max_per_run: int = 2,
    run_initial_watch: bool = True,
) -> Dict[str, Any]:
    """Main autonomous intake & provisioning loop called during `run_daily.ps1`."""
    conn = sqlite3.connect(db_path)
    ensure_onboarding_schema(conn)

    gh_added = sync_github_issue_requests(conn, github_repo=github_repo)

    pending = conn.execute(
        """
        SELECT request_id, source_key, jurisdiction_name, ocd_division_id, state, level, submitted_portal_url
        FROM onboarding_requests
        WHERE status = 'pending'
        ORDER BY request_id ASC
        LIMIT ?
        """,
        (max_per_run,),
    ).fetchall()

    results: List[Dict[str, Any]] = []
    activated_ids: List[str] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    for req_id, src_key, jname, ocd_id, st, lvl, sub_url in pending:
        meta = resolve_from_local_db_or_geo(conn, ocd_id, jname, public_dir / "geo" / "boundaries.geojson")
        canon_id = meta["ocd_division_id"]
        canon_name = meta["name"]
        canon_lvl = meta["level"]
        lookup_url = sub_url or meta["portal_url"]

        probe = probe_portal_candidates(canon_name, st or "CO", submitted_url=lookup_url)
        roster_url, council_email = ("", "")

        if probe["status"] == "supported":
            roster_url, council_email = discover_gov_roster_and_email(canon_name, probe["portal_url"], st or "CO")
            jur_cols = {r[1] for r in conn.execute("PRAGMA table_info(jurisdictions)").fetchall()}

            cur = conn.execute(
                """
                UPDATE jurisdictions
                SET name = ?, level = ?, adapter_type = ?, portal_url = ?, status = 'active',
                    roster_url = COALESCE(NULLIF(?, ''), roster_url),
                    council_email = COALESCE(NULLIF(?, ''), council_email)
                WHERE ocd_division_id = ?
                """,
                (canon_name, canon_lvl, probe["adapter_type"], probe["portal_url"], roster_url, council_email, canon_id),
            )
            if cur.rowcount == 0:
                cols = ["ocd_division_id", "name", "level", "adapter_type", "portal_url", "status", "roster_url", "council_email"]
                vals = [canon_id, canon_name, canon_lvl, probe["adapter_type"], probe["portal_url"], "active", roster_url, council_email]
                if "lat" in jur_cols and "lng" in jur_cols:
                    cols.extend(["lat", "lng"])
                    vals.extend([meta["lat"], meta["lng"]])
                if "latitude" in jur_cols and "longitude" in jur_cols:
                    cols.extend(["latitude", "longitude"])
                    vals.extend([meta["lat"], meta["lng"]])
                ph = ", ".join("?" for _ in cols)
                conn.execute(f"INSERT INTO jurisdictions ({', '.join(cols)}) VALUES ({ph})", vals)

            req_status = "activated"
            note = f"Auto-activated via {probe['adapter_type']} ({probe['sample_count']} sample items)."
            activated_ids.append(canon_id)
        else:
            req_status = probe["status"]
            note = probe.get("reason") or "Kept unclaimed."

        conn.execute(
            """
            UPDATE onboarding_requests
            SET status = ?, detected_adapter = ?, resolved_portal_url = ?,
                resolved_roster_url = ?, council_email = ?, notes = ?, processed_at = ?
            WHERE request_id = ?
            """,
            (
                req_status,
                probe["adapter_type"],
                probe.get("portal_url") or "",
                roster_url,
                council_email,
                note,
                now_iso,
                req_id,
            ),
        )
        conn.commit()
        results.append({
            "request_id": req_id,
            "source_key": src_key,
            "ocd_division_id": canon_id,
            "jurisdiction_name": canon_name,
            "outcome": req_status,
            "adapter_type": probe["adapter_type"],
            "portal_url": probe.get("portal_url") or "",
            "roster_url": roster_url,
            "council_email": council_email,
            "notes": note,
        })

    recent_rows = conn.execute(
        """
        SELECT jurisdiction_name, ocd_division_id, status, detected_adapter, resolved_portal_url, notes, processed_at
        FROM onboarding_requests
        ORDER BY request_id DESC
        LIMIT 25
        """
    ).fetchall()
    conn.close()

    if run_initial_watch and activated_ids:
        for jid in activated_ids:
            try:
                from civicpulse.pipeline.roster_sync import sync_rosters
                sync_rosters(str(db_path), jurisdiction_filter=jid)
            except Exception:
                pass
            try:
                from civicpulse.pipeline.watcher import watch_jurisdictions
                watch_jurisdictions(str(db_path), jurisdiction_filter=jid, force=True)
            except Exception:
                pass

    status_payload = {
        "schema_version": "1.0",
        "updated_at": now_iso,
        "requests": [
            {
                "jurisdiction_name": r[0],
                "ocd_division_id": r[1],
                "status": r[2],
                "adapter_type": r[3] or "unclaimed",
                "portal_url": r[4] or "",
                "notes": r[5] or "",
                "processed_at": r[6] or "",
            }
            for r in recent_rows
        ],
    }
    out_p = public_dir / "data" / "onboarding_status.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(status_payload, indent=2) + "\n", encoding="utf-8")

    return {
        "github_issues_queued": gh_added,
        "processed_count": len(results),
        "activated_count": len(activated_ids),
        "details": results,
    }


def enqueue_local_request(
    db_path: Path,
    jurisdiction_name: str,
    state: str = "CO",
    level: Optional[str] = None,
    portal_url: str = "",
    ocd_division_id: str = "",
) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    ensure_onboarding_schema(conn)
    lvl = infer_level(jurisdiction_name, level)
    ocd = ocd_division_id.strip() or build_ocd_id(jurisdiction_name, state, lvl)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    src_key = f"cli_{ocd}"
    conn.execute(
        """
        INSERT OR REPLACE INTO onboarding_requests
        (source_key, source_type, raw_title, jurisdiction_name, ocd_division_id,
         state, level, submitted_portal_url, status, created_at)
        VALUES (?, 'cli', ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (src_key, jurisdiction_name, jurisdiction_name, ocd, state.upper(), lvl, portal_url, now_iso),
    )
    conn.commit()
    conn.close()
    return {"queued": True, "ocd_division_id": ocd, "jurisdiction_name": jurisdiction_name, "level": lvl}


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Jurisdiction Request Intake & Provisioning Agent")
    parser.add_argument("--db", default="core_civic.db")
    parser.add_argument("--public-dir", default="public")
    parser.add_argument("--github-repo", default=os.environ.get("CIVICPULSE_GITHUB_REPO", DEFAULT_GITHUB_REPO))
    parser.add_argument("--max-per-run", type=int, default=2)
    parser.add_argument("--no-watch", action="store_true", help="Skip immediate watch/roster sync after activation")
    parser.add_argument("--request", default="", help="Queue a jurisdiction name directly from CLI before running")
    parser.add_argument("--portal-url", default="", help="Optional portal URL when using --request")
    parser.add_argument("--level", default="", help="Optional level (city|county|school_district) when using --request")
    args = parser.parse_args()

    db_p = Path(args.db)
    if args.request:
        q = enqueue_local_request(db_p, args.request, level=args.level or None, portal_url=args.portal_url)
        print("[ONBOARD-QUEUE]", json.dumps(q))

    summary = process_pending_onboarding_requests(
        db_path=db_p,
        public_dir=Path(args.public_dir),
        github_repo=args.github_repo,
        max_per_run=args.max_per_run,
        run_initial_watch=not args.no_watch,
    )
    print("[ONBOARD-AGENT]", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
