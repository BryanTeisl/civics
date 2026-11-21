"""
Universal Dual-Path Adapter Contract.
Every platform family returns an IngestionResult containing:
  - documents: PDFs/text queued for the RTX 2060 worker
  - events:    Pre-structured roll-call votes that bypass the GPU completely
"""
from abc import ABC, abstractmethod
from typing import List, Literal
from pydantic import BaseModel, Field


class NormalizedDocument(BaseModel):
    external_id: str
    meeting_date: str
    doc_type: Literal["agenda", "minutes", "transcript"]
    title: str
    source_url: str
    raw_text: str


class NormalizedVote(BaseModel):
    person_name: str
    vote: Literal["Yes", "No", "Abstain", "Absent"]
    rationale_summary: str = "Recorded via structured municipal API."


class NormalizedEvent(BaseModel):
    event_id: str
    meeting_date: str
    title: str
    event_type: Literal["ordinance", "resolution", "budget", "motion", "consent"] = "ordinance"
    topic: str = "General"
    outcome: Literal["Passed", "Failed", "Tabled"]
    source_url: str
    votes: List[NormalizedVote] = Field(default_factory=list)


class IngestionResult(BaseModel):
    documents: List[NormalizedDocument] = Field(default_factory=list)
    events: List[NormalizedEvent] = Field(default_factory=list)


class BaseAdapter(ABC):
    HEADERS = {
        "User-Agent": "CivicCoreAggregator/1.0 (+https://github.com/BryanTeisl/civics)"
    }

    def __init__(self, portal_url: str):
        self.portal_url = portal_url.rstrip("/")

    @abstractmethod
    def fetch_recent(self, days_back: int = 30) -> IngestionResult:
        """Fetches recent documents and/or structured vote events."""
        raise NotImplementedError