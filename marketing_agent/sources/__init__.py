"""Pluggable content-source providers.

Select one with the ``SOURCE_PROVIDER`` env var:
    rss       -> RSSSourceProvider (default; feeds from SOURCE_FEEDS)
    vectordb  -> VectorDBSourceProvider (Postgres + pgvector knowledge base)
    none      -> NoneSourceProvider (no external signals)
    module:Class / module.Class -> your own SourceProvider implementation
"""

from __future__ import annotations

import importlib

from .. import config
from .base import SourceItem, SourceProvider
from .none import NoneSourceProvider
from .rss import RSSSourceProvider

_BUILTIN = {
    "rss": RSSSourceProvider,
    "none": NoneSourceProvider,
    "static": NoneSourceProvider,
    "": NoneSourceProvider,
}


def _load_custom(path: str) -> SourceProvider:
    """Load a provider from a "module:Class" or "module.Class" dotted path."""
    if ":" in path:
        module_name, _, attr = path.partition(":")
    else:
        module_name, _, attr = path.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"Invalid SOURCE_PROVIDER path: {path!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)()


def get_source_provider(name: str | None = None) -> SourceProvider:
    """Resolve the configured (or named) source provider instance."""
    raw = name if name is not None else config.SOURCE_PROVIDER
    key = raw.strip().lower()

    if key == "vectordb":
        # Imported lazily so the optional DB/embedding deps aren't required
        # unless this provider is actually selected.
        from .vectordb import VectorDBSourceProvider

        return VectorDBSourceProvider()
    if key in _BUILTIN:
        return _BUILTIN[key]()
    return _load_custom(raw)


__all__ = [
    "SourceItem",
    "SourceProvider",
    "RSSSourceProvider",
    "NoneSourceProvider",
    "get_source_provider",
]
