"""Integration tests for shared.storage.repositories against a real TimescaleDB.

Requires a real TimescaleDB server -- see tests/integration/timescale/conftest.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.storage.models import OHLCVCandle, Tick
from shared.storage.repositories import OHLCVRepository, TickRepository

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
T0 = datetime(2026, 6, 1, 9, 15, tzinfo=UTC)


def _candle(minute_offset: int, **overrides: object) -> OHLCVCandle:
    defaults: dict[str, object] = {
        "time": T0 + timedelta(minutes=minute_offset),
        "symbol": SYMBOL,
        "exchange": EXCHANGE,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000,
    }
    defaults.update(overrides)
    return OHLCVCandle(**defaults)  # type: ignore[arg-type]


def _tick(second_offset: int, **overrides: object) -> Tick:
    defaults: dict[str, object] = {
        "time": T0 + timedelta(seconds=second_offset),
        "symbol": SYMBOL,
        "exchange": EXCHANGE,
        "price": 100.0,
        "volume": 10,
    }
    defaults.update(overrides)
    return Tick(**defaults)  # type: ignore[arg-type]


class TestTickRepository:
    def test_insert_many_and_count(self, pg_connection: PGConnection) -> None:
        repo = TickRepository(pg_connection)
        ticks = [_tick(i) for i in range(5)]

        inserted = repo.insert_many(ticks)

        assert inserted == 5
        count = repo.count(SYMBOL, EXCHANGE, T0, T0 + timedelta(minutes=1))
        assert count == 5

    def test_insert_empty_is_noop(self, pg_connection: PGConnection) -> None:
        repo = TickRepository(pg_connection)

        assert repo.insert_many([]) == 0

    def test_count_excludes_out_of_range(self, pg_connection: PGConnection) -> None:
        repo = TickRepository(pg_connection)
        repo.insert_many([_tick(0), _tick(120)])  # one inside, one 2 minutes later

        count = repo.count(SYMBOL, EXCHANGE, T0, T0 + timedelta(minutes=1))

        assert count == 1


class TestOHLCVRepository:
    def test_upsert_empty_is_noop(self, pg_connection: PGConnection) -> None:
        repo = OHLCVRepository(pg_connection)

        assert repo.upsert_1m([]) == 0

    def test_upsert_and_query_1m(self, pg_connection: PGConnection) -> None:
        repo = OHLCVRepository(pg_connection)
        candles = [_candle(i) for i in range(3)]

        written = repo.upsert_1m(candles)

        assert written == 3
        queried = repo.query_candles(
            SYMBOL, EXCHANGE, "1m", T0, T0 + timedelta(minutes=10)
        )
        assert len(queried) == 3
        assert queried == sorted(queried, key=lambda c: c.time)

    def test_upsert_is_idempotent_on_conflict(
        self, pg_connection: PGConnection
    ) -> None:
        repo = OHLCVRepository(pg_connection)
        repo.upsert_1m([_candle(0, close=100.5)])
        repo.upsert_1m([_candle(0, close=999.0)])  # same (symbol, exchange, time)

        queried = repo.query_candles(
            SYMBOL, EXCHANGE, "1m", T0, T0 + timedelta(minutes=1)
        )

        assert len(queried) == 1, "must update in place, not duplicate"
        assert queried[0].close == 999.0

    def test_query_candles_invalid_timeframe_raises(
        self, pg_connection: PGConnection
    ) -> None:
        repo = OHLCVRepository(pg_connection)

        with pytest.raises(ValueError, match="unsupported timeframe"):
            repo.query_candles(SYMBOL, EXCHANGE, "3m", T0, T0 + timedelta(minutes=1))

    def test_5m_continuous_aggregate_rolls_up_1m_rows_correctly(
        self, pg_connection: PGConnection
    ) -> None:
        repo = OHLCVRepository(pg_connection)
        candles = [
            _candle(0, open=100.0, high=105.0, low=99.0, close=104.0, volume=1000),
            _candle(1, open=104.0, high=106.0, low=103.0, close=105.5, volume=1200),
            _candle(2, open=105.5, high=107.0, low=105.0, close=106.0, volume=800),
            _candle(3, open=106.0, high=108.0, low=105.5, close=107.5, volume=900),
            _candle(4, open=107.5, high=109.0, low=107.0, close=108.5, volume=1100),
        ]
        repo.upsert_1m(candles)

        rolled_up = repo.query_candles(
            SYMBOL, EXCHANGE, "5m", T0, T0 + timedelta(minutes=5)
        )

        assert len(rolled_up) == 1
        bucket = rolled_up[0]
        assert bucket.open == 100.0  # first
        assert bucket.high == 109.0  # max
        assert bucket.low == 99.0  # min
        assert bucket.close == 108.5  # last
        assert bucket.volume == 5000  # sum

    def test_5m_aggregate_reflects_single_row_bucket_exactly(
        self, pg_connection: PGConnection
    ) -> None:
        """A coarse (5m-granularity) backfilled row is one row per 5-min bucket --
        the continuous aggregate must reproduce it exactly (ADR-007)."""
        repo = OHLCVRepository(pg_connection)
        repo.upsert_1m(
            [_candle(0, open=50.0, high=55.0, low=49.0, close=53.0, volume=4242)]
        )

        rolled_up = repo.query_candles(
            SYMBOL, EXCHANGE, "5m", T0, T0 + timedelta(minutes=5)
        )

        assert len(rolled_up) == 1
        assert rolled_up[0] == OHLCVCandle(
            time=T0,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            open=50.0,
            high=55.0,
            low=49.0,
            close=53.0,
            volume=4242,
        )

    def test_backfill_30_days_then_query_5m_count_correct(
        self, pg_connection: PGConnection
    ) -> None:
        """The spec's M03 VERIFY command: backfill 30 days -> query 5m candles ->
        count correct. Uses synthetic data standing in for a real yfinance fetch
        (Yahoo Finance is rate-limited from this build's network -- see
        shared/storage/backfill.py and tests/integration/test_yfinance_backfill_live.py
        for the real-network attempt); this test instead proves the storage layer's
        own round-trip integrity, which is what the VERIFY command is actually
        checking.
        """
        repo = OHLCVRepository(pg_connection)
        # One synthetic 5-minute candle per bucket across 30 days of NSE trading
        # hours (09:15-15:30 IST -> stored as UTC, the actual tz is irrelevant here).
        bars_per_day = 75  # 6h15m / 5min
        num_days = 30
        candles = [
            _candle(i * 5, open=100.0, high=101.0, low=99.0, close=100.5, volume=100)
            for i in range(bars_per_day * num_days)
        ]
        written = repo.upsert_1m(candles)
        assert written == bars_per_day * num_days

        queried = repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "5m",
            T0,
            T0 + timedelta(minutes=5 * bars_per_day * num_days),
        )

        assert len(queried) == bars_per_day * num_days
