"""Unit tests for shared.ingestion.models (M16)."""

from __future__ import annotations

import pytest

from shared.ingestion.models import (
    IngestionStatus,
    OHLCVCandle,
    RawTick,
    TickValidationError,
)


class TestIngestionStatus:
    def test_values(self) -> None:
        assert IngestionStatus.LIVE == "LIVE"
        assert IngestionStatus.DEGRADED == "DEGRADED"
        assert IngestionStatus.PAPER == "PAPER"

    def test_is_str(self) -> None:
        assert isinstance(IngestionStatus.PAPER, str)


class TestRawTick:
    def test_frozen(self) -> None:
        tick = RawTick(symbol="REL", exchange="NSE", ltp=100.0, volume=50, timestamp_ms=1)
        with pytest.raises((AttributeError, TypeError)):
            tick.ltp = 200.0  # type: ignore[misc]

    def test_fields(self) -> None:
        tick = RawTick(symbol="CBA", exchange="ASX", ltp=75.5, volume=200, timestamp_ms=999)
        assert tick.symbol == "CBA"
        assert tick.exchange == "ASX"
        assert tick.ltp == 75.5
        assert tick.volume == 200
        assert tick.timestamp_ms == 999


class TestOHLCVCandle:
    def _make(self) -> OHLCVCandle:
        return OHLCVCandle(
            symbol="REL", exchange="NSE", interval_seconds=60,
            open=100.0, high=110.0, low=95.0, close=105.0,
            volume=1000, timestamp_ms=1_000_000,
        )

    def test_frozen(self) -> None:
        c = self._make()
        with pytest.raises((AttributeError, TypeError)):
            c.close = 99.0  # type: ignore[misc]

    def test_default_tick_count(self) -> None:
        c = self._make()
        assert c.tick_count == 0

    def test_interval_stored(self) -> None:
        c = self._make()
        assert c.interval_seconds == 60

    def test_ohlcv_fields(self) -> None:
        c = self._make()
        assert c.open == 100.0
        assert c.high == 110.0
        assert c.low == 95.0
        assert c.close == 105.0
        assert c.volume == 1000


class TestTickValidationError:
    def test_is_exception(self) -> None:
        with pytest.raises(TickValidationError):
            raise TickValidationError("bad tick")
