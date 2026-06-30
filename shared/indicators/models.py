"""Data shapes for the indicator engine: the vectorized input every indicator
computes from, and the snapshot of results produced for one symbol/timeframe."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from shared.storage.models import OHLCVCandle


@dataclass(frozen=True)
class CandleArrays:
    """OHLCV candles as parallel NumPy arrays, oldest first -- the shape every
    TA-Lib/NumPy indicator function in `shared/indicators/definitions/` expects.

    Built once per `compute_all` call via `candle_arrays_from_candles` rather than
    making each indicator convert the candle list itself.
    """

    time: list[datetime]
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    volume: NDArray[np.float64]

    def __len__(self) -> int:
        return len(self.time)


def candle_arrays_from_candles(candles: Sequence[OHLCVCandle]) -> CandleArrays:
    """Convert time-ordered `OHLCVCandle` rows (as returned by
    `OHLCVRepository.query_candles`) into the parallel-array shape indicators need.

    Callers are responsible for passing candles already sorted oldest-first --
    `query_candles` already does this, so no re-sorting happens here.
    """
    return CandleArrays(
        time=[c.time for c in candles],
        open=np.array([c.open for c in candles], dtype=np.float64),
        high=np.array([c.high for c in candles], dtype=np.float64),
        low=np.array([c.low for c in candles], dtype=np.float64),
        close=np.array([c.close for c in candles], dtype=np.float64),
        volume=np.array([c.volume for c in candles], dtype=np.float64),
    )


IndicatorOutputDict = dict[str, float | None]
"""One indicator's computed result: one or more named values (e.g. EMA produces
EMA_9/EMA_21/EMA_50/EMA_200; RSI produces a single RSI_14). `None` means the value
isn't yet computable (e.g. an early bar before a moving average has warmed up)."""


@dataclass(frozen=True)
class IndicatorSnapshot:
    """The full set of computed indicator values for one symbol/exchange/timeframe
    at one point in time -- what gets cached in Redis and returned by the engine."""

    symbol: str
    exchange: str
    timeframe: str
    candle_time: datetime
    """Time of the most recent candle used in the computation (not wall-clock time)."""
    computed_at: datetime
    """Wall-clock time the computation ran -- used to judge cache freshness."""
    values: dict[str, IndicatorOutputDict]
