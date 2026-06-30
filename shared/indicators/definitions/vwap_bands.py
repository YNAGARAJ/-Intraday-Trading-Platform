"""VWAP bands: session VWAP +/- N standard deviations of price dispersion around it.

Not a TA-Lib function. Reuses `vwap.session_vwap_series` rather than recomputing VWAP
independently.
"""

import numpy as np

from shared.core.constants import VWAP_BAND_STDDEV_MULTIPLIER
from shared.indicators.definitions.vwap import current_session_mask, session_vwap_series
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator


@register_indicator("VWAP_BANDS", min_candles=2)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    series = session_vwap_series(candles)
    if series.size == 0 or np.isnan(series[-1]):
        return {"VWAP_BAND_UPPER": None, "VWAP_BAND_LOWER": None}

    mask = current_session_mask(candles)
    typical_price = (candles.high[mask] + candles.low[mask] + candles.close[mask]) / 3.0
    deviation = np.nanstd(typical_price - series)
    vwap = float(series[-1])
    return {
        "VWAP_BAND_UPPER": vwap + VWAP_BAND_STDDEV_MULTIPLIER * float(deviation),
        "VWAP_BAND_LOWER": vwap - VWAP_BAND_STDDEV_MULTIPLIER * float(deviation),
    }
