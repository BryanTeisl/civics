from __future__ import annotations
import re

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from civicpulse.config import SETTINGS


@dataclass
class DocumentRecord:
    jurisdiction_id: str
    external_id: str
    meeting_date: str
    doc_type: str  # 'agenda', 'minutes', 'packet', 'transcript'
    title: str
    source_url: str
    raw_text: str = ""
    content_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.content_hash:
            key = f"{self.jurisdiction_id}|{self.external_id}|{self.doc_type}|{self.source_url}"
            self.content_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class ProbeResult:
    ok: bool
    status_code: int | str
    item_count: int
    sample_title: str
    adapter_type: str
    normalized_portal_url: str


class BaseAdapter(ABC):
    """Contract implemented by every legislative platform adapter."""

    name: str = "base"
    is_structured: bool = False

    def __init__(self, timeout: Optional[int] = None) -> None:
        self.timeout = timeout or SETTINGS.request_timeout
        self.headers = SETTINGS.headers

    def normalize_portal_url(self, portal_url: str) -> str:
        return (portal_url or "").strip()

    @abstractmethod
    def health_check(self, portal_url: str, year: int) -> ProbeResult:
        """Verifies that the remote legislative portal is reachable."""

    @abstractmethod
    def fetch_documents(
        self, jurisdiction_id: str, portal_url: str, year: int, limit: int = 25
    ) -> List[DocumentRecord]:
        """Polls the remote portal and returns normalized DocumentRecord objects."""


_REGISTRY: Dict[str, Type[BaseAdapter]] = {}


def register_adapter(name: str):
    def decorator(cls: Type[BaseAdapter]) -> Type[BaseAdapter]:
        cls.name = name
        _REGISTRY[name.lower()] = cls
        return cls

    return decorator


def get_adapter(name: str) -> Optional[BaseAdapter]:
    cls = _REGISTRY.get((name or "").strip().lower())
    return cls() if cls else None


def list_adapters() -> List[str]:
    return sorted(_REGISTRY.keys())


COUNCIL_INCLUDE_RE = re.compile(
    r"\b("
    r"city council|town council|town board|board of trustees|"
    r"board of commissioners|board of county commissioners|"
    r"board of education|school board|"
    r"regular council|special council|council meeting|council regular|council special|"
    r"council study"
    r")\b",
    re.IGNORECASE,
)

ADVISORY_EXCLUDE_RE = re.compile(
    r"\b("
    r"advisory|planning commission|planning & zoning|planning and zoning|zoning board|"
    r"historic preservation|preservation commission|tree board|water & sewer|water and sewer|"
    r"parks|recreation|library|arts|cultural|housing authority|urban renewal|"
    r"liquor|beer license|licensing authority|callahan house|youth council|"
    r"golf|airport|museum|cemetery|senior|sustainability|transportation advisory|"
    r"environmental|human relations|open space|citizens|citizen|committee|commission|"
    r"general improvement district|gid\b|gid#|authority|board of adjustment|appeals"
    r")\b",
    re.IGNORECASE,
)


def is_elected_council_meeting(title: str) -> bool:
    """Returns True only for primary elected governing bodies (excludes advisory boards & commissions)."""
    t = (title or "").strip()
    if not t:
        return False
    if ADVISORY_EXCLUDE_RE.search(t):
        return False
    return bool(COUNCIL_INCLUDE_RE.search(t))
