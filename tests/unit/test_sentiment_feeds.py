"""Unit tests for M10 RSS feed scraping (feeds.py)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from shared.core.constants import SENTIMENT_MAX_HEADLINES_PER_RUN
from shared.sentiment.feeds import (
    _cutoff_utc,
    _parse_entry_time,
    fetch_all_feeds,
    fetch_rss_headlines,
)
from shared.sentiment.models import Headline

# ---------------------------------------------------------------------------
# _cutoff_utc
# ---------------------------------------------------------------------------


class TestCutoffUtc:
    def test_returns_utc(self) -> None:
        dt = _cutoff_utc(24)
        assert dt.tzinfo is not None

    def test_offset_is_24h(self) -> None:
        before = datetime.now(tz=timezone.utc)
        cutoff = _cutoff_utc(24)
        delta = before - cutoff
        assert 23 * 3600 < delta.total_seconds() < 25 * 3600

    def test_zero_hours(self) -> None:
        before = datetime.now(tz=timezone.utc)
        cutoff = _cutoff_utc(0)
        assert abs((before - cutoff).total_seconds()) < 2


# ---------------------------------------------------------------------------
# _parse_entry_time
# ---------------------------------------------------------------------------


class TestParseEntryTime:
    def test_published_parsed_struct(self) -> None:
        entry = MagicMock()
        # time.gmtime() returns a time.struct_time
        entry.published_parsed = time.gmtime(1_000_000_000)
        result = _parse_entry_time(entry)
        assert result is not None
        assert result.tzinfo is not None

    def test_published_string_rfc2822(self) -> None:
        entry = MagicMock()
        entry.published_parsed = None
        entry.published = "Tue, 01 Jul 2026 06:00:00 +0000"
        result = _parse_entry_time(entry)
        assert result is not None
        assert result.year == 2026

    def test_missing_both_returns_none(self) -> None:
        entry = MagicMock()
        entry.published_parsed = None
        entry.published = None
        result = _parse_entry_time(entry)
        assert result is None

    def test_invalid_published_string_returns_none(self) -> None:
        entry = MagicMock()
        entry.published_parsed = None
        entry.published = "not-a-date"
        result = _parse_entry_time(entry)
        assert result is None


# ---------------------------------------------------------------------------
# fetch_rss_headlines — mocking feedparser + network
# ---------------------------------------------------------------------------


def _make_feed_entry(title: str, age_seconds: int = 3600) -> MagicMock:
    """Create a mock feedparser entry."""
    entry = MagicMock()
    entry.title = title
    entry.link = f"https://example.com/{title.replace(' ', '-')}"
    ts = time.time() - age_seconds
    entry.published_parsed = time.gmtime(ts)
    return entry


def _make_parsed_feed(entries: list[MagicMock]) -> MagicMock:
    feed = MagicMock()
    feed.entries = entries
    return feed


class TestFetchRSSHeadlines:
    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_returns_list_of_headlines(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = _make_parsed_feed(
            [_make_feed_entry("NIFTY up 1%"), _make_feed_entry("RBI holds rates")]
        )
        result = fetch_rss_headlines("http://example.com/rss", "test", "NSE")
        assert len(result) == 2
        assert all(isinstance(h, Headline) for h in result)

    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_stale_entries_excluded(self, mock_fetch: MagicMock) -> None:
        fresh = _make_feed_entry("Fresh news", age_seconds=3600)
        stale = _make_feed_entry("Old news", age_seconds=25 * 3600)
        mock_fetch.return_value = _make_parsed_feed([fresh, stale])
        result = fetch_rss_headlines("http://x.com", "src", "NSE", max_age_hours=24)
        assert len(result) == 1
        assert result[0].text == "Fresh news"

    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_blank_title_skipped(self, mock_fetch: MagicMock) -> None:
        blank = _make_feed_entry("")
        valid = _make_feed_entry("Market rally")
        mock_fetch.return_value = _make_parsed_feed([blank, valid])
        result = fetch_rss_headlines("http://x.com", "src", "ASX")
        assert len(result) == 1
        assert result[0].text == "Market rally"

    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_exchange_set_on_headlines(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = _make_parsed_feed(
            [_make_feed_entry("ASX daily recap")]
        )
        result = fetch_rss_headlines("http://x.com", "asx", "ASX")
        assert result[0].exchange == "ASX"

    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_empty_feed_returns_empty(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = _make_parsed_feed([])
        result = fetch_rss_headlines("http://x.com", "src", "NSE")
        assert result == []

    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_none_url_on_entry(self, mock_fetch: MagicMock) -> None:
        entry = _make_feed_entry("Valid headline")
        entry.link = None
        mock_fetch.return_value = _make_parsed_feed([entry])
        result = fetch_rss_headlines("http://x.com", "src", "NSE")
        assert len(result) == 1
        assert result[0].url is None

    @patch("shared.sentiment.feeds._fetch_feed_raw")
    def test_missing_published_uses_now(self, mock_fetch: MagicMock) -> None:
        entry = MagicMock()
        entry.title = "No date headline"
        entry.link = "http://x.com"
        entry.published_parsed = None
        entry.published = None
        mock_fetch.return_value = _make_parsed_feed([entry])
        result = fetch_rss_headlines("http://x.com", "src", "NSE")
        # Should still be included (falls back to now, which is always fresh)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# fetch_all_feeds
# ---------------------------------------------------------------------------


class TestFetchAllFeeds:
    @patch("shared.sentiment.feeds.fetch_rss_headlines")
    @patch("shared.sentiment.feeds.fetch_nse_announcements")
    def test_nse_fetches_both_rss_and_announcements(
        self, mock_ann: MagicMock, mock_rss: MagicMock
    ) -> None:
        def _make_h(text: str) -> Headline:
            return Headline(
                text=text,
                url=None,
                source="test",
                published_at=datetime.now(tz=timezone.utc),
                exchange="NSE",
            )

        mock_rss.return_value = [_make_h("NSE RSS headline")]
        mock_ann.return_value = [_make_h("NSE announcement")]
        result = fetch_all_feeds("NSE")
        assert len(result) == 2
        mock_ann.assert_called_once()

    @patch("shared.sentiment.feeds.fetch_rss_headlines")
    @patch("shared.sentiment.feeds.fetch_nse_announcements")
    def test_asx_skips_nse_announcements(
        self, mock_ann: MagicMock, mock_rss: MagicMock
    ) -> None:
        mock_rss.return_value = []
        result = fetch_all_feeds("ASX")
        mock_ann.assert_not_called()
        assert result == []

    @patch("shared.sentiment.feeds.fetch_rss_headlines")
    @patch("shared.sentiment.feeds.fetch_nse_announcements")
    def test_deduplicates_same_text(
        self, mock_ann: MagicMock, mock_rss: MagicMock
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        dup = Headline(
            text="Duplicate headline",
            url=None,
            source="s",
            published_at=now,
            exchange="NSE",
        )
        mock_rss.return_value = [dup]
        mock_ann.return_value = [dup]
        result = fetch_all_feeds("NSE")
        assert len(result) == 1

    @patch("shared.sentiment.feeds.fetch_rss_headlines")
    @patch("shared.sentiment.feeds.fetch_nse_announcements")
    def test_capped_at_max_headlines(
        self, mock_ann: MagicMock, mock_rss: MagicMock
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        many = [
            Headline(
                text=f"Headline {i}",
                url=None,
                source="s",
                published_at=now,
                exchange="NSE",
            )
            for i in range(SENTIMENT_MAX_HEADLINES_PER_RUN + 10)
        ]
        mock_rss.return_value = many
        mock_ann.return_value = []
        result = fetch_all_feeds("NSE")
        assert len(result) <= SENTIMENT_MAX_HEADLINES_PER_RUN

    @patch("shared.sentiment.feeds.fetch_rss_headlines")
    @patch("shared.sentiment.feeds.fetch_nse_announcements")
    def test_unknown_exchange_returns_empty(
        self, mock_ann: MagicMock, mock_rss: MagicMock
    ) -> None:
        result = fetch_all_feeds("NYSE")
        assert result == []
        mock_rss.assert_not_called()

    @patch("shared.sentiment.feeds.fetch_rss_headlines")
    @patch("shared.sentiment.feeds.fetch_nse_announcements")
    def test_sorted_newest_first(
        self, mock_ann: MagicMock, mock_rss: MagicMock
    ) -> None:
        from datetime import timedelta

        old = Headline(
            text="Old news",
            url=None,
            source="s",
            published_at=datetime.now(tz=timezone.utc) - timedelta(hours=5),
            exchange="NSE",
        )
        new = Headline(
            text="New news",
            url=None,
            source="s",
            published_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
            exchange="NSE",
        )
        mock_rss.return_value = [old, new]
        mock_ann.return_value = []
        result = fetch_all_feeds("NSE")
        assert result[0].text == "New news"
