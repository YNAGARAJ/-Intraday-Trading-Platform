"""Unit tests for shared.patterns.orb -- Opening Range Breakout detector."""

from datetime import date, datetime, timedelta, timezone

import pytest

from shared.patterns.models import ORBState
from shared.patterns.orb import detect_orb
from shared.storage.models import OHLCVCandle

_DATE = date(2024, 1, 15)
_SESSION_OPEN = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)


def _candle(
    minutes_after_open: int,
    open: float,
    high: float,
    low: float,
    close: float,
) -> OHLCVCandle:
    return OHLCVCandle(
        time=_SESSION_OPEN + timedelta(minutes=minutes_after_open),
        symbol="TEST",
        exchange="NSE",
        open=open,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


class TestDetectOrb:
    def test_empty_candles_returns_none(self) -> None:
        assert detect_orb([]) is None

    def test_returns_orb_state(self) -> None:
        candles = [_candle(0, 100, 102, 99, 101)]
        result = detect_orb(candles, opening_range_minutes=15)
        assert isinstance(result, ORBState)

    def test_single_candle_in_range_no_breakout(self) -> None:
        # Only one candle, within the ORB window → range formed, no breakout yet
        candles = [_candle(0, 100, 101, 99, 100.5)]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        assert result.range_formed is True
        assert result.orb_high == pytest.approx(101.0)
        assert result.orb_low == pytest.approx(99.0)
        assert result.breakout_direction is None

    def test_orb_high_and_low_from_multiple_range_candles(self) -> None:
        candles = [
            _candle(0, 100, 102, 99, 101),  # high=102, low=99
            _candle(5, 101, 103, 100, 102),  # high=103, low=100
            _candle(10, 102, 103, 98, 100),  # high=103, low=98
        ]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        assert result.orb_high == pytest.approx(103.0)
        assert result.orb_low == pytest.approx(98.0)
        assert result.orb_range == pytest.approx(5.0)

    def test_bullish_breakout_detected(self) -> None:
        # ORB: first two 5-min candles form range 99-103
        # Third candle (after ORB window) closes above 103 → bullish breakout
        candles = [
            _candle(0, 100, 103, 99, 101),
            _candle(5, 101, 103, 99, 101.5),
            _candle(20, 102, 106, 101, 105),  # post-ORB, close 105 > 103
        ]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        assert result.breakout_direction == 1
        assert result.breakout_price == pytest.approx(105.0)

    def test_bearish_breakout_detected(self) -> None:
        # Post-ORB candle closes below ORB low
        candles = [
            _candle(0, 100, 103, 99, 101),
            _candle(5, 101, 103, 99, 101.5),
            _candle(20, 101, 102, 97, 97.5),  # close 97.5 < orb_low 99
        ]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        assert result.breakout_direction == -1
        assert result.breakout_price == pytest.approx(97.5)

    def test_first_breakout_wins_when_multiple_post_orb(self) -> None:
        """Only the first post-ORB candle that breaks out matters."""
        candles = [
            _candle(0, 100, 103, 99, 101),
            _candle(20, 101, 106, 100, 105),  # bullish breakout first
            _candle(25, 104, 107, 96, 96.5),  # later bearish -- should be ignored
        ]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        assert result.breakout_direction == 1  # first one wins
        assert result.breakout_price == pytest.approx(105.0)

    def test_no_breakout_when_price_stays_in_range(self) -> None:
        candles = [
            _candle(0, 100, 103, 99, 101),
            _candle(5, 101, 103, 99, 101.5),
            _candle(20, 101, 102.9, 99.1, 101),  # within range
            _candle(25, 101, 102.8, 99.2, 101.5),
        ]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        assert result.breakout_direction is None
        assert result.breakout_price is None

    def test_explicit_session_open_overrides_inferred(self) -> None:
        # Session open is 09:30, but candles start at 09:15.
        # With inferred open (09:15), all candles are within the 15-min window.
        # With explicit 09:30, the 09:15 candle is PRE-range, only 09:30 candle
        # forms the range, and 09:50 is post-ORB.
        session_open = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
        candles = [
            _candle(0, 95, 99, 94, 97),  # 09:15 -- before explicit session_open
            _candle(15, 100, 103, 99, 101),  # 09:30 -- first candle in range
            _candle(20, 101, 103, 99, 101.5),  # 09:35 -- still in range
            _candle(35, 102, 106, 101, 105),  # 09:50 -- post-ORB, breakout
        ]
        result = detect_orb(
            candles, opening_range_minutes=15, session_open=session_open
        )
        assert result is not None
        assert result.range_formed is True
        assert result.orb_high == pytest.approx(103.0)
        assert result.orb_low == pytest.approx(99.0)
        assert result.breakout_direction == 1

    def test_only_last_date_candles_used(self) -> None:
        """Yesterday's candles are ignored; only today's date determines ORB."""
        yesterday_open = _SESSION_OPEN - timedelta(days=1)
        candles = [
            OHLCVCandle(
                time=yesterday_open,
                symbol="TEST",
                exchange="NSE",
                open=90,
                high=95,
                low=88,
                close=92,
                volume=1000,
            ),
            _candle(0, 100, 103, 99, 101),
        ]
        result = detect_orb(candles, opening_range_minutes=15)
        assert result is not None
        # Range must come from today's candle, not yesterday's
        assert result.orb_high == pytest.approx(103.0)
        assert result.orb_low == pytest.approx(99.0)

    def test_range_not_formed_when_no_session_candles_in_window(self) -> None:
        """If session_open is set so that all session candles fall AFTER the ORB
        cutoff, range_formed should be False."""
        # Force session open to a time AFTER all candles
        far_future_open = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
        candles = [_candle(0, 100, 103, 99, 101)]
        result = detect_orb(
            candles, opening_range_minutes=15, session_open=far_future_open
        )
        assert result is not None
        assert result.range_formed is False
