"""M10 Sentiment & News Agent — RSS and announcement feed scrapers.

Public API
----------
fetch_rss_headlines(url, source, exchange, max_age_hours) → list[Headline]
fetch_all_feeds(exchange, max_age_hours)                  → list[Headline]
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import cast

import feedparser
import structlog

from shared.core.constants import (
    SENTIMENT_MAX_FEED_AGE_HOURS,
    SENTIMENT_MAX_HEADLINES_PER_RUN,
)
from shared.sentiment.models import Headline

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Feed URL registry
# ---------------------------------------------------------------------------

_NSE_RSS: dict[str, str] = {
    "economic_times": (
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms"
    ),
    "moneycontrol": "https://www.moneycontrol.com/rss/MCtopnews.xml",
}

_ASX_RSS: dict[str, str] = {
    "asx_newsroom": (
        "https://www.asx.com.au/content/asx/home/news/news_releases"
        ".html.rss.xml"
    ),
}

_NSE_ANNOUNCEMENT_URL: str = (
    "https://nsearchives.nseindia.com/web/sites/default/files/"
    "nse_corporate_announcements_rss.xml"
)

_USER_AGENT: str = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_FETCH_TIMEOUT_SECONDS: int = 15


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cutoff_utc(max_age_hours: int) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)


def _parse_entry_time(entry: object) -> datetime | None:
    """Extract a timezone-aware UTC datetime from a feedparser entry."""
    # feedparser populates published_parsed (time.struct_time) when available
    published_parsed = getattr(entry, "published_parsed", None)
    if published_parsed is not None:
        ts = time.mktime(published_parsed)
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    # Fall back to published string
    published_str = getattr(entry, "published", None)
    if published_str:
        try:
            parsed = parsedate_to_datetime(published_str).astimezone(timezone.utc)
            return cast(datetime, parsed)
        except Exception:  # noqa: BLE001
            pass

    return None


def _fetch_feed_raw(url: str) -> object:
    """Fetch and parse an RSS feed URL; return feedparser result or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            data = resp.read()
        return feedparser.parse(data)
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("feed_fetch_failed", url=url, error=str(exc))
        return feedparser.parse("")


# ---------------------------------------------------------------------------
# Public scrapers
# ---------------------------------------------------------------------------


def fetch_rss_headlines(
    url: str,
    source: str,
    exchange: str | None,
    max_age_hours: int = SENTIMENT_MAX_FEED_AGE_HOURS,
) -> list[Headline]:
    """Fetch and parse a single RSS feed; return non-stale Headline objects.

    Args:
        url:          RSS feed URL.
        source:       Logical name (e.g. ``"economic_times"``).
        exchange:     Target exchange (``"NSE"``, ``"ASX"``, or ``None`` for both).
        max_age_hours: Discard entries older than this.

    Returns:
        List of Headline objects, newest first, capped at
        ``SENTIMENT_MAX_HEADLINES_PER_RUN``.
    """
    cutoff = _cutoff_utc(max_age_hours)
    parsed = _fetch_feed_raw(url)
    entries = getattr(parsed, "entries", [])

    headlines: list[Headline] = []
    for entry in entries:
        title = getattr(entry, "title", "").strip()
        if not title:
            continue

        pub = _parse_entry_time(entry)
        if pub is None:
            pub = datetime.now(tz=timezone.utc)
        if pub < cutoff:
            continue

        link = getattr(entry, "link", None) or None
        try:
            headlines.append(
                Headline(
                    text=title,
                    url=link,
                    source=source,
                    published_at=pub,
                    exchange=exchange,
                )
            )
        except ValueError as exc:
            logger.warning(
                "headline_skipped", source=source, title=title[:60], error=str(exc)
            )

    logger.info(
        "feed_fetched",
        source=source,
        exchange=exchange,
        total=len(entries),
        kept=len(headlines),
    )
    return headlines


def fetch_nse_announcements(
    max_age_hours: int = SENTIMENT_MAX_FEED_AGE_HOURS,
) -> list[Headline]:
    """Fetch NSE corporate announcement RSS feed.

    Args:
        max_age_hours: Discard entries older than this.

    Returns:
        List of Headline objects for NSE corporate announcements.
    """
    return fetch_rss_headlines(
        url=_NSE_ANNOUNCEMENT_URL,
        source="nse_announcements",
        exchange="NSE",
        max_age_hours=max_age_hours,
    )


def fetch_all_feeds(
    exchange: str,
    max_age_hours: int = SENTIMENT_MAX_FEED_AGE_HOURS,
) -> list[Headline]:
    """Fetch all relevant news feeds for a given exchange.

    Fetches exchange-specific RSS feeds plus NSE announcements (NSE only).
    Result is capped at ``SENTIMENT_MAX_HEADLINES_PER_RUN`` (newest first).

    Args:
        exchange:     ``"NSE"`` or ``"ASX"``.
        max_age_hours: Discard entries older than this.

    Returns:
        Combined, deduplicated headline list, newest first.
    """
    if exchange.upper() == "NSE":
        feed_map = _NSE_RSS
    elif exchange.upper() == "ASX":
        feed_map = _ASX_RSS
    else:
        logger.warning("fetch_all_feeds_unknown_exchange", exchange=exchange)
        return []

    all_headlines: list[Headline] = []
    for source, url in feed_map.items():
        all_headlines.extend(
            fetch_rss_headlines(url, source, exchange.upper(), max_age_hours)
        )

    if exchange.upper() == "NSE":
        all_headlines.extend(fetch_nse_announcements(max_age_hours))

    # Deduplicate by text, preserve order (newest first after sort)
    seen: set[str] = set()
    unique: list[Headline] = []
    for h in sorted(all_headlines, key=lambda h: h.published_at, reverse=True):
        if h.text not in seen:
            seen.add(h.text)
            unique.append(h)

    capped = unique[:SENTIMENT_MAX_HEADLINES_PER_RUN]
    logger.info(
        "fetch_all_feeds_done",
        exchange=exchange,
        total=len(all_headlines),
        unique=len(unique),
        capped=len(capped),
    )
    return capped
