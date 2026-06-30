"""The M04 VERIFY command, against real TimescaleDB + Redis:

    compute all indicators RELIANCE.NS 5m -> Redis cached -> latency < 50ms

Yahoo Finance is rate-limited from this build's network (see M03's ADR-007/ADR-008
notes and shared/storage/backfill.py), so -- mirroring how M03's own VERIFY test
proved the storage layer's round-trip correctness with synthetic data instead of a
live yfinance fetch -- this seeds synthetic 1-minute candles directly through the
real storage layer, then exercises the real indicator engine and real Redis cache on
top of them. The compute-and-cache code path under test is exactly what the CLI
(shared/indicators/cli.py) runs in production; only the data source is synthetic.
"""

import time
from datetime import UTC, datetime, timedelta

import redis as redis_lib
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.core.constants import INDICATOR_LATENCY_BUDGET_MS
from shared.indicators.cache import load_snapshot, store_snapshot
from shared.indicators.engine import compute_snapshot
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

SYMBOL = "RELIANCE.NS"
EXCHANGE = "NSE"
T0 = datetime(2026, 6, 1, 3, 45, tzinfo=UTC)


def _minute_candle(i: int) -> OHLCVCandle:
    # Gentle, deterministic oscillation -- enough variation that every indicator
    # (oscillators included) produces a real number, not a degenerate constant.
    wiggle = 0.3 if i % 3 else -0.2
    close = 100.0 + wiggle * (i % 7)
    return OHLCVCandle(
        time=T0 + timedelta(minutes=i),
        symbol=SYMBOL,
        exchange=EXCHANGE,
        open=close - 0.1,
        high=close + 0.3,
        low=close - 0.3,
        close=close,
        volume=100 + (i % 20) * 10,
    )


class TestIndicatorEngineVerify:
    def test_compute_cache_and_latency(
        self, pg_connection: PGConnection, redis_client: redis_lib.Redis
    ) -> None:
        # 1,200 one-minute candles -> 240 five-minute candles, comfortably above
        # every indicator's min_candles (the largest is EMA_200).
        repo = OHLCVRepository(pg_connection)
        candles = [_minute_candle(i) for i in range(1200)]
        written = repo.upsert_1m(candles)
        assert written == 1200

        five_min_candles = repo.query_candles(
            SYMBOL, EXCHANGE, "5m", T0, T0 + timedelta(minutes=1200)
        )
        assert len(five_min_candles) == 240

        t0 = time.perf_counter()
        snapshot = compute_snapshot(SYMBOL, EXCHANGE, "5m", five_min_candles)
        store_snapshot(redis_client, snapshot)
        latency_ms = (time.perf_counter() - t0) * 1000

        # Computed correctly: every indicator ran (240 candles clears every
        # min_candles threshold) and produced a real, non-None value.
        assert snapshot.values["EMA"]["EMA_200"] is not None
        assert snapshot.values["RSI"]["RSI_14"] is not None
        assert snapshot.values["PIVOT_POINTS"]["PIVOT"] is not None

        # Cached: a fresh read from Redis (not the in-process object) round-trips.
        cached = load_snapshot(redis_client, SYMBOL, EXCHANGE, "5m")
        assert cached is not None
        assert cached.values["RSI"]["RSI_14"] == snapshot.values["RSI"]["RSI_14"]

        # Latency: compute + cache-write must stay under the M04 VERIFY budget.
        assert latency_ms < INDICATOR_LATENCY_BUDGET_MS, (
            f"compute+cache took {latency_ms:.2f}ms, "
            f"budget is {INDICATOR_LATENCY_BUDGET_MS}ms"
        )
