"""Unit tests for shared.ingestion.aggregator (M16)."""

from __future__ import annotations

import time

from shared.ingestion.aggregator import CandleAggregator
from shared.ingestion.models import RawTick


def _tick(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    ltp: float = 100.0,
    volume: int = 100,
    ts_ms: int = 0,
) -> RawTick:
    return RawTick(symbol=symbol, exchange=exchange, ltp=ltp, volume=volume, timestamp_ms=ts_ms)


def _bar_start(ts_ms: int, interval: int = 60) -> int:
    return (ts_ms // (interval * 1000)) * (interval * 1000)


class TestCandleAggregator:
    def _base(self) -> int:
        now_ms = int(time.time() * 1000)
        return _bar_start(now_ms - 120_000)  # 2 minutes ago

    def test_single_tick_returns_none(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        assert agg.ingest(_tick(ts_ms=t0 + 1_000)) is None

    def test_bar_roll_emits_candle(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ltp=100.0, ts_ms=t0 + 1_000))
        c = agg.ingest(_tick(ltp=101.0, ts_ms=t0 + 61_000))
        assert c is not None

    def test_open_is_first_price(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ltp=100.0, ts_ms=t0 + 100))
        agg.ingest(_tick(ltp=110.0, ts_ms=t0 + 200))
        c = agg.ingest(_tick(ltp=105.0, ts_ms=t0 + 61_000))
        assert c is not None and c.open == 100.0

    def test_close_is_last_price_before_roll(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ltp=100.0, ts_ms=t0 + 100))
        agg.ingest(_tick(ltp=105.0, ts_ms=t0 + 200))
        c = agg.ingest(_tick(ltp=103.0, ts_ms=t0 + 61_000))
        assert c is not None and c.close == 105.0

    def test_high_is_maximum(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        for price in [100.0, 115.0, 108.0, 112.0]:
            agg.ingest(_tick(ltp=price, ts_ms=t0 + 100))
        c = agg.ingest(_tick(ltp=99.0, ts_ms=t0 + 61_000))
        assert c is not None and c.high == 115.0

    def test_low_is_minimum(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        for price in [100.0, 95.0, 98.0, 102.0]:
            agg.ingest(_tick(ltp=price, ts_ms=t0 + 100))
        c = agg.ingest(_tick(ltp=99.0, ts_ms=t0 + 61_000))
        assert c is not None and c.low == 95.0

    def test_volume_accumulates(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        for vol in [50, 100, 200]:
            agg.ingest(_tick(volume=vol, ts_ms=t0 + 100))
        c = agg.ingest(_tick(volume=10, ts_ms=t0 + 61_000))
        assert c is not None and c.volume == 350

    def test_tick_count_tracked(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        for i in range(5):
            agg.ingest(_tick(ts_ms=t0 + i * 100))
        c = agg.ingest(_tick(ts_ms=t0 + 61_000))
        assert c is not None and c.tick_count == 5

    def test_candle_timestamp_is_bar_start(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ts_ms=t0 + 30_000))
        c = agg.ingest(_tick(ts_ms=t0 + 61_000))
        assert c is not None and c.timestamp_ms == t0

    def test_flush_returns_open_bars(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ts_ms=t0 + 1_000))
        result = agg.flush()
        assert "NSE:RELIANCE" in result

    def test_flush_clears_state(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ts_ms=t0 + 1_000))
        agg.flush()
        assert len(agg.flush()) == 0

    def test_reset_discards_open_bar(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(ts_ms=t0 + 1_000))
        agg.reset("RELIANCE", "NSE")
        assert len(agg.flush()) == 0

    def test_multiple_symbols_tracked(self) -> None:
        agg = CandleAggregator(60)
        t0 = self._base()
        agg.ingest(_tick(symbol="RELIANCE", ts_ms=t0 + 100))
        agg.ingest(_tick(symbol="INFY", ts_ms=t0 + 200))
        result = agg.flush()
        assert "NSE:RELIANCE" in result
        assert "NSE:INFY" in result

    def test_interval_seconds_property(self) -> None:
        agg = CandleAggregator(300)
        assert agg.interval_seconds == 300

    def test_5m_aggregator(self) -> None:
        agg = CandleAggregator(300)
        t0 = self._base()
        bar_start = _bar_start(t0, 300)
        agg.ingest(_tick(ltp=200.0, ts_ms=bar_start + 1_000))
        c = agg.ingest(_tick(ltp=205.0, ts_ms=bar_start + 301_000))
        assert c is not None
        assert c.interval_seconds == 300
        assert c.open == 200.0
