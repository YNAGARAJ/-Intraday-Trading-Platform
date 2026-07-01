"""Orchestrates pattern computation: candlestick scan + ORB + S/R, optionally across
multiple timeframes. Pure Python + NumPy/TA-Lib -- zero LLM (RULE 4).

The two public entry points:
  - `compute_snapshot`: one symbol/timeframe → `PatternSnapshot`
  - `compute_multi_timeframe`: dict of {timeframe: candles} → `MultiTimeframePatterns`
    with cross-timeframe pattern confirmation (Gate 5 of the 9-gate signal system).
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import structlog

from shared.core.constants import (
    GATE_5_MIN_TIMEFRAMES_AGREEING,
    ORB_OPENING_RANGE_MINUTES,
    SR_LOOKBACK_CANDLES,
)
from shared.indicators.models import candle_arrays_from_candles
from shared.patterns.candlestick import detect_all
from shared.patterns.models import (
    MultiTimeframePatterns,
    PatternSnapshot,
)
from shared.patterns.orb import detect_orb
from shared.patterns.support_resistance import detect_sr_levels
from shared.storage.models import OHLCVCandle

logger = structlog.get_logger(__name__)


def compute_snapshot(
    symbol: str,
    exchange: str,
    timeframe: str,
    candles: Sequence[OHLCVCandle],
    opening_range_minutes: int = ORB_OPENING_RANGE_MINUTES,
    session_open: datetime | None = None,
    sr_lookback_candles: int = SR_LOOKBACK_CANDLES,
) -> PatternSnapshot:
    """Compute all patterns for one symbol/exchange/timeframe.

    Args:
        symbol: Instrument symbol (e.g. 'RELIANCE').
        exchange: Exchange code ('NSE' or 'ASX').
        timeframe: Bar timeframe string ('1m', '5m', '15m', '1h').
        candles: OHLCV candles, oldest first. May be empty -- all detectors degrade
            gracefully and return empty/None results rather than raising.
        opening_range_minutes: ORB window length in minutes.
        session_open: Explicit session-open timestamp for ORB calculation. When None,
            inferred from the earliest candle on the last candle's date.
        sr_lookback_candles: Cap on how many trailing candles are used for S/R
            computation. Computing S/R over very long series is O(n) but limiting to
            ~100 bars focuses on recent structure without missing meaningful levels.

    Returns:
        A `PatternSnapshot` containing candlestick signals, ORB state, and S/R levels.
    """
    computed_at = datetime.now(UTC)
    candle_time = candles[-1].time if candles else computed_at

    arrays = candle_arrays_from_candles(candles)
    cdl_signals = detect_all(arrays)

    orb_state = detect_orb(
        candles,
        opening_range_minutes=opening_range_minutes,
        session_open=session_open,
    )

    sr_window = (
        list(candles[-sr_lookback_candles:])
        if len(candles) > sr_lookback_candles
        else list(candles)
    )
    sr_levels = detect_sr_levels(sr_window)

    logger.debug(
        "pattern_snapshot_computed",
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        candle_count=len(candles),
        cdl_signals=len(cdl_signals),
        sr_levels=len(sr_levels),
        orb_formed=orb_state.range_formed if orb_state is not None else False,
    )

    return PatternSnapshot(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        computed_at=computed_at,
        candle_time=candle_time,
        candlestick_signals=cdl_signals,
        orb_state=orb_state,
        sr_levels=sr_levels,
    )


def compute_multi_timeframe(
    symbol: str,
    exchange: str,
    timeframe_candles: Mapping[str, Sequence[OHLCVCandle]],
    opening_range_minutes: int = ORB_OPENING_RANGE_MINUTES,
    session_open: datetime | None = None,
    sr_lookback_candles: int = SR_LOOKBACK_CANDLES,
) -> MultiTimeframePatterns:
    """Compute patterns across multiple timeframes and identify cross-TF confirmations.

    Cross-timeframe confirmation (Gate 5 of the 9-gate signal system): a candlestick
    pattern name is added to `confirmed_bullish_patterns` when it appears with bullish
    direction on ≥ `GATE_5_MIN_TIMEFRAMES_AGREEING` distinct timeframes; same logic
    for bearish. ORB and S/R are computed per-timeframe but not cross-TF aggregated --
    those are naturally single-timeframe concepts.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code.
        timeframe_candles: Mapping of timeframe → candle list. E.g.
            {'5m': [...], '15m': [...], '1h': [...]}.
        opening_range_minutes: Forwarded to each `compute_snapshot` call.
        session_open: Forwarded to each `compute_snapshot` call.
        sr_lookback_candles: Forwarded to each `compute_snapshot` call.

    Returns:
        `MultiTimeframePatterns` with per-TF snapshots and cross-TF confirmations.
    """
    computed_at = datetime.now(UTC)

    snapshots: dict[str, PatternSnapshot] = {}
    for tf, candles in timeframe_candles.items():
        snapshots[tf] = compute_snapshot(
            symbol=symbol,
            exchange=exchange,
            timeframe=tf,
            candles=candles,
            opening_range_minutes=opening_range_minutes,
            session_open=session_open,
            sr_lookback_candles=sr_lookback_candles,
        )

    # Collect per-timeframe bullish/bearish pattern name sets
    bullish_by_tf: dict[str, set[str]] = {
        tf: {s.name for s in snap.candlestick_signals if s.direction > 0}
        for tf, snap in snapshots.items()
    }
    bearish_by_tf: dict[str, set[str]] = {
        tf: {s.name for s in snap.candlestick_signals if s.direction < 0}
        for tf, snap in snapshots.items()
    }

    # Count how many timeframes show each pattern name in each direction
    bullish_counts: Counter[str] = Counter()
    bearish_counts: Counter[str] = Counter()
    for tf_names in bullish_by_tf.values():
        bullish_counts.update(tf_names)
    for tf_names in bearish_by_tf.values():
        bearish_counts.update(tf_names)

    min_tfs = min(GATE_5_MIN_TIMEFRAMES_AGREEING, len(snapshots))
    confirmed_bullish = sorted(
        name for name, cnt in bullish_counts.items() if cnt >= min_tfs
    )
    confirmed_bearish = sorted(
        name for name, cnt in bearish_counts.items() if cnt >= min_tfs
    )

    logger.debug(
        "multi_timeframe_patterns_computed",
        symbol=symbol,
        exchange=exchange,
        timeframes=list(snapshots),
        confirmed_bullish=confirmed_bullish,
        confirmed_bearish=confirmed_bearish,
    )

    return MultiTimeframePatterns(
        symbol=symbol,
        exchange=exchange,
        computed_at=computed_at,
        snapshots=snapshots,
        confirmed_bullish_patterns=confirmed_bullish,
        confirmed_bearish_patterns=confirmed_bearish,
    )
