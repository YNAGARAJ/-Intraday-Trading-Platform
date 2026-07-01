"""Unit tests for shared.patterns.candlestick -- TA-Lib CDL scanner."""

from datetime import datetime, timezone

from shared.indicators.models import candle_arrays_from_candles
from shared.patterns.candlestick import _CDL_NAMES, detect_all, detect_recent
from shared.patterns.models import CandlestickSignal
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)


def _make_candle(
    i: int,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: int = 1000,
) -> OHLCVCandle:
    from datetime import timedelta

    return OHLCVCandle(
        time=_T0 + timedelta(minutes=5 * i),
        symbol="TEST",
        exchange="NSE",
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _flat_candles(n: int, price: float = 100.0) -> list[OHLCVCandle]:
    """All-doji candles: open == close, equal highs/lows -- many CDLs fire on these."""
    return [_make_candle(i, price, price + 1.0, price - 1.0, price) for i in range(n)]


class TestCDLNames:
    def test_registry_is_non_empty(self) -> None:
        assert len(_CDL_NAMES) >= 10

    def test_all_names_start_with_cdl(self) -> None:
        assert all(name.startswith("CDL") for name in _CDL_NAMES)

    def test_known_patterns_present(self) -> None:
        # A sampling of well-known TA-Lib CDL functions that must be present
        for expected in ("CDLDOJI", "CDLHAMMER", "CDLENGULFING"):
            assert expected in _CDL_NAMES


class TestDetectAll:
    def test_too_few_candles_returns_empty(self) -> None:
        candles = _flat_candles(3)
        arrays = candle_arrays_from_candles(candles)
        assert detect_all(arrays) == []

    def test_returns_list_of_candlestick_signals(self) -> None:
        candles = _flat_candles(20)
        arrays = candle_arrays_from_candles(candles)
        result = detect_all(arrays)
        assert isinstance(result, list)
        for sig in result:
            assert isinstance(sig, CandlestickSignal)

    def test_direction_is_plus_or_minus_100(self) -> None:
        candles = _flat_candles(30)
        arrays = candle_arrays_from_candles(candles)
        for sig in detect_all(arrays):
            assert sig.direction in (-100, 100)

    def test_bar_index_within_bounds(self) -> None:
        candles = _flat_candles(30)
        arrays = candle_arrays_from_candles(candles)
        n = len(candles)
        for sig in detect_all(arrays):
            assert 0 <= sig.bar_index < n

    def test_sorted_by_bar_index_ascending(self) -> None:
        candles = _flat_candles(40)
        arrays = candle_arrays_from_candles(candles)
        result = detect_all(arrays)
        bar_indices = [s.bar_index for s in result]
        assert bar_indices == sorted(bar_indices)

    def test_flat_candles_detect_doji_class(self) -> None:
        """Open==close candles with shadows → at least CDLDOJI should fire."""
        candles = _flat_candles(20)
        arrays = candle_arrays_from_candles(candles)
        result = detect_all(arrays)
        names = {s.name for s in result}
        # CDLDOJI is the canonical flat-body pattern -- must appear somewhere
        assert "CDLDOJI" in names

    def test_bullish_engulfing_detected(self) -> None:
        """Construct a classic bullish engulfing setup and assert it's detected.

        Prior bars establish a slight downtrend, then:
          bar N-1: bearish (open > close)
          bar N  : bullish engulfing (body completely covers bar N-1 body)
        """
        # 15 gently declining bars to warm up TA-Lib averages
        candles: list[OHLCVCandle] = []
        for i in range(15):
            p = 110.0 - i * 0.5
            candles.append(_make_candle(i, p, p + 0.3, p - 0.5, p - 0.2))

        # Bearish candle (bar 15)
        candles.append(_make_candle(15, open=102.0, high=103.0, low=99.5, close=100.0))
        # Bullish engulfing (bar 16): opens below bar 15 close, closes above bar 15 open
        candles.append(_make_candle(16, open=99.0, high=104.5, low=98.5, close=103.5))

        arrays = candle_arrays_from_candles(candles)
        result = detect_all(arrays)
        engulfing = [
            s for s in result if s.name == "CDLENGULFING" and s.bar_index == 16
        ]
        assert engulfing, (
            "CDLENGULFING should fire bullish on bar 16; "
            f"detected signals at last bar: {[s for s in result if s.bar_index >= 15]}"
        )
        assert engulfing[0].direction == 100


class TestDetectRecent:
    def test_returns_only_last_n_bars(self) -> None:
        candles = _flat_candles(40)
        result = detect_recent(candles, lookback_bars=5)
        n = len(candles)
        for sig in result:
            assert sig.bar_index >= n - 5

    def test_default_lookback_is_3(self) -> None:
        candles = _flat_candles(30)
        result = detect_recent(candles)
        n = len(candles)
        for sig in result:
            assert sig.bar_index >= n - 3

    def test_too_few_candles_returns_empty(self) -> None:
        candles = _flat_candles(3)
        assert detect_recent(candles) == []
