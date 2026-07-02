"""Tests for M17 ReconciliationAgent."""

from __future__ import annotations

import time

from shared.reconciliation.agent import (
    BrokerStateProvider,
    InternalStateProvider,
    ReconciliationAgent,
)
from shared.reconciliation.models import (
    BrokerOrder,
    BrokerPosition,
    InternalOrder,
    InternalPosition,
    MismatchField,
    ReconciliationMismatch,
)


class _StubBroker:
    def __init__(
        self,
        positions: list[BrokerPosition] | None = None,
        orders: list[BrokerOrder] | None = None,
    ) -> None:
        self._positions = positions or []
        self._orders = orders or []

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions)

    def get_open_orders(self) -> list[BrokerOrder]:
        return list(self._orders)


class _StubInternal:
    def __init__(
        self,
        positions: list[InternalPosition] | None = None,
        orders: list[InternalOrder] | None = None,
    ) -> None:
        self._positions = positions or []
        self._orders = orders or []

    def get_positions(self) -> list[InternalPosition]:
        return list(self._positions)

    def get_open_orders(self) -> list[InternalOrder]:
        return list(self._orders)


def _make_agent(
    broker: _StubBroker,
    internal: _StubInternal,
    on_mismatch: object = None,
) -> ReconciliationAgent:
    return ReconciliationAgent(
        broker_state=broker,
        internal_state=internal,
        interval_seconds=3600,
        on_mismatch=on_mismatch,  # type: ignore[arg-type]
    )


class TestReconciliationAgentCycle:
    def test_clean_cycle_no_mismatches(self) -> None:
        broker = _StubBroker(
            positions=[BrokerPosition("RELIANCE", "NSE", 10, 2500.0, "CNC")]
        )
        internal = _StubInternal(
            positions=[InternalPosition("RELIANCE", "NSE", 10, 2500.0)]
        )
        agent = _make_agent(broker, internal)
        result = agent.run_cycle()
        assert not result.has_mismatches
        assert result.symbols_blocked == []
        assert result.symbols_cleared == []

    def test_mismatch_blocks_symbol(self) -> None:
        broker = _StubBroker(
            positions=[BrokerPosition("INFY", "NSE", 5, 1800.0, "CNC")]
        )
        internal = _StubInternal(
            positions=[InternalPosition("INFY", "NSE", 10, 1800.0)]
        )
        agent = _make_agent(broker, internal)
        result = agent.run_cycle()
        assert result.has_mismatches
        assert agent.is_blocked("INFY", "NSE")
        assert "NSE:INFY" in result.symbols_blocked

    def test_stale_block_cleared_on_next_cycle(self) -> None:
        broker = _StubBroker(
            positions=[BrokerPosition("TCS", "NSE", 5, 3600.0, "CNC")]
        )
        internal = _StubInternal(
            positions=[InternalPosition("TCS", "NSE", 10, 3600.0)]  # mismatch
        )
        agent = _make_agent(broker, internal)
        agent.run_cycle()
        assert agent.is_blocked("TCS", "NSE")

        # Fix the mismatch
        internal._positions = [InternalPosition("TCS", "NSE", 5, 3600.0)]
        result2 = agent.run_cycle()
        assert not result2.has_mismatches
        assert "NSE:TCS" in result2.symbols_cleared
        assert not agent.is_blocked("TCS", "NSE")

    def test_on_mismatch_callback_invoked(self) -> None:
        broker = _StubBroker(
            positions=[BrokerPosition("HDFC", "NSE", 3, 1600.0, "CNC")]
        )
        internal = _StubInternal(
            positions=[InternalPosition("HDFC", "NSE", 10, 1600.0)]
        )
        log: list[MismatchField] = []
        agent = _make_agent(
            broker, internal, on_mismatch=lambda mm: log.append(mm.field)
        )
        agent.run_cycle()
        assert MismatchField.QUANTITY in log

    def test_on_mismatch_callback_exception_is_suppressed(self) -> None:
        broker = _StubBroker(
            positions=[BrokerPosition("SBIN", "NSE", 1, 750.0, "CNC")]
        )
        internal = _StubInternal(
            positions=[InternalPosition("SBIN", "NSE", 10, 750.0)]
        )

        def bad_cb(mm: ReconciliationMismatch) -> None:
            raise RuntimeError("boom")

        agent = _make_agent(broker, internal, on_mismatch=bad_cb)
        result = agent.run_cycle()  # should not raise
        assert result.has_mismatches

    def test_is_blocked_delegates_to_registry(self) -> None:
        agent = _make_agent(_StubBroker(), _StubInternal())
        assert not agent.is_blocked("WIPRO", "NSE")

    def test_cycle_timestamps_populated(self) -> None:
        before = int(time.time() * 1000)
        agent = _make_agent(_StubBroker(), _StubInternal())
        result = agent.run_cycle()
        after = int(time.time() * 1000)
        assert (
            before
            <= result.cycle_started_at_ms
            <= result.cycle_completed_at_ms
            <= after
        )

    def test_multiple_mismatches_all_blocked(self) -> None:
        broker = _StubBroker(
            positions=[
                BrokerPosition("A", "NSE", 1, 100.0, "CNC"),
                BrokerPosition("B", "NSE", 1, 200.0, "CNC"),
            ]
        )
        internal = _StubInternal(
            positions=[
                InternalPosition("A", "NSE", 10, 100.0),  # qty mismatch
                InternalPosition("B", "NSE", 10, 200.0),  # qty mismatch
            ]
        )
        agent = _make_agent(broker, internal)
        result = agent.run_cycle()
        assert result.mismatch_count == 2
        assert agent.is_blocked("A", "NSE")
        assert agent.is_blocked("B", "NSE")


class TestReconciliationAgentLifecycle:
    def test_start_creates_timer(self) -> None:
        agent = _make_agent(_StubBroker(), _StubInternal())
        agent.start()
        assert agent._timer is not None
        agent.stop()

    def test_stop_cancels_timer(self) -> None:
        agent = _make_agent(_StubBroker(), _StubInternal())
        agent.start()
        agent.stop()
        assert agent._timer is None

    def test_double_start_is_idempotent(self) -> None:
        agent = _make_agent(_StubBroker(), _StubInternal())
        agent.start()
        timer_first = agent._timer
        agent.start()  # second call should be a no-op
        assert agent._timer is timer_first
        agent.stop()

    def test_stop_before_start_is_safe(self) -> None:
        agent = _make_agent(_StubBroker(), _StubInternal())
        agent.stop()  # should not raise

    def test_protocols_satisfied(self) -> None:
        broker = _StubBroker()
        internal = _StubInternal()
        assert isinstance(broker, BrokerStateProvider)
        assert isinstance(internal, InternalStateProvider)
