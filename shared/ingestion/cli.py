"""M16 CLI — VERIFY scenarios for Data Ingestion Agent.

Run with::

    python -m shared.ingestion verify

Scenarios:
  01  Tick validation: zero-price rejected
  02  Tick validation: negative-price rejected
  03  Tick validation: negative-volume rejected
  04  Tick validation: valid tick accepted
  05  Tick validation: sequence reversal rejected
  06  Tick validation: reset allows re-sequence
  07  Tick validation: future timestamp rejected
  08  Aggregator: single tick → no candle emitted
  09  Aggregator: bar rolls → candle emitted on next tick
  10  Aggregator: OHLCV values correct
  11  Aggregator: volume accumulates within bar
  12  Aggregator: flush returns open bars
  13  Aggregator: reset discards open bar
  14  TickBuffer: push / pending_count (in-memory fallback)
  15  TickBuffer: drain returns and removes ticks
  16  TickBuffer: Redis push path (fake Redis)
  17  DataIngestionAgent: paper mode status = PAPER
  18  DataIngestionAgent: inject_tick triggers 1m candle
  19  DataIngestionAgent: get_latest_candle returns correct close price
  20  DataIngestionAgent: latency < 200ms for 1000 tick injections
"""

from __future__ import annotations

import sys
import time

import structlog

from shared.ingestion.agent import DataIngestionAgent
from shared.ingestion.aggregator import CandleAggregator
from shared.ingestion.buffer import TickBuffer
from shared.ingestion.models import IngestionStatus, RawTick, TickValidationError
from shared.ingestion.validator import TickSequenceValidator

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(40),  # ERROR only in CLI
)


class _FakeRedis:
    """In-process fake Redis for VERIFY scenarios."""

    def __init__(self) -> None:
        self._store: dict[str, list[str]] = {}

    def rpush(self, name: str, *values: str) -> int:
        lst = self._store.setdefault(name, [])
        lst.extend(values)
        return len(lst)

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        lst = self._store.get(name, [])
        slice_ = lst[start: end + 1] if end >= 0 else lst[start:]
        return [s.encode() for s in slice_]

    def llen(self, name: str) -> int:
        return len(self._store.get(name, []))

    def ltrim(self, name: str, start: int, end: int) -> bool:
        lst = self._store.get(name, [])
        self._store[name] = lst[start: end + 1] if end >= 0 else lst[start:]
        return True


def _pass(num: str, msg: str) -> None:
    print(f"  [PASS] Scenario {num}: {msg}")


def _fail(num: str, msg: str) -> None:
    print(f"  [FAIL] Scenario {num}: {msg}")


def _tick(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    ltp: float = 2500.0,
    volume: int = 100,
    ts_ms: int | None = None,
) -> RawTick:
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    return RawTick(
        symbol=symbol, exchange=exchange, ltp=ltp, volume=volume, timestamp_ms=ts
    )


def run_verify() -> bool:  # noqa: PLR0912,PLR0915
    """Execute all 20 VERIFY scenarios. Returns True if all pass."""
    print("=" * 70)
    print("M16 — DATA INGESTION AGENT  |  20 VERIFY SCENARIOS")
    print("=" * 70)
    all_pass = True

    print("\n── Scenarios 01-07: Tick validation ──")

    # 01: zero-price rejected
    v01 = TickSequenceValidator()
    ok01 = False
    try:
        v01.validate(_tick(ltp=0.0))
    except TickValidationError:
        ok01 = True
    if not ok01:
        all_pass = False
    (_pass if ok01 else _fail)("01", "Zero-price tick rejected")

    # 02: negative-price rejected
    v02 = TickSequenceValidator()
    ok02 = False
    try:
        v02.validate(_tick(ltp=-1.0))
    except TickValidationError:
        ok02 = True
    if not ok02:
        all_pass = False
    (_pass if ok02 else _fail)("02", "Negative-price tick rejected")

    # 03: negative-volume rejected
    v03 = TickSequenceValidator()
    ok03 = False
    try:
        v03.validate(_tick(volume=-1))
    except TickValidationError:
        ok03 = True
    if not ok03:
        all_pass = False
    (_pass if ok03 else _fail)("03", "Negative-volume tick rejected")

    # 04: valid tick accepted
    v04 = TickSequenceValidator()
    ok04 = True
    try:
        v04.validate(_tick())
    except TickValidationError:
        ok04 = False
    if not ok04:
        all_pass = False
    (_pass if ok04 else _fail)("04", "Valid tick accepted without error")

    # 05: sequence reversal rejected
    v05 = TickSequenceValidator()
    now_ms = int(time.time() * 1000)
    v05.validate(_tick(ts_ms=now_ms))
    ok05 = False
    try:
        v05.validate(_tick(ts_ms=now_ms - 2_000))  # 2s in the past
    except TickValidationError:
        ok05 = True
    if not ok05:
        all_pass = False
    (_pass if ok05 else _fail)("05", "Out-of-sequence tick rejected")

    # 06: reset allows re-sequence
    v05.reset("RELIANCE", "NSE")
    ok06 = True
    try:
        v05.validate(_tick(ts_ms=now_ms - 2_000))
    except TickValidationError:
        ok06 = False
    if not ok06:
        all_pass = False
    (_pass if ok06 else _fail)("06", "Reset allows earlier timestamp after re-sequence")

    # 07: far-future timestamp rejected
    v07 = TickSequenceValidator()
    ok07 = False
    try:
        v07.validate(_tick(ts_ms=now_ms + 10_000))  # 10s in the future
    except TickValidationError:
        ok07 = True
    if not ok07:
        all_pass = False
    (_pass if ok07 else _fail)("07", "Far-future timestamp rejected")

    print("\n── Scenarios 08-13: Candle aggregator ──")

    # 08: single tick → no candle
    agg08 = CandleAggregator(interval_seconds=60)
    bar_start = (now_ms // 60_000) * 60_000
    c08 = agg08.ingest(_tick(ts_ms=bar_start + 1_000))
    ok08 = c08 is None
    if not ok08:
        all_pass = False
    (_pass if ok08 else _fail)("08", "Single tick yields no candle")

    # 09: bar rolls → candle emitted
    agg09 = CandleAggregator(interval_seconds=60)
    t0 = (now_ms // 60_000) * 60_000
    agg09.ingest(_tick(ltp=2500.0, ts_ms=t0 + 1_000))
    c09 = agg09.ingest(_tick(ltp=2510.0, ts_ms=t0 + 61_000))  # next bar
    ok09 = c09 is not None
    if not ok09:
        all_pass = False
    close09 = c09.close if c09 else None
    (_pass if ok09 else _fail)("09", f"Bar roll emits candle (close={close09})")

    # 10: OHLCV values correct
    agg10 = CandleAggregator(interval_seconds=60)
    t1 = (now_ms // 60_000) * 60_000
    agg10.ingest(_tick(ltp=100.0, volume=10, ts_ms=t1 + 100))
    agg10.ingest(_tick(ltp=105.0, volume=20, ts_ms=t1 + 200))
    agg10.ingest(_tick(ltp=98.0, volume=30, ts_ms=t1 + 300))
    agg10.ingest(_tick(ltp=102.0, volume=15, ts_ms=t1 + 400))
    c10 = agg10.ingest(_tick(ltp=99.0, volume=5, ts_ms=t1 + 61_000))
    ok10 = (
        c10 is not None
        and c10.open == 100.0
        and c10.high == 105.0
        and c10.low == 98.0
        and c10.close == 102.0
        and c10.volume == 75
    )
    if not ok10:
        all_pass = False
    detail10 = (
        f"O={c10.open} H={c10.high} L={c10.low} C={c10.close} V={c10.volume}"
        if c10 else "no candle"
    )
    (_pass if ok10 else _fail)("10", f"OHLCV values correct: {detail10}")

    # 11: volume accumulates within bar
    agg11 = CandleAggregator(interval_seconds=60)
    t2 = (now_ms // 60_000) * 60_000
    for vol in [50, 100, 200]:
        agg11.ingest(_tick(volume=vol, ts_ms=t2 + 1_000))
    c11_list = agg11.flush()
    key11 = "NSE:RELIANCE"
    ok11 = key11 in c11_list and c11_list[key11].volume == 350
    if not ok11:
        all_pass = False
    vol11 = c11_list[key11].volume if key11 in c11_list else "?"
    (_pass if ok11 else _fail)("11", f"Volume accumulated: {vol11} (expected 350)")

    # 12: flush returns open bars
    agg12 = CandleAggregator(interval_seconds=60)
    agg12.ingest(_tick(ltp=500.0, ts_ms=now_ms))
    flushed12 = agg12.flush()
    ok12 = len(flushed12) == 1 and len(agg12.flush()) == 0
    if not ok12:
        all_pass = False
    (_pass if ok12 else _fail)("12", f"Flush returns {len(flushed12)} open bars")

    # 13: reset discards open bar
    agg13 = CandleAggregator(interval_seconds=60)
    agg13.ingest(_tick(ts_ms=now_ms))
    agg13.reset("RELIANCE", "NSE")
    ok13 = len(agg13.flush()) == 0
    if not ok13:
        all_pass = False
    (_pass if ok13 else _fail)("13", "Reset discards open bar")

    print("\n── Scenarios 14-16: TickBuffer ──")

    # 14: push / pending_count (in-memory fallback)
    buf14 = TickBuffer(redis_client=None)
    buf14.push(_tick())
    buf14.push(_tick(ltp=2501.0))
    ok14 = buf14.pending_count() == 2
    if not ok14:
        all_pass = False
    (_pass if ok14 else _fail)("14", f"In-memory pending_count={buf14.pending_count()}")

    # 15: drain returns and removes ticks
    drained15 = buf14.drain(1)
    ok15 = len(drained15) == 1 and buf14.pending_count() == 1
    if not ok15:
        all_pass = False
    (_pass if ok15 else _fail)(
        "15", f"Drain 1 → got {len(drained15)}, remaining {buf14.pending_count()}"
    )

    # 16: Redis push path
    redis16 = _FakeRedis()
    buf16 = TickBuffer(redis_client=redis16)
    for _ in range(3):
        buf16.push(_tick())
    ok16 = buf16.pending_count() == 3
    if not ok16:
        all_pass = False
    drained16 = buf16.drain(2)
    ok16b = len(drained16) == 2 and buf16.pending_count() == 1
    if not ok16b:
        ok16 = False
        all_pass = False
    (_pass if ok16 else _fail)(
        "16",
        f"Redis push: count=3, drain 2 → got {len(drained16)}"
        f", rem {buf16.pending_count()}"
    )

    print("\n── Scenarios 17-20: DataIngestionAgent ──")

    # 17: paper mode status = PAPER
    agent17 = DataIngestionAgent(
        symbols=["RELIANCE"], exchange="NSE", mode=IngestionStatus.PAPER
    )
    ok17 = agent17.mode == IngestionStatus.PAPER
    if not ok17:
        all_pass = False
    (_pass if ok17 else _fail)("17", f"Paper mode status={agent17.mode.value}")

    # 18: inject_tick triggers 1m candle on bar roll
    # Use timestamps 2 minutes in the past so they pass future-guard validation.
    agent18 = DataIngestionAgent(
        symbols=["RELIANCE"], exchange="NSE", mode=IngestionStatus.PAPER
    )
    t3 = (now_ms // 60_000) * 60_000 - 120_000  # 2 min ago
    agent18.inject_tick(_tick(ltp=2500.0, ts_ms=t3 + 500))
    agent18.inject_tick(_tick(ltp=2505.0, ts_ms=t3 + 1_000))
    candles18 = agent18.inject_tick(_tick(ltp=2510.0, ts_ms=t3 + 61_000))
    ok18 = len(candles18) >= 1 and any(c.interval_seconds == 60 for c in candles18)
    if not ok18:
        all_pass = False
    (_pass if ok18 else _fail)(
        "18", f"inject_tick triggered {len(candles18)} candle(s) on bar roll"
    )

    # 19: get_latest_candle returns correct close price
    latest19 = agent18.get_latest_candle("RELIANCE", interval=60)
    ok19 = latest19 is not None and latest19.close == 2505.0
    if not ok19:
        all_pass = False
    (_pass if ok19 else _fail)(
        "19", f"get_latest_candle close={latest19.close if latest19 else 'None'}"
        f" (expected 2505.0)"
    )

    # 20: latency < 200ms for 1000 tick injections (timestamps in the past)
    agent20 = DataIngestionAgent(
        symbols=["RELIANCE"], exchange="NSE", mode=IngestionStatus.PAPER
    )
    t4 = now_ms - 120_000  # 2 min ago; 1000 × 60ms = 60s window, all in the past
    start20 = time.perf_counter()
    for i in range(1000):
        agent20.inject_tick(_tick(ltp=2500.0 + i * 0.001, ts_ms=t4 + i * 60))
    elapsed20_ms = (time.perf_counter() - start20) * 1000
    ok20 = elapsed20_ms < 200.0
    if not ok20:
        all_pass = False
    (_pass if ok20 else _fail)(
        "20", f"1000 ticks processed in {elapsed20_ms:.1f}ms (budget 200ms)"
    )

    print("\n" + "=" * 70)
    print(f"RESULT: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print("=" * 70)
    return all_pass


def main() -> None:
    """Entry point: ``python -m shared.ingestion [verify]``."""
    if len(sys.argv) < 2 or sys.argv[1] != "verify":
        print("Usage: python -m shared.ingestion verify")
        sys.exit(1)
    ok = run_verify()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
