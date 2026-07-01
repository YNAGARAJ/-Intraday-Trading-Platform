"""M09 universe filter: orchestrates scoring, compliance, ranking, and top-N cut.

Entry point: ``run_universe_filter()``.

RULE 2 enforcement: if regime is HIGH_VOL_CHAOS, returns an empty list immediately.
No scoring, no database writes — an empty watchlist is the correct output.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt
import structlog

from shared.core.constants import WATCHLIST_MIN_CANDLES, WATCHLIST_TOP_N
from shared.regime.models import MarketRegime
from shared.universe.compliance import ComplianceExclusionList
from shared.universe.models import WatchlistEntry
from shared.universe.scoring import (
    BETA_WEIGHTS,
    assign_strategy_id,
    compute_composite,
    rank_entries,
    score_stock,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Type alias for a candle dict with OHLCV numpy arrays
CandleArrays = dict[str, npt.NDArray[np.float64]]


def run_universe_filter(
    instruments: list[dict[str, str]],
    candles_by_symbol: dict[str, CandleArrays],
    regime: MarketRegime,
    exclusion_list: ComplianceExclusionList,
    top_n: int = WATCHLIST_TOP_N,
) -> list[WatchlistEntry]:
    """Score, rank, and return the top-N watchlist entries for the current session.

    RULE 2: Returns an empty list immediately when regime is HIGH_VOL_CHAOS.
    Compliance exclusions are applied before scoring.

    Args:
        instruments:       List of instrument dicts with at least ``symbol`` and
                           ``exchange`` keys.
        candles_by_symbol: Map from symbol → dict with keys ``close``, ``high``,
                           ``low``, ``volume`` as 1-D float64 numpy arrays
                           (oldest bar first).
        regime:            Current market regime from M08.
        exclusion_list:    SEBI/NSE compliance exclusion data from M09 compliance
                           fetcher.
        top_n:             Maximum watchlist size (default WATCHLIST_TOP_N = 20).

    Returns:
        Ranked list of WatchlistEntry, length ≤ top_n.  Empty list when regime
        is HIGH_VOL_CHAOS or when no instrument clears scoring/compliance.
    """
    # RULE 2 — hard refusal, not a warning
    if regime == MarketRegime.HIGH_VOL_CHAOS:
        logger.warning(
            "universe_filter_skipped_high_vol_chaos",
            regime=regime.value,
        )
        return []

    weights = BETA_WEIGHTS[regime]
    scored_at = datetime.now(tz=timezone.utc)
    unranked: list[WatchlistEntry] = []

    for instrument in instruments:
        symbol: str = instrument["symbol"]
        exchange: str = instrument["exchange"]

        if exclusion_list.is_excluded(symbol):
            reason = exclusion_list.exclusion_reason(symbol)
            logger.debug(
                "universe_filter_excluded",
                symbol=symbol,
                reason=reason,
            )
            continue

        candles = candles_by_symbol.get(symbol)
        if candles is None:
            logger.debug("universe_filter_no_candles", symbol=symbol)
            continue

        close = candles.get("close", np.empty(0))
        high = candles.get("high", np.empty(0))
        low = candles.get("low", np.empty(0))
        volume = candles.get("volume", np.empty(0))

        if len(close) < WATCHLIST_MIN_CANDLES:
            logger.debug(
                "universe_filter_insufficient_candles",
                symbol=symbol,
                bars=len(close),
                required=WATCHLIST_MIN_CANDLES,
            )
            continue

        components = score_stock(close, high, low, volume, regime)
        composite = compute_composite(components, weights)
        strategy_id = assign_strategy_id(regime, components.trend_score)

        unranked.append(
            WatchlistEntry(
                symbol=symbol,
                exchange=exchange,
                rank=0,  # assigned by rank_entries()
                composite_score=composite,
                components=components,
                regime=regime,
                strategy_id=strategy_id,
                scored_at=scored_at,
            )
        )

    ranked = rank_entries(unranked)[:top_n]
    logger.info(
        "universe_filter_complete",
        regime=regime.value,
        total_scored=len(unranked),
        watchlist_size=len(ranked),
    )
    return ranked
