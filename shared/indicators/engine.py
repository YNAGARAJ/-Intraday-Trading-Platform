"""Orchestrates indicator computation: take OHLCV candles, run every registered
indicator, return a combined snapshot. Pure Python + NumPy/TA-Lib -- zero LLM, hot
path (RULE 4).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import structlog

import shared.indicators.definitions as _definitions  # noqa: F401
from shared.indicators.models import (
    IndicatorOutputDict,
    IndicatorSnapshot,
    candle_arrays_from_candles,
)
from shared.indicators.registry import all_indicators
from shared.storage.models import OHLCVCandle

logger = structlog.get_logger(__name__)
# `_definitions` itself is never referenced again -- importing the package is only to
# trigger every definition file's @register_indicator side effect (see that package's
# docstring). The noqa suppresses the otherwise-correct unused-import warning.


def compute_all(candles: Sequence[OHLCVCandle]) -> dict[str, IndicatorOutputDict]:
    """Run every registered indicator over `candles` (oldest first).

    Indicators whose `min_candles` requirement isn't met by `len(candles)` are
    skipped (returned as an empty dict for that name) rather than called with
    insufficient data -- this is the single place that guarantee is enforced, so
    individual definition files can assume they're only ever called with enough data.
    """
    arrays = candle_arrays_from_candles(candles)
    results: dict[str, IndicatorOutputDict] = {}
    for name, spec in all_indicators().items():
        if len(arrays) < spec.min_candles:
            logger.debug(
                "indicator_skipped_insufficient_data",
                indicator=name,
                have=len(arrays),
                need=spec.min_candles,
            )
            results[name] = {}
            continue
        results[name] = spec.compute(arrays)
    return results


def compute_snapshot(
    symbol: str, exchange: str, timeframe: str, candles: Sequence[OHLCVCandle]
) -> IndicatorSnapshot:
    """`compute_all` plus the symbol/timeframe/timing metadata needed to cache and
    later identify a result -- see `shared.indicators.cache`."""
    values = compute_all(candles)
    candle_time = candles[-1].time if candles else datetime.now(UTC)
    return IndicatorSnapshot(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        candle_time=candle_time,
        computed_at=datetime.now(UTC),
        values=values,
    )
