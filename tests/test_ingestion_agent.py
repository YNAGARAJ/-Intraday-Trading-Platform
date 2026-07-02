"""Unit tests for shared.ingestion.agent (M16)."""

from __future__ import annotations

import time

import pytest

from shared.ingestion.agent import DataIngestionAgent
from shared.ingestion.models import IngestionStatus, RawTick, TickValidationError


def _tick(
    symbol: str = "RELIANCE",
    ltp: float = 2500.0,
    volume: int = 100,
    ts_ms: int | None = None,
) -> RawTick:
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    return RawTick(symbol=symbol, exchange="NSE", ltp=ltp, volume=volume, timestamp_ms=ts)


def _base_ms() -> int:
    now_ms = int(time.time() * 1000)
    return (now_ms // 60_000) * 60_000 - 120_000  # 2 min ago


class TestDataIngestionAgentPaper:
    def test_default_mode_is_paper(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        assert agent.mode == IngestionStatus.PAPER

    def test_explicit_paper_mode(self) -> None:
        agent = DataIngestionAgent(
            symbols=["RELIANCE"], exchange="NSE", mode=IngestionStatus.PAPER
        )
        assert agent.mode == IngestionStatus.PAPER

    def test_inject_valid_tick_returns_list(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        result = agent.inject_tick(_tick())
        assert isinstance(result, list)

    def test_inject_invalid_tick_raises(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        with pytest.raises(TickValidationError):
            agent.inject_tick(_tick(ltp=0.0))

    def test_inject_tick_emits_candle_on_bar_roll(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        t0 = _base_ms()
        agent.inject_tick(_tick(ltp=100.0, ts_ms=t0 + 500))
        candles = agent.inject_tick(_tick(ltp=105.0, ts_ms=t0 + 61_000))
        assert len(candles) >= 1
        assert any(c.interval_seconds == 60 for c in candles)

    def test_get_latest_candle_none_before_roll(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        agent.inject_tick(_tick())
        assert agent.get_latest_candle("RELIANCE") is None

    def test_get_latest_candle_after_roll(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        t0 = _base_ms()
        agent.inject_tick(_tick(ltp=2500.0, ts_ms=t0 + 500))
        agent.inject_tick(_tick(ltp=2505.0, ts_ms=t0 + 1_000))
        agent.inject_tick(_tick(ltp=2510.0, ts_ms=t0 + 61_000))
        c = agent.get_latest_candle("RELIANCE", interval=60)
        assert c is not None
        assert c.close == 2505.0

    def test_get_latest_5m_candle(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        t0 = (int(time.time() * 1000) // 300_000) * 300_000 - 600_000
        agent.inject_tick(_tick(ltp=100.0, ts_ms=t0 + 1_000))
        agent.inject_tick(_tick(ltp=102.0, ts_ms=t0 + 301_000))
        c5 = agent.get_latest_candle("RELIANCE", interval=300)
        assert c5 is not None
        assert c5.interval_seconds == 300

    def test_flush_open_bars(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        agent.inject_tick(_tick())
        flushed = agent.flush_open_bars()
        assert len(flushed) > 0

    def test_inject_multiple_symbols(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE", "INFY"], exchange="NSE")
        t0 = _base_ms()
        agent.inject_tick(RawTick("RELIANCE", "NSE", 2500.0, 100, t0 + 500))
        agent.inject_tick(RawTick("INFY", "NSE", 1500.0, 50, t0 + 600))
        flushed = agent.flush_open_bars()
        keys = set(flushed.keys())
        assert "NSE:RELIANCE" in keys
        assert "NSE:INFY" in keys

    def test_1000_ticks_under_200ms(self) -> None:
        agent = DataIngestionAgent(symbols=["RELIANCE"], exchange="NSE")
        t0 = int(time.time() * 1000) - 120_000
        start = time.perf_counter()
        for i in range(1000):
            agent.inject_tick(_tick(ltp=2500.0 + i * 0.001, ts_ms=t0 + i * 60))
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 200.0, f"1000 ticks took {elapsed_ms:.1f}ms"
