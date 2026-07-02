"""Unit tests for shared.ingestion.validator (M16)."""

from __future__ import annotations

import time

import pytest

from shared.core.constants import TICK_MAX_BACKWARD_MS, TICK_MAX_FUTURE_MS
from shared.ingestion.models import RawTick, TickValidationError
from shared.ingestion.validator import TickSequenceValidator


def _tick(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    ltp: float = 2500.0,
    volume: int = 100,
    ts_ms: int | None = None,
) -> RawTick:
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    return RawTick(symbol=symbol, exchange=exchange, ltp=ltp, volume=volume, timestamp_ms=ts)


class TestTickSequenceValidator:
    def test_valid_tick_passes(self) -> None:
        v = TickSequenceValidator()
        v.validate(_tick())  # should not raise

    def test_zero_price_rejected(self) -> None:
        v = TickSequenceValidator()
        with pytest.raises(TickValidationError, match="zero"):
            v.validate(_tick(ltp=0.0))

    def test_negative_price_rejected(self) -> None:
        v = TickSequenceValidator()
        with pytest.raises(TickValidationError, match="zero"):
            v.validate(_tick(ltp=-1.0))

    def test_negative_volume_rejected(self) -> None:
        v = TickSequenceValidator()
        with pytest.raises(TickValidationError, match="negative volume"):
            v.validate(_tick(volume=-1))

    def test_zero_volume_accepted(self) -> None:
        v = TickSequenceValidator()
        v.validate(_tick(volume=0))  # zero volume is valid (no trades yet)

    def test_future_timestamp_rejected(self) -> None:
        v = TickSequenceValidator()
        future_ms = int(time.time() * 1000) + TICK_MAX_FUTURE_MS + 1_000
        with pytest.raises(TickValidationError, match="future"):
            v.validate(_tick(ts_ms=future_ms))

    def test_timestamp_at_future_boundary_rejected(self) -> None:
        v = TickSequenceValidator()
        future_ms = int(time.time() * 1000) + TICK_MAX_FUTURE_MS + 1
        with pytest.raises(TickValidationError, match="future"):
            v.validate(_tick(ts_ms=future_ms))

    def test_sequence_reversal_rejected(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        v.validate(_tick(ts_ms=now_ms))
        with pytest.raises(TickValidationError, match="out-of-sequence"):
            v.validate(_tick(ts_ms=now_ms - TICK_MAX_BACKWARD_MS - 1))

    def test_small_backward_within_tolerance_accepted(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        v.validate(_tick(ts_ms=now_ms))
        # Within TICK_MAX_BACKWARD_MS tolerance — should pass
        v.validate(_tick(ts_ms=now_ms - TICK_MAX_BACKWARD_MS + 1))

    def test_increasing_timestamps_accepted(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        for i in range(5):
            v.validate(_tick(ts_ms=now_ms - 5000 + i * 1000))

    def test_reset_clears_per_symbol(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        v.validate(_tick(ts_ms=now_ms))
        v.reset("RELIANCE", "NSE")
        # After reset, old timestamp is forgotten
        v.validate(_tick(ts_ms=now_ms - 2_000))

    def test_reset_without_exchange_clears_all(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        v.validate(_tick(ts_ms=now_ms))
        v.reset("RELIANCE")
        v.validate(_tick(ts_ms=now_ms - 2_000))

    def test_different_symbols_tracked_independently(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        v.validate(_tick(symbol="RELIANCE", ts_ms=now_ms))
        # Different symbol should not conflict
        v.validate(_tick(symbol="INFY", ts_ms=now_ms - 5_000))

    def test_different_exchanges_tracked_independently(self) -> None:
        v = TickSequenceValidator()
        now_ms = int(time.time() * 1000)
        v.validate(_tick(symbol="CBA", exchange="ASX", ts_ms=now_ms))
        v.validate(_tick(symbol="CBA", exchange="NSE", ts_ms=now_ms - 5_000))
