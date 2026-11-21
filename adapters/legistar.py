"""
Granicus Legistar OData REST API Adapter (GPU-Bypass).
Fetches structured roll-call votes directly from /events -> /eventitems -> /votes.
"""
from datetime import datetime, timedelta, timezone
from typing import List
import requests
from adapters.base import BaseAdapter, IngestionResult, NormalizedEvent, NormalizedVote


class LegistarAdapter(BaseAdapter):
    def _normalize_vote(self, raw_val: str) -> str:
        val = (raw_val or "").strip().lower()
        if val in ("aye", "yes", "yea", "approve", "for"):
            return "Yes"
        if val in ("nay", "no", "against", "oppose"):
            return "No"
        if "abstain" in val or "recus" in val:
            return "Abstain"
        return "Absent"

    def _classify_type(self, title: str, matter_type: str) -> str:
        text = f"{title} {matter_type}".lower()
        if "budget" in text or "appropriat" in text:
            return "budget"
        if "ordinance" in text or "bill" in text:
            return "ordinance"
        if "resolution" in text:
            return "resolution"
        if "consent" in text:
            return "consent"
        return "motion"

    def fetch_recent(self, days_back: int = 30) -> IngestionResult:
        now = datetime.now(timezone.utc)
        since_str = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        until_str = now.strftime("%Y-%m-%d")

        events_url = f"{self.portal_url}/events"
        params = {
            "$filter": f"EventDate ge datetime'{since_str}' and EventDate le datetime'{until_str}'",
            "$orderby": "EventDate desc",
            "$top": 5,  # Keep laptop test runs fast
        }
        resp = requests.get(events_url, params=params, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        meetings = resp.json()

        structured_events: List[NormalizedEvent] = []

        for m in meetings:
            event_id = m.get("EventId")
            meeting_date = (m.get("EventDate") or "")[:10]
            minutes_url = m.get("EventMinutesFile") or m.get("EventInSiteURL") or self.portal_url

            items_resp = requests.get(
                f"{self.portal_url}/events/{event_id}/eventitems",
                headers=self.HEADERS,
                timeout=20,
            )
            if items_resp.status_code != 200:
                continue

            for item in items_resp.json():
                # Only process items that had a recorded action/vote
                if item.get("EventItemPassedFlag") is None:
                    continue

                item_id = item.get("EventItemId")
                votes_resp = requests.get(
                    f"{self.portal_url}/eventitems/{item_id}/votes",
                    headers=self.HEADERS,
                    timeout=20,
                )
                if votes_resp.status_code != 200:
                    continue

                raw_votes = votes_resp.json()
                if not raw_votes:
                    continue

                votes = [
                    NormalizedVote(
                        person_name=v.get("VotePersonName", "Unknown").strip(),
                        vote=self._normalize_vote(v.get("VoteValueName")),
                    )
                    for v in raw_votes
                    if v.get("VotePersonName")
                ]

                outcome = "Passed" if item.get("EventItemPassedFlag") == 1 else "Failed"
                title = (item.get("EventItemTitle") or f"Item {item_id}").strip()
                matter_type = item.get("EventItemMatterType") or ""

                structured_events.append(
                    NormalizedEvent(
                        event_id=f"legistar-{event_id}-{item_id}",
                        meeting_date=meeting_date,
                        title=title[:220],
                        event_type=self._classify_type(title, matter_type),
                        topic=matter_type or "City Council",
                        outcome=outcome,
                        source_url=minutes_url,
                        votes=votes,
                    )
                )

        return IngestionResult(events=structured_events)