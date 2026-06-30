"""Importing this package registers every built-in indicator as a side effect.

To add a new indicator: create one file here that calls `@register_indicator(...)`
on a compute function, then add one import line below. Nothing else in the codebase
needs to change -- `shared.indicators.engine` discovers indicators purely through the
registry, not through this import list's contents.
"""

from shared.indicators.definitions import (
    adx,
    atr,
    bollinger_bands,
    cci,
    ema,
    macd,
    mfi,
    obv,
    pivot_points,
    roc,
    rsi,
    stochastic,
    volume_delta,
    vwap,
    vwap_bands,
    williams_r,
)

__all__ = [
    "adx",
    "atr",
    "bollinger_bands",
    "cci",
    "ema",
    "macd",
    "mfi",
    "obv",
    "pivot_points",
    "roc",
    "rsi",
    "stochastic",
    "volume_delta",
    "vwap",
    "vwap_bands",
    "williams_r",
]
