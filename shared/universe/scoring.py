"""M09 alpha scoring: TrendScore, VolScore, LiqScore, composite, strategy assignment.

All computation is pure NumPy/TA-Lib — no LLM, no network I/O.  SentScore is
always 0.0 until M10 supplies sentiment data; the β weight slot is reserved.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import talib

from shared.core.constants import (
    ALPHA_BETA_BEAR_TREND,
    ALPHA_BETA_BULL_TREND,
    ALPHA_BETA_MEAN_REVERTING,
    ALPHA_LIQ_AVERAGE_BARS,
    ALPHA_LIQ_RECENT_BARS,
    ALPHA_LIQ_VOLUME_RATIO_CAP,
    ALPHA_TREND_ADX_SCALE,
    ALPHA_VOL_BB_WIDTH_SCALE,
    STRATEGY_TREND_SCORE_THRESHOLD,
    WATCHLIST_MIN_CANDLES,
)
from shared.regime.models import MarketRegime
from shared.universe.models import AlphaComponents, AlphaWeights, WatchlistEntry

# β-weight table keyed by regime.  HIGH_VOL_CHAOS is absent intentionally —
# the filter layer returns an empty watchlist before scoring begins (RULE 2).
BETA_WEIGHTS: dict[MarketRegime, AlphaWeights] = {
    MarketRegime.BULL_TREND: AlphaWeights(*ALPHA_BETA_BULL_TREND),
    MarketRegime.BEAR_TREND: AlphaWeights(*ALPHA_BETA_BEAR_TREND),
    MarketRegime.MEAN_REVERTING: AlphaWeights(*ALPHA_BETA_MEAN_REVERTING),
}


def _trend_score(
    close: npt.NDArray[np.float64],
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
    regime: MarketRegime,
) -> float:
    """Compute TrendScore ∈ [0, 1] from EMA21 direction × normalised ADX.

    For BULL_TREND: positive slope (close > EMA21) earns the full ADX weight.
    For BEAR_TREND: negative slope (close < EMA21) earns the full ADX weight.
    For MEAN_REVERTING: score is ADX-complement (low ADX = high MEAN_REV score).
    """
    ema21: npt.NDArray[np.float64] = talib.EMA(close, timeperiod=21)
    adx: npt.NDArray[np.float64] = talib.ADX(high, low, close, timeperiod=14)

    last_close = float(close[-1])
    last_ema = float(ema21[-1])
    last_adx = float(adx[-1])

    if np.isnan(last_ema) or np.isnan(last_adx):
        return 0.0

    adx_norm = min(last_adx / ALPHA_TREND_ADX_SCALE, 1.0)

    if regime == MarketRegime.BULL_TREND:
        direction = 1.0 if last_close > last_ema else 0.0
        return adx_norm * direction
    if regime == MarketRegime.BEAR_TREND:
        direction = 1.0 if last_close < last_ema else 0.0
        return adx_norm * direction
    # MEAN_REVERTING: favour low-ADX (ranging) stocks
    return max(0.0, 1.0 - adx_norm)


def _vol_score(
    close: npt.NDArray[np.float64],
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
) -> float:
    """Compute VolScore ∈ [0, 1] from normalised Bollinger Band width %.

    BB width % = (upper - lower) / middle × 100.
    ALPHA_VOL_BB_WIDTH_SCALE (5.0) maps a 5% width to score 1.0.
    """
    upper, middle, lower = talib.BBANDS(close, timeperiod=20)
    mid = float(middle[-1])
    if np.isnan(mid) or mid == 0.0:
        return 0.0
    width_pct = (float(upper[-1]) - float(lower[-1])) / mid * 100.0
    if np.isnan(width_pct):
        return 0.0
    return min(width_pct / ALPHA_VOL_BB_WIDTH_SCALE, 1.0)


def _liq_score(volume: npt.NDArray[np.float64]) -> float:
    """Compute LiqScore ∈ [0, 1] from recent vs. average volume ratio.

    ratio = mean(last ALPHA_LIQ_RECENT_BARS bars) /
    mean(last ALPHA_LIQ_AVERAGE_BARS bars).
    Capped at ALPHA_LIQ_VOLUME_RATIO_CAP before normalising to [0, 1].
    """
    if len(volume) < ALPHA_LIQ_AVERAGE_BARS:
        return 0.0
    avg = float(np.mean(volume[-ALPHA_LIQ_AVERAGE_BARS:]))
    if avg == 0.0:
        return 0.0
    recent = float(np.mean(volume[-ALPHA_LIQ_RECENT_BARS:]))
    ratio = min(recent / avg, ALPHA_LIQ_VOLUME_RATIO_CAP)
    return ratio / ALPHA_LIQ_VOLUME_RATIO_CAP


def score_stock(
    close: npt.NDArray[np.float64],
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
    volume: npt.NDArray[np.float64],
    regime: MarketRegime,
) -> AlphaComponents:
    """Compute individual alpha component scores for one instrument.

    Args:
        close:  1-D float64 array of closing prices (oldest → newest).
        high:   1-D float64 array of high prices.
        low:    1-D float64 array of low prices.
        volume: 1-D float64 array of volume values.
        regime: Current market regime (must NOT be HIGH_VOL_CHAOS).

    Returns:
        AlphaComponents with each score in [0.0, 1.0].  Returns all-zeros
        if the array is shorter than WATCHLIST_MIN_CANDLES.
    """
    if len(close) < WATCHLIST_MIN_CANDLES:
        return AlphaComponents(
            trend_score=0.0, vol_score=0.0, liq_score=0.0, sent_score=0.0
        )
    return AlphaComponents(
        trend_score=_trend_score(close, high, low, regime),
        vol_score=_vol_score(close, high, low),
        liq_score=_liq_score(volume),
        sent_score=0.0,  # reserved for M10
    )


def compute_composite(components: AlphaComponents, weights: AlphaWeights) -> float:
    """Compute the weighted composite alpha score Σ ∈ [0.0, 1.0].

    Σ = β_Trend·trend + β_Vol·vol + β_Liq·liq + β_Sent·sent
    """
    return (
        weights.trend * components.trend_score
        + weights.vol * components.vol_score
        + weights.liq * components.liq_score
        + weights.sent * components.sent_score
    )


def assign_strategy_id(regime: MarketRegime, trend_score: float) -> str:
    """Return the pre-market candidate strategy full-name for a given regime/score.

    Pre-market assignment rules (M11 may override intraday):
    - BULL_TREND or BEAR_TREND, trend_score ≥ threshold  → EMA_VWAP_TREND
    - BULL_TREND or BEAR_TREND, trend_score < threshold  → MOMENTUM_RSI
    - MEAN_REVERTING                                      → MEAN_REVERT_PIVOT
    - HIGH_VOL_CHAOS                                      → not reachable (empty list)

    ORB_BREAKOUT and ORDER_FLOW_ABSORPTION are intraday assignments made in M11.
    """
    if regime in (MarketRegime.BULL_TREND, MarketRegime.BEAR_TREND):
        if trend_score >= STRATEGY_TREND_SCORE_THRESHOLD:
            return "EMA_VWAP_TREND"
        return "MOMENTUM_RSI"
    # MEAN_REVERTING
    return "MEAN_REVERT_PIVOT"


def rank_entries(entries: list[WatchlistEntry]) -> list[WatchlistEntry]:
    """Return entries sorted by composite_score descending, ranks re-assigned 1-based.

    Args:
        entries: Unranked WatchlistEntry objects (rank field ignored on input).

    Returns:
        New list of WatchlistEntry objects with rank set to position (1 = best).
    """
    sorted_entries = sorted(entries, key=lambda e: e.composite_score, reverse=True)
    return [
        WatchlistEntry(
            symbol=e.symbol,
            exchange=e.exchange,
            rank=idx + 1,
            composite_score=e.composite_score,
            components=e.components,
            regime=e.regime,
            strategy_id=e.strategy_id,
            scored_at=e.scored_at,
        )
        for idx, e in enumerate(sorted_entries)
    ]
