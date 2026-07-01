"""Full TA-Lib candlestick pattern scan.

Enumerates every CDL* function present in the installed TA-Lib version and runs each
one over the provided candle arrays. TA-Lib returns +100 (bullish), -100 (bearish), or
0 (no pattern); some functions return ±200 -- normalised to ±100 here so callers only
see a signed direction, not a magnitude.

Adding future TA-Lib CDL functions requires no code change here -- new CDL* names are
discovered at import time via `dir(talib)` (see ADR-011).
"""

from collections.abc import Sequence

import numpy as np
import talib
from numpy.typing import NDArray

from shared.core.constants import CDL_MIN_CANDLES
from shared.core.logging import get_logger
from shared.indicators.models import CandleArrays, candle_arrays_from_candles
from shared.patterns.models import CandlestickSignal
from shared.storage.models import OHLCVCandle

logger = get_logger(__name__)

_CDL_NAMES: list[str] = sorted(name for name in dir(talib) if name.startswith("CDL"))
"""All CDL* function names exported by the installed TA-Lib version, sorted for
deterministic output ordering. Discovered once at import time."""


def detect_all(arrays: CandleArrays) -> list[CandlestickSignal]:
    """Scan every available TA-Lib candlestick pattern over `arrays`.

    Each CDL* function is called with the full open/high/low/close arrays; only bars
    where the result is non-zero are returned. The resulting list is sorted by
    `bar_index` ascending (oldest first) so callers can trivially select only recent
    signals (e.g. `[s for s in signals if s.bar_index >= len(arrays) - 3]`).

    Returns an empty list when `len(arrays) < CDL_MIN_CANDLES` or no patterns fire.

    Args:
        arrays: Pre-built parallel NumPy arrays from `candle_arrays_from_candles`.

    Returns:
        All non-zero pattern detections, sorted oldest-bar first.
    """
    if len(arrays) < CDL_MIN_CANDLES:
        logger.debug(
            "candlestick_scan_skipped_insufficient_data",
            have=len(arrays),
            need=CDL_MIN_CANDLES,
        )
        return []

    o: NDArray[np.float64] = arrays.open
    h: NDArray[np.float64] = arrays.high
    lo: NDArray[np.float64] = arrays.low
    c: NDArray[np.float64] = arrays.close

    signals: list[CandlestickSignal] = []

    for name in _CDL_NAMES:
        fn = getattr(talib, name)
        try:
            result: NDArray[np.int32] = fn(o, h, lo, c)
        except Exception as exc:  # TA-Lib raises on malformed arrays in rare edge cases
            logger.warning("candlestick_function_error", pattern=name, error=str(exc))
            continue
        for i, val in enumerate(result):
            if val != 0:
                direction = 100 if val > 0 else -100
                signals.append(
                    CandlestickSignal(name=name, direction=direction, bar_index=i)
                )

    signals.sort(key=lambda s: s.bar_index)
    return signals


def detect_recent(
    candles: Sequence[OHLCVCandle], lookback_bars: int = 3
) -> list[CandlestickSignal]:
    """Convenience wrapper: detect all patterns and return only signals on the last
    `lookback_bars` bars of the series.

    This is the entry point M11's Gate 4 will use: it only needs to know whether the
    most recent candle(s) show a pattern that confirms the signal direction.

    Args:
        candles: OHLCV candle list (oldest first).
        lookback_bars: How many trailing bars to include in the result.

    Returns:
        Candlestick signals from the last `lookback_bars` bars, oldest first.
    """
    arrays = candle_arrays_from_candles(candles)
    all_signals = detect_all(arrays)
    cutoff = len(arrays) - lookback_bars
    return [s for s in all_signals if s.bar_index >= cutoff]
