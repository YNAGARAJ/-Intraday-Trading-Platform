"""Unit tests for M14 execution models."""

from __future__ import annotations

import time

import pytest

from shared.execution.models import DeadLetterEntry, FillReport, OrderStatus


def _make_fill(**kwargs: object) -> FillReport:
    defaults: dict[str, object] = dict(
        client_order_id="ORD-001",
        broker_order_id="BRK-001",
        symbol="RELIANCE",
        exchange="NSE",
        direction="LONG",
        filled_quantity=100,
        requested_quantity=100,
        filled_price=200.0,
        status=OrderStatus.FILLED,
        rejection_reason=None,
        placed_at_ms=int(time.time() * 1000),
        filled_at_ms=int(time.time() * 1000),
        slippage_pct=0.05,
        is_partial=False,
        sl_quantity=100,
        attempt_count=1,
        strategy_tag="STRAT001",
        compliance_audit_id="audit-abc",
    )
    defaults.update(kwargs)
    return FillReport(**defaults)  # type: ignore[arg-type]


class TestOrderStatus:
    def test_all_statuses_defined(self) -> None:
        statuses = {s.value for s in OrderStatus}
        assert statuses == {
            "PENDING", "PLACED", "FILLED", "PARTIALLY_FILLED",
            "REJECTED", "CANCELLED",
        }

    def test_is_string_enum(self) -> None:
        assert isinstance(OrderStatus.FILLED, str)
        assert OrderStatus.FILLED == "FILLED"


class TestFillReport:
    def test_basic_construction(self) -> None:
        fill = _make_fill()
        assert fill.symbol == "RELIANCE"
        assert fill.status == OrderStatus.FILLED
        assert fill.sl_quantity == 100

    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        fill = _make_fill()
        with pytest.raises(FrozenInstanceError):
            fill.filled_quantity = 999  # type: ignore[misc]

    def test_partial_fill(self) -> None:
        fill = _make_fill(
            filled_quantity=60,
            requested_quantity=100,
            status=OrderStatus.PARTIALLY_FILLED,
            is_partial=True,
            sl_quantity=60,
        )
        assert fill.is_partial
        assert fill.sl_quantity == fill.filled_quantity

    def test_rejected_has_no_broker_id(self) -> None:
        fill = _make_fill(
            broker_order_id=None,
            filled_quantity=0,
            filled_price=None,
            status=OrderStatus.REJECTED,
            rejection_reason="compliance violation",
            sl_quantity=0,
        )
        assert fill.broker_order_id is None
        assert fill.rejection_reason == "compliance violation"

    def test_slippage_none_when_market(self) -> None:
        fill = _make_fill(slippage_pct=None, filled_price=None)
        assert fill.slippage_pct is None

    def test_compliance_audit_id_attached(self) -> None:
        fill = _make_fill(compliance_audit_id="abc-123")
        assert fill.compliance_audit_id == "abc-123"


class TestDeadLetterEntry:
    def test_construction(self) -> None:
        entry = DeadLetterEntry(
            client_order_id="ORD-DLQ",
            symbol="TCS",
            exchange="NSE",
            last_error="Connection refused",
            attempt_count=3,
            enqueued_at_ms=int(time.time() * 1000),
            strategy_tag="STRAT002",
        )
        assert entry.client_order_id == "ORD-DLQ"
        assert entry.attempt_count == 3

    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        entry = DeadLetterEntry(
            client_order_id="X",
            symbol="X",
            exchange="NSE",
            last_error="err",
            attempt_count=1,
            enqueued_at_ms=0,
            strategy_tag="STRAT001",
        )
        with pytest.raises(FrozenInstanceError):
            entry.attempt_count = 99  # type: ignore[misc]
