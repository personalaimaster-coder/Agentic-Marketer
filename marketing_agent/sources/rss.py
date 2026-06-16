"""RSS/Atom feed provider (the default source).

Wraps the feed-ingestion logic in ``tools/sources.py``. RSS is robust: no auth,
no rate-limit headaches. Configure feeds via ``SOURCE_FEEDS`` (see config.py).
"""

from __future__ import annotations

from ..tools import sources as _rss
from .base import SourceItem


class RSSSourceProvider:
    def fetch(self, limit: int = 40, brief: str | None = None) -> list[SourceItem]:
        return _rss.fetch_sources(limit=limit)
