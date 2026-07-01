"""The M06 VERIFY command, against real TimescaleDB:

    detect patterns in historical data → match known dates.

Three deterministic sub-verifications using synthetic OHLCV data:

1. **ORB VERIFY**: Inject 5 candles where the first two (within a 10-min window)
   form a range of 99–103, then a post-ORB candle closes at 106 → confirm
   `breakout_direction == 1` at that price.

2. **S/R VERIFY**: Inject 30 candles that revisit low=95.0 exactly three times →
   confirm a SUPPORT level near 95.0 with `touches >= 3`.

3. **Candlestick VERIFY**: Inject 20 declining candles followed by a bearish and then
   a bullish-engulfing candle at bar index 21 → confirm `CDLENGULFING` detected
   bullish at bar 21.

All three use only the storage layer (OHLCVRepository.upsert_1m / query_candles) and
the pattern engine. No live network access is needed; the results are deterministic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.indicators.models import candle_arrays_from_candles
from shared.patterns.candlestick import detect_all
from shared.patterns.engine import compute_snapshot
from shared.patterns.orb import detect_orb
from shared.patterns.support_resistance import detect_sr_levels
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

SYMBOL = "TESTPAT"
EXCHANGE = "NSE"

# Fixed session open: 2024-01-15 09:15 UTC (NSE open)
_SESSION_OPEN = datetime(2024, 1, 15, 9, 15, tzinfo=UTC)


def _candle(
    minutes_offset: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int = 5000,
) -> OHLCVCandle:
    return OHLCVCandle(
        time=_SESSION_OPEN + timedelta(minutes=minutes_offset),
        symbol=SYMBOL,
        exchange=EXCHANGE,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


class TestORBVerify:
    def test_orb_range_and_bullish_breakout(self, pg_connection: PGConnection) -> None:
        """M06 VERIFY (ORB): first 10 minutes form range 99–103; post-ORB close at
        106 → bullish breakout detected with correct orb_high/low."""
        repo = OHLCVRepository(pg_connection)
        candles = [
            # ORB candles (t+0 and t+5, within 10-min window)
            _candle(0, 100.0, 103.0, 99.0, 101.0),
            _candle(5, 101.0, 103.0, 99.5, 100.5),
            # Post-ORB candles
            _candle(15, 101.0, 107.0, 100.5, 106.0),  # close 106 > orb_high 103
            _candle(20, 105.0, 108.0, 104.0, 107.0),
        ]
        repo.upsert_1m(candles)

        stored = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            _SESSION_OPEN,
            _SESSION_OPEN + timedelta(minutes=30),
        )
        assert len(stored) == 4

        # Run ORB with a 10-minute opening range (not the default 15)
        state = detect_orb(stored, opening_range_minutes=10, session_open=_SESSION_OPEN)

        assert state is not None
        assert state.range_formed is True
        assert state.orb_high == pytest.approx(103.0)
        assert state.orb_low == pytest.approx(99.0)
        assert state.orb_range == pytest.approx(4.0)
        assert state.breakout_direction == 1
        assert state.breakout_price == pytest.approx(106.0)

    def test_bearish_orb_breakout(self, pg_connection: PGConnection) -> None:
        """ORB: post-ORB close below orb_low → bearish breakout."""
        repo = OHLCVRepository(pg_connection)
        candles = [
            _candle(0, 100.0, 103.0, 99.0, 101.0),
            _candle(5, 101.0, 103.0, 99.5, 100.5),
            _candle(15, 100.0, 100.5, 96.0, 97.0),  # close 97 < orb_low 99 → bearish
        ]
        repo.upsert_1m(candles)

        stored = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            _SESSION_OPEN,
            _SESSION_OPEN + timedelta(minutes=20),
        )
        state = detect_orb(stored, opening_range_minutes=10, session_open=_SESSION_OPEN)

        assert state is not None
        assert state.breakout_direction == -1
        assert state.breakout_price == pytest.approx(97.0)


class TestSRVerify:
    def test_support_level_at_known_bounce_price(
        self, pg_connection: PGConnection
    ) -> None:
        """M06 VERIFY (S/R): price visits low=95 three times → support at ~95 with
        touches >= 3."""
        repo = OHLCVRepository(pg_connection)
        bounce_bars = {5, 12, 19}
        candles: list[OHLCVCandle] = []
        for i in range(25):
            low = 95.0 if i in bounce_bars else 97.0
            candles.append(_candle(i, 100.0, 103.0, low, 100.0))
        repo.upsert_1m(candles)

        stored = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            _SESSION_OPEN,
            _SESSION_OPEN + timedelta(minutes=25),
        )
        assert len(stored) == 25

        levels = detect_sr_levels(stored, swing_window=5, min_touches=2)
        support_near_95 = [
            lv
            for lv in levels
            if lv.level_type == "SUPPORT" and abs(lv.price - 95.0) < 1.0
        ]
        assert support_near_95, f"Expected support near 95.0; detected levels: {levels}"
        assert support_near_95[0].touches >= 3

    def test_resistance_level_at_known_peak_price(
        self, pg_connection: PGConnection
    ) -> None:
        """S/R: price touches high=108 twice → resistance at ~108."""
        repo = OHLCVRepository(pg_connection)
        peak_bars = {6, 15}
        candles: list[OHLCVCandle] = []
        for i in range(25):
            high = 108.0 if i in peak_bars else 103.0
            candles.append(_candle(i, 100.0, high, 97.0, 100.0))
        repo.upsert_1m(candles)

        stored = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            _SESSION_OPEN,
            _SESSION_OPEN + timedelta(minutes=25),
        )
        levels = detect_sr_levels(stored, swing_window=5, min_touches=2)
        resistance_near_108 = [
            lv
            for lv in levels
            if lv.level_type == "RESISTANCE" and abs(lv.price - 108.0) < 1.0
        ]
        assert (
            resistance_near_108
        ), f"Expected resistance near 108.0; detected levels: {levels}"


class TestCandlestickVerify:
    def test_bullish_engulfing_detected_at_known_bar(
        self, pg_connection: PGConnection
    ) -> None:
        """M06 VERIFY (candlestick): 20 declining bars then a classic bullish
        engulfing at bar 21 → CDLENGULFING detected bullish at index 21."""
        repo = OHLCVRepository(pg_connection)

        candles: list[OHLCVCandle] = []
        # 20 gently declining bars to establish downtrend
        for i in range(20):
            p = 120.0 - i * 0.4
            candles.append(_candle(i, p, p + 0.3, p - 0.5, p - 0.2))

        # Bar 20: bearish candle
        candles.append(_candle(20, open_=112.0, high=112.5, low=109.5, close=110.0))
        # Bar 21: bullish engulfing
        #   open below bar 20's close (110.0), close above bar 20's open (112.0)
        candles.append(_candle(21, open_=109.5, high=114.0, low=109.0, close=113.5))

        repo.upsert_1m(candles)

        stored = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            _SESSION_OPEN,
            _SESSION_OPEN + timedelta(minutes=22),
        )
        assert len(stored) == 22

        arrays = candle_arrays_from_candles(stored)
        signals = detect_all(arrays)

        engulfing_at_21 = [
            s for s in signals if s.name == "CDLENGULFING" and s.bar_index == 21
        ]
        assert engulfing_at_21, (
            "CDLENGULFING should fire bullish at bar 21 (the engulfing candle). "
            f"Signals at bars 20-21: {[s for s in signals if s.bar_index >= 20]}"
        )
        assert engulfing_at_21[0].direction == 100

    def test_full_snapshot_via_engine(self, pg_connection: PGConnection) -> None:
        """compute_snapshot returns valid PatternSnapshot with all three components."""
        repo = OHLCVRepository(pg_connection)
        candles = [_candle(i, 100.0, 103.0, 97.0, 100.0) for i in range(30)]
        repo.upsert_1m(candles)

        stored = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            _SESSION_OPEN,
            _SESSION_OPEN + timedelta(minutes=30),
        )
        assert len(stored) == 30

        snapshot = compute_snapshot(SYMBOL, EXCHANGE, "1m", stored)

        assert snapshot.symbol == SYMBOL
        assert snapshot.exchange == EXCHANGE
        assert isinstance(snapshot.candlestick_signals, list)
        assert isinstance(snapshot.sr_levels, list)
        # ORB: first candle at session open, so ORB window starts there
        assert snapshot.orb_state is not None
        assert snapshot.orb_state.range_formed is True
