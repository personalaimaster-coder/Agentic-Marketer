"""Ingest trending signals from RSS feeds (Reddit hot.rss + Guardian fashion).

RSS is used instead of the Reddit JSON API because the JSON endpoints return
403 to datacenter IPs; the .rss feeds are public and stable.
"""

from __future__ import annotations

import feedparser

from .. import config


def fetch_sources(limit: int = 40) -> list[dict]:
    """Fetch + dedupe recent items across all configured feeds.

    Returns a list of {title, url, context, source} dicts, capped at `limit`
    to keep token usage lean.
    """
    seen: set[str] = set()
    results: list[dict] = []

    for feed_url in config.SOURCE_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception:
            continue

        if "reddit.com" in feed_url:
            source = "reddit"
        elif "theguardian.com" in feed_url:
            source = "guardian"
        else:
            source = "rss"

        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            url = (entry.get("link") or "").strip()
            if not title or not url or url in seen:
                continue
            seen.add(url)

            summary = entry.get("summary") or entry.get("description") or ""
            # feedparser gives HTML in summaries; a rough strip is enough for ranking.
            context = _strip_html(summary)[:300]

            results.append(
                {"title": title, "url": url, "context": context, "source": source}
            )

    return results[:limit]


def _strip_html(text: str) -> str:
    out, in_tag = [], False
    for ch in text:
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag:
            out.append(ch)
    return "".join(out).strip()
