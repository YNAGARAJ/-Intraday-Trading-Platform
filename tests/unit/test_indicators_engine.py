"""Unit tests for shared.indicators.engine -- exercises the real, built-in registry
(importing the module registers every shared/indicators/definitions/ file), entirely
offline against synthetic candles.
"""

from datetime import UTC, datetime, timedelta

from shared.core.constants import EMA_PERIODS
from shared.indicators.engine import compute_all, compute_snapshot
from shared.storage.models import OHLCVCandle

SYMBOL = "RELIANCE.NS"
EXCHANGE = "NSE"
T0 = datetime(2026, 6, 1, 3, 45, tzinfo=UTC)

ALL_INDICATOR_NAMES = {
    "ADX",
    "ATR",
    "BBANDS",
    "CCI",
    "EMA",
    "MACD",
    "MFI",
    "OBV",
    "PIVOT_POINTS",
    "ROC",
    "RSI",
    "STOCHASTIC",
    "VOLUME_DELTA",
    "VWAP",
    "VWAP_BANDS",
    "WILLR",
}


def _synthetic_candles(count: int) -> list[OHLCVCandle]:
    """Deterministic, gently-trending synthetic candles -- enough variation that
    oscillators don't degenerate to a constant, but no randomness (reproducible).
    """
    candles = []
    price = 100.0
    for i in range(count):
        wiggle = 0.5 if i % 2 == 0 else -0.3
        open_ = price
        close = price + wiggle
        high = max(open_, close) + 0.2
        low = min(open_, close) - 0.2
        volume = 100 + (i % 10) * 10
        candles.append(
            OHLCVCandle(
                time=T0 + timedelta(minutes=5 * i),
                symbol=SYMBOL,
                exchange=EXCHANGE,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
        price = close
    return candles


class TestComputeAll:
    def test_returns_every_registered_indicator_name(self) -> None:
        results = compute_all(_synthetic_candles(250))

        assert set(results) >= ALL_INDICATOR_NAMES

    def test_sufficient_history_yields_real_values_not_none(self) -> None:
        results = compute_all(_synthetic_candles(250))

        for period in EMA_PERIODS:
            assert results["EMA"][f"EMA_{period}"] is not None
        assert results["RSI"]["RSI_14"] is not None
        assert results["VWAP"]["VWAP"] is not None

    def test_empty_candles_skips_every_indicator(self) -> None:
        results = compute_all([])

        assert set(results) >= ALL_INDICATOR_NAMES
        assert all(results[name] == {} for name in ALL_INDICATOR_NAMES)

    def test_single_candle_only_runs_min_candles_one_indicators(self) -> None:
        results = compute_all(_synthetic_candles(1))

        # VWAP and VOLUME_DELTA both declare min_candles=1 -- they should run.
        assert results["VWAP"] != {}
        assert results["VOLUME_DELTA"] != {}
        # Everything requiring 2+ candles (e.g. OBV, PIVOT_POINTS, VWAP_BANDS) or
        # TA-Lib's longer lookback periods should be skipped, not crash.
        assert results["PIVOT_POINTS"] == {}
        assert results["OBV"] == {}
        assert results["RSI"] == {}


class TestComputeSnapshot:
    def test_snapshot_metadata_matches_inputs(self) -> None:
        candles = _synthetic_candles(50)

        snapshot = compute_snapshot(SYMBOL, EXCHANGE, "5m", candles)

        assert snapshot.symbol == SYMBOL
        assert snapshot.exchange == EXCHANGE
        assert snapshot.timeframe == "5m"
        assert snapshot.candle_time == candles[-1].time
        assert set(snapshot.values) >= ALL_INDICATOR_NAMES
