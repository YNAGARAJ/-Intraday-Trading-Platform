"""Money Flow Index: MFI(14) -- volume-weighted RSI."""

import talib

from shared.core.constants import MFI_PERIOD
from shared.indicators.models import CandleArrays, IndicatorOutputDict
from shared.indicators.registry import register_indicator
from shared.indicators.utils import last_value


@register_indicator("MFI", min_candles=MFI_PERIOD)
def compute(candles: CandleArrays) -> IndicatorOutputDict:
    mfi = talib.MFI(
        candles.high, candles.low, candles.close, candles.volume, timeperiod=MFI_PERIOD
    )
    return {f"MFI_{MFI_PERIOD}": last_value(mfi)}
