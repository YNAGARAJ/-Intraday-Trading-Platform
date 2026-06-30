"""Volume Delta: buy-side minus sell-side volume.

Not a TA-Lib function, and not a true order-flow delta either: that requires
tick-level bid/ask aggressor classification, which isn't available from OHLCV candles
(the `ticks` table has bid/ask quotes -- see shared/storage/schema.sql -- but no
trade-direction flag yet; that would need to come from the Data Ingestion Agent's
tick handling in M16). This is the standard candle-direction proxy: a bar's volume is
classified entirely as buy-side if it closed up (close >= open) and sell-side
otherwise. Revisit if M16 starts persisting true aggressor-side volume.
"""

import numpy as np

from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator


@register_indicator("VOLUME_DELTA", min_candles=1)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    signed_volume = np.where(
        candles.close >= candles.open, candles.volume, -candles.volume
    )
    return {
        "VOLUME_DELTA": float(signed_volume[-1]),
        "VOLUME_DELTA_CUMULATIVE": float(np.sum(signed_volume)),
    }
