"""No-op provider.

Use ``SOURCE_PROVIDER=none`` when you don't want any external signals; the
agents then work purely from the brand context configured in config.py.
"""

from __future__ import annotations

from .base import SourceItem


class NoneSourceProvider:
    def fetch(self, limit: int = 40, brief: str | None = None) -> list[SourceItem]:
        return []
