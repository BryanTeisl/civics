"""
Universal Adapter Contract.
Every platform adapter (CivicClerk, Legistar, CivicPlus, PrimeGov, etc.)
must emit NormalizedDocument objects (for Agendas/Minutes) or direct NormalizedEvent objects.
"""
from abc import ABC, abstractmethod
from typing import List, Literal, Optional
from pydantic import BaseModel


class NormalizedDocument(BaseModel):
    external_id: str
    meeting_date: str
    doc_type: Literal["agenda", "minutes", "transcript"]
    title: str
    source_url: str
    raw_text: str


class BaseAdapter(ABC):
    def __init__(self, portal_url: str):
        self.portal_url = portal_url.rstrip("/")

    @abstractmethod
    def fetch_recent_documents(self, days_back: int = 30) -> List[NormalizedDocument]:
        """Fetches recent agendas and minutes from the target platform."""
        raise NotImplementedError
