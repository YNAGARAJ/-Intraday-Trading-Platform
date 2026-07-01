"""Unit tests for M09 alpha scoring: TrendScore, VolScore, LiqScore, composite,
strategy assignment, and rank ordering."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt
import pytest

from shared.core.constants import (
    ALPHA_LIQ_AVERAGE_BARS,
    ALPHA_LIQ_RECENT_BARS,
    ALPHA_LIQ_VOLUME_RATIO_CAP,
    STRATEGY_TREND_SCORE_THRESHOLD,
    WATCHLIST_MIN_CANDLES,
)
from shared.regime.models import MarketRegime
from shared.universe.models import AlphaComponents, AlphaWeights, WatchlistEntry
from shared.universe.scoring import (
    BETA_WEIGHTS,
    _liq_score,
    _trend_score,
    _vol_score,
    assign_strategy_id,
    compute_composite,
    rank_entries,
    score_stock,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)


def _flat_close(n: int = 100, price: float = 100.0) -> npt.NDArray[np.float64]:
    """Constant price series — EMA ≈ close, ADX ≈ low."""
    return np.full(n, price, dtype=np.float64)


def _trending_up(
    n: int = 100, start: float = 80.0, end: float = 120.0
) -> npt.NDArray[np.float64]:
    return np.linspace(start, end, n, dtype=np.float64)


def _trending_down(
    n: int = 100, start: float = 120.0, end: float = 80.0
) -> npt.NDArray[np.float64]:
    return np.linspace(start, end, n, dtype=np.float64)


def _volume_array(n: int = 100, base: float = 1_000_000.0) -> npt.NDArray[np.float64]:
    return np.full(n, base, dtype=np.float64)


def _make_entry(
    symbol: str = "TEST",
    composite_score: float = 0.5,
    components: AlphaComponents | None = None,
) -> WatchlistEntry:
    if components is None:
        components = AlphaComponents(
            trend_score=0.5, vol_score=0.5, liq_score=0.5, sent_score=0.0
        )
    return WatchlistEntry(
        symbol=symbol,
        exchange="NSE",
        rank=0,
        composite_score=composite_score,
        components=components,
        regime=MarketRegime.BULL_TREND,
        strategy_id="EMA_VWAP_TREND",
        scored_at=_NOW,
    )


# ---------------------------------------------------------------------------
# BETA_WEIGHTS
# ---------------------------------------------------------------------------


class TestBetaWeights:
    def test_all_three_regimes_present(self) -> None:
        assert MarketRegime.BULL_TREND in BETA_WEIGHTS
        assert MarketRegime.BEAR_TREND in BETA_WEIGHTS
        assert MarketRegime.MEAN_REVERTING in BETA_WEIGHTS

    def test_high_vol_chaos_absent(self) -> None:
        assert MarketRegime.HIGH_VOL_CHAOS not in BETA_WEIGHTS

    def test_weights_sum_to_one(self) -> None:
        for regime, w in BETA_WEIGHTS.items():
            total = w.trend + w.vol + w.liq + w.sent
            assert abs(total - 1.0) < 1e-9, f"{regime} weights sum to {total}"

    def test_bull_trend_maximises_trend_weight(self) -> None:
        w = BETA_WEIGHTS[MarketRegime.BULL_TREND]
        assert w.trend >= w.vol
        assert w.trend >= w.liq
        assert w.trend >= w.sent

    def test_mean_reverting_maximises_vol_weight(self) -> None:
        w = BETA_WEIGHTS[MarketRegime.MEAN_REVERTING]
        assert w.vol >= w.trend
        assert w.vol >= w.liq
        assert w.vol >= w.sent


# ---------------------------------------------------------------------------
# TrendScore
# ---------------------------------------------------------------------------


class TestTrendScore:
    def test_uptrend_bull_gives_nonzero_score(self) -> None:
        close = _trending_up()
        high = close + 1.0
        low = close - 1.0
        score = _trend_score(close, high, low, MarketRegime.BULL_TREND)
        assert score > 0.0

    def test_downtrend_bull_gives_low_or_zero_score(self) -> None:
        close = _trending_down()
        high = close + 1.0
        low = close - 1.0
        score = _trend_score(close, high, low, MarketRegime.BULL_TREND)
        # Price < EMA21 → direction = 0 → score = 0
        assert score == 0.0

    def test_downtrend_bear_gives_nonzero_score(self) -> None:
        close = _trending_down()
        high = close + 1.0
        low = close - 1.0
        score = _trend_score(close, high, low, MarketRegime.BEAR_TREND)
        assert score > 0.0

    def test_uptrend_bear_gives_zero_score(self) -> None:
        close = _trending_up()
        high = close + 1.0
        low = close - 1.0
        score = _trend_score(close, high, low, MarketRegime.BEAR_TREND)
        assert score == 0.0

    def test_mean_reverting_flat_gives_high_score(self) -> None:
        close = _flat_close()
        high = close + 0.5
        low = close - 0.5
        score = _trend_score(close, high, low, MarketRegime.MEAN_REVERTING)
        # Low ADX in flat market → high complement score
        assert score > 0.5

    def test_mean_reverting_strong_trend_gives_low_score(self) -> None:
        close = _trending_up(n=100, start=50.0, end=200.0)
        high = close + 1.0
        low = close - 1.0
        score = _trend_score(close, high, low, MarketRegime.MEAN_REVERTING)
        # Strong trend → high ADX → low complement
        assert score < 0.5

    def test_score_capped_at_one(self) -> None:
        close = _trending_up(n=200, start=50.0, end=500.0)
        high = close + 0.5
        low = close - 0.5
        score = _trend_score(close, high, low, MarketRegime.BULL_TREND)
        assert score <= 1.0

    def test_score_non_negative(self) -> None:
        close = _flat_close()
        high = close + 1.0
        low = close - 1.0
        for regime in (
            MarketRegime.BULL_TREND,
            MarketRegime.BEAR_TREND,
            MarketRegime.MEAN_REVERTING,
        ):
            assert _trend_score(close, high, low, regime) >= 0.0


# ---------------------------------------------------------------------------
# VolScore
# ---------------------------------------------------------------------------


class TestVolScore:
    def test_flat_price_low_vol_score(self) -> None:
        close = _flat_close()
        high = close + 0.1
        low = close - 0.1
        score = _vol_score(close, high, low)
        # BB width ≈ 0 → VolScore ≈ 0
        assert score < 0.1

    def test_high_volatility_gives_higher_score(self) -> None:
        rng = np.random.default_rng(42)
        close = 100.0 + rng.normal(0, 5, 100)
        high = close + 3.0
        low = close - 3.0
        score = _vol_score(close, high, low)
        assert score > 0.1

    def test_score_capped_at_one(self) -> None:
        close = np.linspace(50.0, 200.0, 100)
        high = close * 1.05
        low = close * 0.95
        score = _vol_score(close, high, low)
        assert score <= 1.0

    def test_score_non_negative(self) -> None:
        close = _flat_close()
        high = close + 1.0
        low = close - 1.0
        assert _vol_score(close, high, low) >= 0.0


# ---------------------------------------------------------------------------
# LiqScore
# ---------------------------------------------------------------------------


class TestLiqScore:
    def test_equal_volume_gives_normalised_score(self) -> None:
        vol = _volume_array()
        score = _liq_score(vol)
        # ratio = 1.0, capped at 3.0 → normalised = 1/3
        expected = 1.0 / ALPHA_LIQ_VOLUME_RATIO_CAP
        assert abs(score - expected) < 1e-6

    def test_high_recent_volume_raises_score(self) -> None:
        vol = _volume_array(n=100, base=1_000_000.0)
        # spike recent bars to 3× average
        vol[-ALPHA_LIQ_RECENT_BARS:] = 3_000_000.0
        score = _liq_score(vol)
        # average is pulled up slightly, but recent is still >> average
        assert score > 1.0 / ALPHA_LIQ_VOLUME_RATIO_CAP

    def test_volume_ratio_cap_enforced(self) -> None:
        vol = _volume_array(n=100, base=1.0)
        vol[-ALPHA_LIQ_RECENT_BARS:] = 1_000_000.0  # massively above average
        score = _liq_score(vol)
        assert score == pytest.approx(1.0)

    def test_insufficient_bars_returns_zero(self) -> None:
        vol = _volume_array(n=ALPHA_LIQ_AVERAGE_BARS - 1)
        assert _liq_score(vol) == 0.0

    def test_zero_volume_returns_zero(self) -> None:
        vol = np.zeros(100, dtype=np.float64)
        assert _liq_score(vol) == 0.0

    def test_score_non_negative(self) -> None:
        vol = _volume_array()
        assert _liq_score(vol) >= 0.0


# ---------------------------------------------------------------------------
# score_stock (integration of components)
# ---------------------------------------------------------------------------


class TestScoreStock:
    def test_returns_alpha_components(self) -> None:
        close = _trending_up()
        high = close + 1.0
        low = close - 1.0
        vol = _volume_array()
        result = score_stock(close, high, low, vol, MarketRegime.BULL_TREND)
        assert isinstance(result, AlphaComponents)

    def test_all_scores_in_range(self) -> None:
        close = _trending_up()
        high = close + 1.0
        low = close - 1.0
        vol = _volume_array()
        c = score_stock(close, high, low, vol, MarketRegime.BULL_TREND)
        for score in (c.trend_score, c.vol_score, c.liq_score, c.sent_score):
            assert 0.0 <= score <= 1.0

    def test_sent_score_always_zero(self) -> None:
        close = _trending_up()
        high = close + 1.0
        low = close - 1.0
        vol = _volume_array()
        c = score_stock(close, high, low, vol, MarketRegime.BULL_TREND)
        assert c.sent_score == 0.0

    def test_insufficient_candles_returns_zeros(self) -> None:
        close = _flat_close(n=WATCHLIST_MIN_CANDLES - 1)
        high = close + 1.0
        low = close - 1.0
        vol = _volume_array(n=WATCHLIST_MIN_CANDLES - 1)
        c = score_stock(close, high, low, vol, MarketRegime.BULL_TREND)
        assert c == AlphaComponents(
            trend_score=0.0, vol_score=0.0, liq_score=0.0, sent_score=0.0
        )


# ---------------------------------------------------------------------------
# compute_composite
# ---------------------------------------------------------------------------


class TestComputeComposite:
    def test_zero_components_gives_zero(self) -> None:
        components = AlphaComponents(
            trend_score=0.0, vol_score=0.0, liq_score=0.0, sent_score=0.0
        )
        weights = AlphaWeights(trend=0.5, vol=0.2, liq=0.2, sent=0.1)
        assert compute_composite(components, weights) == 0.0

    def test_all_one_gives_sum_of_weights(self) -> None:
        components = AlphaComponents(
            trend_score=1.0, vol_score=1.0, liq_score=1.0, sent_score=1.0
        )
        weights = AlphaWeights(trend=0.5, vol=0.2, liq=0.2, sent=0.1)
        result = compute_composite(components, weights)
        assert abs(result - 1.0) < 1e-9

    def test_weighted_correctly(self) -> None:
        components = AlphaComponents(
            trend_score=1.0, vol_score=0.0, liq_score=0.0, sent_score=0.0
        )
        weights = BETA_WEIGHTS[MarketRegime.BULL_TREND]
        result = compute_composite(components, weights)
        assert abs(result - weights.trend) < 1e-9


# ---------------------------------------------------------------------------
# assign_strategy_id
# ---------------------------------------------------------------------------


class TestAssignStrategyId:
    def test_bull_high_trend_gives_ema_vwap(self) -> None:
        result = assign_strategy_id(
            MarketRegime.BULL_TREND, STRATEGY_TREND_SCORE_THRESHOLD
        )
        assert result == "EMA_VWAP_TREND"

    def test_bull_low_trend_gives_momentum_rsi(self) -> None:
        result = assign_strategy_id(
            MarketRegime.BULL_TREND, STRATEGY_TREND_SCORE_THRESHOLD - 0.01
        )
        assert result == "MOMENTUM_RSI"

    def test_bear_high_trend_gives_ema_vwap(self) -> None:
        result = assign_strategy_id(MarketRegime.BEAR_TREND, 1.0)
        assert result == "EMA_VWAP_TREND"

    def test_bear_low_trend_gives_momentum_rsi(self) -> None:
        result = assign_strategy_id(MarketRegime.BEAR_TREND, 0.0)
        assert result == "MOMENTUM_RSI"

    def test_mean_reverting_gives_mean_revert_pivot(self) -> None:
        result = assign_strategy_id(MarketRegime.MEAN_REVERTING, 0.0)
        assert result == "MEAN_REVERT_PIVOT"

    def test_mean_reverting_regardless_of_trend_score(self) -> None:
        result = assign_strategy_id(MarketRegime.MEAN_REVERTING, 1.0)
        assert result == "MEAN_REVERT_PIVOT"


# ---------------------------------------------------------------------------
# rank_entries
# ---------------------------------------------------------------------------


class TestRankEntries:
    def test_ranked_by_score_descending(self) -> None:
        entries = [
            _make_entry("A", composite_score=0.3),
            _make_entry("B", composite_score=0.8),
            _make_entry("C", composite_score=0.5),
        ]
        ranked = rank_entries(entries)
        assert [e.symbol for e in ranked] == ["B", "C", "A"]

    def test_ranks_are_one_based(self) -> None:
        entries = [
            _make_entry("X", 0.9),
            _make_entry("Y", 0.7),
            _make_entry("Z", 0.4),
        ]
        ranked = rank_entries(entries)
        assert [e.rank for e in ranked] == [1, 2, 3]

    def test_empty_list_returns_empty(self) -> None:
        assert rank_entries([]) == []

    def test_single_entry_rank_one(self) -> None:
        entry = _make_entry("ONLY", 0.5)
        ranked = rank_entries([entry])
        assert ranked[0].rank == 1

    def test_original_entries_not_mutated(self) -> None:
        entries = [_make_entry("A", 0.3), _make_entry("B", 0.8)]
        _ = rank_entries(entries)
        assert entries[0].rank == 0  # original unchanged
