from .base import BaseAdapter, DocumentRecord, ProbeResult, get_adapter, list_adapters, register_adapter
from . import boarddocs, civicclerk, civicplus, granicus, legistar, primegov  # noqa: F401

__all__ = [
    "BaseAdapter",
    "DocumentRecord",
    "ProbeResult",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
from . import gov_web  # noqa: F401
from . import escribe  # noqa: F401
