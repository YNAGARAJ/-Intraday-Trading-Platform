"""Tests for M19 PnLTracker."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from shared.monitor.pnl_tracker import PnLTracker


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None

    def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        entries = self._streams.get(name, [])
        result = [
            (eid.encode(), {k.encode(): v.encode() for k, v in fields.items()})
            for eid, fields in reversed(entries)
        ]
        if count is not None:
            result = result[:count]
        return result

    def xadd(self, name: str, fields: dict[str, str]) -> bytes:
        self._streams.setdefault(name, []).append(("0-0", fields))
        return b"0-0"


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d")


class TestPnLTrackerNone:
    def test_no_redis_returns_zero_pnl(self) -> None:
        t = PnLTracker(redis_client=None)
        s = t.snapshot()
        assert s.pnl_today == 0.0
        assert s.pnl_today_pct == 0.0
        assert s.is_circuit_breaker is False

    def test_no_redis_halted_returns_false(self) -> None:
        t = PnLTracker(redis_client=None)
        assert t.read_system_halted() is False

    def test_no_redis_recon_returns_zero(self) -> None:
        t = PnLTracker(redis_client=None)
        assert t.read_reconciliation_mismatches() == 0

    def test_no_redis_orc_state_returns_empty(self) -> None:
        t = PnLTracker(redis_client=None)
        assert t.read_orchestrator_state() == {}


class TestPnLTrackerWithRedis:
    def test_reads_absolute_pnl(self) -> None:
        r = _FakeRedis()
        r.set(f"risk:daily:pnl:{_today()}", "12000.50")
        t = PnLTracker(redis_client=r, starting_capital=1_000_000.0)
        s = t.snapshot()
        assert abs(s.pnl_today - 12000.50) < 0.01

    def test_computes_pnl_pct(self) -> None:
        r = _FakeRedis()
        r.set(f"risk:daily:pnl:{_today()}", "-10000.0")
        t = PnLTracker(redis_client=r, starting_capital=1_000_000.0)
        s = t.snapshot()
        assert abs(s.pnl_today_pct - (-0.01)) < 1e-9

    def test_circuit_breaker_at_minus_2_pct(self) -> None:
        r = _FakeRedis()
        r.set(f"risk:daily:pnl:{_today()}", "-20000.0")
        t = PnLTracker(redis_client=r, starting_capital=1_000_000.0)
        s = t.snapshot()
        assert s.is_circuit_breaker is True

    def test_no_circuit_breaker_above_threshold(self) -> None:
        r = _FakeRedis()
        r.set(f"risk:daily:pnl:{_today()}", "-10000.0")
        t = PnLTracker(redis_client=r, starting_capital=1_000_000.0)
        s = t.snapshot()
        assert s.is_circuit_breaker is False

    def test_missing_pnl_key_returns_zero(self) -> None:
        r = _FakeRedis()
        t = PnLTracker(redis_client=r, starting_capital=1_000_000.0)
        s = t.snapshot()
        assert s.pnl_today == 0.0

    def test_corrupt_pnl_value_returns_zero(self) -> None:
        r = _FakeRedis()
        r.set(f"risk:daily:pnl:{_today()}", "not_a_number")
        t = PnLTracker(redis_client=r, starting_capital=1_000_000.0)
        s = t.snapshot()
        assert s.pnl_today == 0.0

    def test_starting_capital_zero_returns_zero_pct(self) -> None:
        r = _FakeRedis()
        r.set(f"risk:daily:pnl:{_today()}", "5000.0")
        t = PnLTracker(redis_client=r, starting_capital=0.0)
        s = t.snapshot()
        assert s.pnl_today_pct == 0.0


class TestSystemHaltedAndState:
    def test_halted_key_present_returns_true(self) -> None:
        r = _FakeRedis()
        r.set("system:status:halted", "true")
        t = PnLTracker(redis_client=r)
        assert t.read_system_halted() is True

    def test_halted_key_absent_returns_false(self) -> None:
        r = _FakeRedis()
        t = PnLTracker(redis_client=r)
        assert t.read_system_halted() is False

    def test_orchestrator_state_json_parsed(self) -> None:
        r = _FakeRedis()
        state = {"signals_today": 7, "open_positions": {"RELIANCE": {}}}
        r.set("orchestrator:state", json.dumps(state))
        t = PnLTracker(redis_client=r)
        result = t.read_orchestrator_state()
        assert result["signals_today"] == 7

    def test_orchestrator_state_missing_returns_empty(self) -> None:
        r = _FakeRedis()
        t = PnLTracker(redis_client=r)
        assert t.read_orchestrator_state() == {}

    def test_orchestrator_state_corrupt_returns_empty(self) -> None:
        r = _FakeRedis()
        r.set("orchestrator:state", "{not valid json}")
        t = PnLTracker(redis_client=r)
        assert t.read_orchestrator_state() == {}


class TestReconciliationMismatches:
    def test_empty_stream_returns_zero(self) -> None:
        r = _FakeRedis()
        t = PnLTracker(redis_client=r)
        assert t.read_reconciliation_mismatches() == 0

    def test_entries_counted_correctly(self) -> None:
        r = _FakeRedis()
        r.xadd("reconciliation:mismatches", {"type": "position"})
        r.xadd("reconciliation:mismatches", {"type": "order"})
        r.xadd("reconciliation:mismatches", {"type": "position"})
        t = PnLTracker(redis_client=r)
        assert t.read_reconciliation_mismatches() == 3
