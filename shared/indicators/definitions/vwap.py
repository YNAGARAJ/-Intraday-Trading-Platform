"""Volume-Weighted Average Price, reset each session.

Not a TA-Lib function -- computed directly from typical price (H+L+C)/3 weighted by
volume, cumulative within the current session only.

Session boundary simplification: bars are grouped by the UTC calendar date of their
candle timestamp rather than by exchange-local session open/close (which would need
this module to depend on `shared.session_manager`'s region config). Both NSE
(09:15-15:30 IST = 03:45-10:00 UTC) and ASX (10:00-16:00 AEST = 00:00-06:00 UTC)
trading sessions fall entirely within a single UTC calendar day, so this is exact for
both regions today; revisit if a region with a midnight-UTC-spanning session is added.
"""

from datetime import date as date_type
from typing import cast

import numpy as np
from numpy.typing import NDArray

from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator


def current_session_mask(candles: CandleArrays) -> NDArray[np.bool_]:
    """Boolean mask selecting bars that share the most recent bar's UTC date."""
    # dtype=object: datetime.date has no native numpy dtype, so numpy can't infer an
    # element type for the comparison below -- cast() makes the real bool[] type
    # explicit to mypy rather than letting it widen to Any (no-any-return).
    session_dates: NDArray[np.object_] = np.array([t.date() for t in candles.time])
    last_date: date_type = session_dates[-1]
    return cast(NDArray[np.bool_], session_dates == last_date)


def session_vwap_series(candles: CandleArrays) -> NDArray[np.float64]:
    """Cumulative VWAP at every bar within the current session (not just the last).

    Used by this module's own `compute` (which takes the final value) and by
    `vwap_bands.py` (which needs the whole series to measure dispersion around it).
    Returns an empty array if there's no volume in the current session yet.
    """
    mask = current_session_mask(candles)
    typical_price = (candles.high[mask] + candles.low[mask] + candles.close[mask]) / 3.0
    volume = candles.volume[mask]
    cumulative_vol = np.cumsum(volume)
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.cumsum(typical_price * volume) / cumulative_vol
    return np.where(cumulative_vol > 0, vwap, np.nan)


@register_indicator("VWAP", min_candles=1)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    series = session_vwap_series(candles)
    if series.size == 0 or np.isnan(series[-1]):
        return {"VWAP": None}
    return {"VWAP": float(series[-1])}
