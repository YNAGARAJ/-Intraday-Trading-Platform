"""Pivot points: Standard, Fibonacci, and Camarilla -- all derived from the prior
bar's high/low/close. Not TA-Lib functions; standard textbook formulas.

"Prior bar" here means the candle immediately before the most recent one in whatever
timeframe was requested (e.g. the prior daily bar for a 1h chart, the prior 5m bar for
a 5m chart) -- pivot points are timeframe-relative by nature, and the spec's
multi-timeframe requirement (M04) is satisfied by computing on whichever timeframe's
candles the caller passed in, the same as every other indicator in this engine.
"""

from shared.core.constants import CAMARILLA_RANGE_MULTIPLIER
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator


@register_indicator("PIVOT_POINTS", min_candles=2)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    high = float(candles.high[-2])
    low = float(candles.low[-2])
    close = float(candles.close[-2])
    pivot_range = high - low

    pivot = (high + low + close) / 3.0

    return {
        "PIVOT": pivot,
        # Standard
        "PIVOT_R1": 2 * pivot - low,
        "PIVOT_S1": 2 * pivot - high,
        "PIVOT_R2": pivot + pivot_range,
        "PIVOT_S2": pivot - pivot_range,
        "PIVOT_R3": high + 2 * (pivot - low),
        "PIVOT_S3": low - 2 * (high - pivot),
        # Fibonacci
        "PIVOT_FIB_R1": pivot + 0.382 * pivot_range,
        "PIVOT_FIB_S1": pivot - 0.382 * pivot_range,
        "PIVOT_FIB_R2": pivot + 0.618 * pivot_range,
        "PIVOT_FIB_S2": pivot - 0.618 * pivot_range,
        "PIVOT_FIB_R3": pivot + 1.0 * pivot_range,
        "PIVOT_FIB_S3": pivot - 1.0 * pivot_range,
        # Camarilla
        "PIVOT_CAM_R1": close + pivot_range * CAMARILLA_RANGE_MULTIPLIER / 12,
        "PIVOT_CAM_S1": close - pivot_range * CAMARILLA_RANGE_MULTIPLIER / 12,
        "PIVOT_CAM_R2": close + pivot_range * CAMARILLA_RANGE_MULTIPLIER / 6,
        "PIVOT_CAM_S2": close - pivot_range * CAMARILLA_RANGE_MULTIPLIER / 6,
        "PIVOT_CAM_R3": close + pivot_range * CAMARILLA_RANGE_MULTIPLIER / 4,
        "PIVOT_CAM_S3": close - pivot_range * CAMARILLA_RANGE_MULTIPLIER / 4,
        "PIVOT_CAM_R4": close + pivot_range * CAMARILLA_RANGE_MULTIPLIER / 2,
        "PIVOT_CAM_S4": close - pivot_range * CAMARILLA_RANGE_MULTIPLIER / 2,
    }
