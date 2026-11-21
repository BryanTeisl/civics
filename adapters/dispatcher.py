"""
Platform Family Dispatcher.
Routes each jurisdiction to its vendor adapter and enforces polite rate limits.
"""
import time
from typing import Dict, Type
from adapters.base import BaseAdapter, IngestionResult
from adapters.civicclerk import CivicClerkAdapter
from adapters.legistar import LegistarAdapter
from adapters.vendors import (
    CivicPlusAdapter,
    PrimeGovAdapter,
    GranicusAdapter,
    BoardDocsAdapter,
)

PLATFORM_REGISTRY: Dict[str, Type[BaseAdapter]] = {
    "civicclerk": CivicClerkAdapter,
    "legistar": LegistarAdapter,
    "civicplus": CivicPlusAdapter,
    "primegov": PrimeGovAdapter,
    "granicus": GranicusAdapter,
    "boarddocs": BoardDocsAdapter,
}


def dispatch_jurisdiction(adapter_type: str, portal_url: str, days_back: int = 30) -> IngestionResult:
    key = adapter_type.lower().strip()
    adapter_cls = PLATFORM_REGISTRY.get(key)
    if not adapter_cls:
        raise ValueError(f"Unsupported platform family: '{adapter_type}'")

    # Polite 0.5s pause between portals to avoid triggering municipal WAFs
    time.sleep(0.5)
    adapter = adapter_cls(portal_url)
    return adapter.fetch_recent(days_back=days_back)