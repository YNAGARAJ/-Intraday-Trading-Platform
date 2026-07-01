"""Unit tests for M10 sentiment models (models.py)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from shared.sentiment.models import (
    FIIDIIData,
    Headline,
    MarketSentiment,
    SentimentScore,
    VIXData,
)

_NOW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)


def _headline(**kwargs: object) -> Headline:
    defaults: dict[str, object] = {
        "text": "NIFTY rises 2% on positive data",
        "url": "https://example.com/article",
        "source": "economic_times",
        "published_at": _NOW,
        "exchange": "NSE",
    }
    defaults.update(kwargs)
    return Headline(**defaults)  # type: ignore[arg-type]


def _score(**kwargs: object) -> SentimentScore:
    defaults: dict[str, object] = {
        "headline": "NIFTY rises 2%",
        "score": 0.7,
        "label": "BULLISH",
        "confidence": 0.85,
        "tokens_used": 50,
        "from_cache": False,
        "model_version": "groq/llama-3.1-8b-instant",
    }
    defaults.update(kwargs)
    return SentimentScore(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Headline
# ---------------------------------------------------------------------------


class TestHeadline:
    def test_valid_construction(self) -> None:
        h = _headline()
        assert h.text == "NIFTY rises 2% on positive data"
        assert h.exchange == "NSE"

    def test_blank_text_raises(self) -> None:
        with pytest.raises(ValueError, match="blank"):
            _headline(text="   ")

    def test_naive_datetime_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            _headline(published_at=datetime(2026, 7, 1, 6, 0))

    def test_unknown_exchange_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown exchange"):
            _headline(exchange="NYSE")

    def test_none_exchange_allowed(self) -> None:
        h = _headline(exchange=None)
        assert h.exchange is None

    def test_none_url_allowed(self) -> None:
        h = _headline(url=None)
        assert h.url is None

    def test_asx_exchange_valid(self) -> None:
        h = _headline(exchange="ASX")
        assert h.exchange == "ASX"


# ---------------------------------------------------------------------------
# SentimentScore
# ---------------------------------------------------------------------------


class TestSentimentScore:
    def test_valid_bullish(self) -> None:
        s = _score()
        assert s.label == "BULLISH"
        assert 0.0 <= s.score <= 1.0

    def test_valid_bearish(self) -> None:
        s = _score(score=-0.5, label="BEARISH")
        assert s.label == "BEARISH"

    def test_valid_neutral(self) -> None:
        s = _score(score=0.0, label="NEUTRAL", confidence=0.3)
        assert s.label == "NEUTRAL"

    def test_score_out_of_range_low(self) -> None:
        with pytest.raises(ValueError, match="score"):
            _score(score=-1.1)

    def test_score_out_of_range_high(self) -> None:
        with pytest.raises(ValueError, match="score"):
            _score(score=1.01)

    def test_unknown_label_raises(self) -> None:
        with pytest.raises(ValueError, match="label"):
            _score(label="POSITIVE")

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            _score(confidence=1.1)

    def test_negative_tokens_raises(self) -> None:
        with pytest.raises(ValueError, match="tokens_used"):
            _score(tokens_used=-1)

    def test_from_cache_true(self) -> None:
        s = _score(from_cache=True, tokens_used=0)
        assert s.from_cache is True
        assert s.tokens_used == 0

    def test_score_boundary_minus_one(self) -> None:
        s = _score(score=-1.0, label="BEARISH")
        assert s.score == -1.0

    def test_score_boundary_plus_one(self) -> None:
        s = _score(score=1.0, label="BULLISH")
        assert s.score == 1.0


# ---------------------------------------------------------------------------
# FIIDIIData
# ---------------------------------------------------------------------------


class TestFIIDIIData:
    def test_valid_construction(self) -> None:
        d = FIIDIIData(
            date=date(2026, 7, 1),
            fii_net_crore=1234.5,
            dii_net_crore=-567.8,
            fetched_at=_NOW,
        )
        assert d.fii_net_crore == 1234.5

    def test_net_institutional_property(self) -> None:
        d = FIIDIIData(
            date=date(2026, 7, 1),
            fii_net_crore=1000.0,
            dii_net_crore=500.0,
            fetched_at=_NOW,
        )
        assert d.net_institutional == 1500.0

    def test_negative_net_institutional(self) -> None:
        d = FIIDIIData(
            date=date(2026, 7, 1),
            fii_net_crore=-800.0,
            dii_net_crore=-300.0,
            fetched_at=_NOW,
        )
        assert d.net_institutional == -1100.0

    def test_naive_fetched_at_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            FIIDIIData(
                date=date(2026, 7, 1),
                fii_net_crore=0.0,
                dii_net_crore=0.0,
                fetched_at=datetime(2026, 7, 1, 6, 0),
            )


# ---------------------------------------------------------------------------
# VIXData
# ---------------------------------------------------------------------------


class TestVIXData:
    def test_valid_construction(self) -> None:
        v = VIXData(vix=14.5, put_call_ratio=0.95, fetched_at=_NOW)
        assert v.vix == 14.5
        assert v.put_call_ratio == 0.95

    def test_none_pcr_allowed(self) -> None:
        v = VIXData(vix=20.0, put_call_ratio=None, fetched_at=_NOW)
        assert v.put_call_ratio is None

    def test_negative_vix_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            VIXData(vix=-1.0, put_call_ratio=None, fetched_at=_NOW)

    def test_negative_pcr_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            VIXData(vix=15.0, put_call_ratio=-0.1, fetched_at=_NOW)

    def test_naive_fetched_at_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            VIXData(
                vix=15.0, put_call_ratio=None, fetched_at=datetime(2026, 7, 1)
            )


# ---------------------------------------------------------------------------
# MarketSentiment
# ---------------------------------------------------------------------------


class TestMarketSentiment:
    def _make(self, **kwargs: object) -> MarketSentiment:
        defaults: dict[str, object] = dict(
            exchange="NSE",
            headlines=[_headline()],
            scores=[_score()],
            aggregate_score=0.5,
            fii_dii=None,
            vix_data=None,
            total_tokens_used=50,
            total_cost_usd=0.000025,
            cache_hits=0,
            cache_misses=1,
            scored_at=_NOW,
        )
        defaults.update(kwargs)
        return MarketSentiment(**defaults)  # type: ignore[arg-type]

    def test_cache_hit_rate_no_total(self) -> None:
        ms = self._make(cache_hits=0, cache_misses=0)
        assert ms.cache_hit_rate == 0.0

    def test_cache_hit_rate_all_hits(self) -> None:
        ms = self._make(cache_hits=5, cache_misses=0)
        assert ms.cache_hit_rate == 1.0

    def test_cache_hit_rate_mixed(self) -> None:
        ms = self._make(cache_hits=3, cache_misses=7)
        assert abs(ms.cache_hit_rate - 0.3) < 1e-9

    def test_empty_factory(self) -> None:
        ms = MarketSentiment.empty("ASX")
        assert ms.exchange == "ASX"
        assert ms.headlines == []
        assert ms.scores == []
        assert ms.aggregate_score == 0.0
        assert ms.cache_hit_rate == 0.0

    def test_empty_has_utc_scored_at(self) -> None:
        ms = MarketSentiment.empty("NSE")
        assert ms.scored_at.tzinfo is not None
