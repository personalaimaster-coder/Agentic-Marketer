"""The data-source contract every provider implements.

A SourceProvider turns "what's worth talking about right now" into a flat list
of signal dicts the research agent reasons over. Bring your own data source by
implementing this Protocol and pointing SOURCE_PROVIDER at "module:Class".

Each returned item is a dict with these keys:
    title   (str)  -> short headline / row title
    url     (str)  -> source link, or "" if none
    context (str)  -> a short snippet of supporting text (<= ~300 chars)
    source  (str)  -> a label for where it came from (e.g. "rss", "vectordb")
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

SourceItem = dict


@runtime_checkable
class SourceProvider(Protocol):
    """Anything with a ``fetch`` method that returns signal items."""

    def fetch(self, limit: int = 40, brief: str | None = None) -> list[SourceItem]:
        """Return up to ``limit`` signal items.

        ``brief`` is an optional free-text hint (e.g. a campaign brief) that
        retrieval-based providers can use to ground their query. Providers that
        don't need it may ignore it.
        """
        ...
