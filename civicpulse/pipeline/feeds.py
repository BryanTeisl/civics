"""Static RSS 2.0 feed generator for CivicPulse.

Generates zero-server, $0/month RSS feeds under public/feeds/ so residents can
subscribe in any RSS/email reader and businesses can connect directly to Slack,
Microsoft Teams, or Zapier alerts by city or topic.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Dict, List


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "general"


def _rfc2822(date_str: str) -> str:
    try:
        dt = datetime.strptime((date_str or "")[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)
    return format_datetime(dt)


def build_rss_xml(
    title: str,
    link: str,
    description: str,
    items: List[Dict[str, Any]],
    site_base_url: str = "https://civics-d03.pages.dev",
    max_items: int = 50,
) -> str:
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = link
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    sorted_items = sorted(
        items,
        key=lambda x: (x.get("meeting_date") or "", x.get("impact_score") or 0),
        reverse=True,
    )[:max_items]

    for ev in sorted_items:
        item = ET.SubElement(channel, "item")
        jur = ev.get("jurisdiction_name") or ev.get("jurisdiction_id") or "Local Gov"
        ev_title = ev.get("title") or "Local Measure"
        outcome = ev.get("outcome_status") or ev.get("outcome") or "Recorded"
        tally = ev.get("tally") or ""
        score = ev.get("impact_score")
        topic = ev.get("topic") or "General"

        headline = f"[{jur}] {ev_title}"
        if tally:
            headline += f" ({outcome} {tally})"
        elif outcome:
            headline += f" ({outcome})"

        ET.SubElement(item, "title").text = headline
        event_id = ev.get("event_id") or ""
        item_link = (
            f"{site_base_url.rstrip('/')}/#/bill/{event_id}"
            if event_id
            else (ev.get("source_url") or site_base_url)
        )
        ET.SubElement(item, "link").text = item_link
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = event_id or f"{jur}:{ev.get('meeting_date')}:{ev_title[:40]}"
        ET.SubElement(item, "pubDate").text = _rfc2822(ev.get("meeting_date") or "")
        ET.SubElement(item, "category").text = topic

        desc_parts = []
        if ev.get("plain_summary"):
            desc_parts.append(ev["plain_summary"])
        meta_bits = [f"Topic: {topic}", f"Outcome: {outcome}"]
        if tally:
            meta_bits.append(f"Tally: {tally}")
        if score is not None:
            meta_bits.append(f"Impact Score: {score}/100")
        if ev.get("capture_method"):
            meta_bits.append(f"Source: {ev['capture_method']}")
        desc_parts.append(" | ".join(meta_bits))
        if ev.get("source_url"):
            desc_parts.append(f"Official Document: {ev['source_url']}")

        ET.SubElement(item, "description").text = "\n\n".join(desc_parts)

    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def generate_all_feeds(
    events: List[Dict[str, Any]],
    public_dir: Path,
    site_base_url: str = "https://civics-d03.pages.dev",
) -> Dict[str, Any]:
    """Writes all.xml, per-jurisdiction feeds, per-topic feeds, and feeds_index.json."""
    feeds_dir = public_dir / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Any] = {
        "all": "feeds/all.xml",
        "jurisdictions": {},
        "topics": {},
    }

    # 1. Master feed
    (feeds_dir / "all.xml").write_text(
        build_rss_xml(
            title="CivicPulse — All Colorado Local Measures & Votes",
            link=site_base_url,
            description="Plain-English local government votes, ordinances, and agendas tracked by CivicPulse.",
            items=events,
            site_base_url=site_base_url,
        ),
        encoding="utf-8",
    )

    # 2. Per-jurisdiction feeds
    by_jur: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        jkey = ev.get("jurisdiction_slug") or _slug(ev.get("jurisdiction_name") or ev.get("jurisdiction_id") or "")
        by_jur.setdefault(jkey, []).append(ev)

    for jslug, jevents in sorted(by_jur.items()):
        jname = jevents[0].get("jurisdiction_name") or jslug
        fname = f"jur_{jslug}.xml"
        (feeds_dir / fname).write_text(
            build_rss_xml(
                title=f"CivicPulse — {jname}",
                link=f"{site_base_url}/#/jur/{jevents[0].get('jurisdiction_id', '')}",
                description=f"Latest votes, ordinances, and agendas for {jname}.",
                items=jevents,
                site_base_url=site_base_url,
            ),
            encoding="utf-8",
        )
        manifest["jurisdictions"][jslug] = {
            "name": jname,
            "url": f"feeds/{fname}",
            "item_count": len(jevents),
        }

    # 3. Per-topic feeds (ideal for residents & businesses tracking Zoning, Budget, Utilities, etc.)
    by_topic: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        topic = ev.get("topic") or "General"
        by_topic.setdefault(topic, []).append(ev)

    for topic, tevents in sorted(by_topic.items()):
        tslug = _slug(topic)
        fname = f"topic_{tslug}.xml"
        (feeds_dir / fname).write_text(
            build_rss_xml(
                title=f"CivicPulse Topic — {topic}",
                link=site_base_url,
                description=f"All tracked local government measures related to {topic}.",
                items=tevents,
                site_base_url=site_base_url,
            ),
            encoding="utf-8",
        )
        manifest["topics"][topic] = {
            "url": f"feeds/{fname}",
            "item_count": len(tevents),
        }

    (public_dir / "data").mkdir(parents=True, exist_ok=True)
    (public_dir / "data" / "feeds_index.json").write_text(
        __import__("json").dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
