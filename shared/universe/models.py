"""M09 data models for the stock universe filter and alpha scoring output.

All models are frozen dataclasses (immutable after construction) so they can be
safely passed between pipeline stages without defensive copying.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shared.regime.models import MarketRegime


@dataclass(frozen=True)
class AlphaWeights:
    """Regime-specific β coefficients for the alpha scoring formula.

    The four weights must sum to 1.0.  The ``sent`` slot is reserved for M10's
    sentiment feed; it is always 0.10 in M09 (and SentScore is always 0.0).

    Σ = trend * trend_score + vol * vol_score + liq * liq_score + sent * sent_score
    """

    trend: float
    vol: float
    liq: float
    sent: float


@dataclass(frozen=True)
class AlphaComponents:
    """Per-component alpha scores for a single instrument, all in [0.0, 1.0].

    Args:
        trend_score: EMA-direction × normalised ADX strength.
        vol_score:   Normalised Bollinger Band width.
        liq_score:   Normalised recent-volume / average-volume ratio.
        sent_score:  Sentiment score from M10 feed (0.0 until M10 is built).
    """

    trend_score: float
    vol_score: float
    liq_score: float
    sent_score: float


@dataclass(frozen=True)
class WatchlistEntry:
    """A single ranked entry in the daily pre-market watchlist.

    Args:
        symbol:          Instrument ticker (e.g. ``"RELIANCE"`` or ``"BHP"``).
        exchange:        Exchange code (``"NSE"`` or ``"ASX"``).
        rank:            1-based rank within the watchlist (1 = highest score).
        composite_score: Weighted alpha composite Σ ∈ [0.0, 1.0].
        components:      Individual score components before weighting.
        regime:          Market regime active when this entry was scored.
        strategy_id:     Pre-assigned candidate strategy (full name, not compressed
                         tag — M13 compresses it for the broker).
        scored_at:       UTC timestamp when the score was computed.
    """

    symbol: str
    exchange: str
    rank: int
    composite_score: float
    components: AlphaComponents
    regime: MarketRegime
    strategy_id: str
    scored_at: datetime
