"""Tests for M17 reconciliation data models."""

from __future__ import annotations

import pytest

from shared.reconciliation.models import (
    BrokerOrder,
    BrokerPosition,
    InternalOrder,
    InternalPosition,
    MismatchField,
    ReconciliationMismatch,
    ReconciliationResult,
)


class TestMismatchField:
    def test_all_variants_present(self) -> None:
        fields = {f.value for f in MismatchField}
        assert "quantity" in fields
        assert "avg_price" in fields
        assert "order_status" in fields
        assert "position_missing" in fields
        assert "order_missing" in fields
        assert "unexpected_position" in fields
        assert "unexpected_order" in fields

    def test_string_enum(self) -> None:
        assert MismatchField.QUANTITY.value == "quantity"


class TestBrokerPosition:
    def test_frozen(self) -> None:
        p = BrokerPosition("RELIANCE", "NSE", 10, 2500.0, "CNC")
        with pytest.raises((AttributeError, TypeError)):
            p.quantity = 5  # type: ignore[misc]

    def test_fields(self) -> None:
        p = BrokerPosition("INFY", "BSE", 20, 1800.0, "MIS")
        assert p.symbol == "INFY"
        assert p.exchange == "BSE"
        assert p.quantity == 20
        assert p.avg_price == 1800.0
        assert p.product == "MIS"


class TestBrokerOrder:
    def test_frozen(self) -> None:
        o = BrokerOrder("OID1", "COID1", "TCS", "NSE", "PLACED", 5, 0, 0.0)
        with pytest.raises((AttributeError, TypeError)):
            o.status = "FILLED"  # type: ignore[misc]

    def test_fields(self) -> None:
        o = BrokerOrder("OID2", "COID2", "HDFC", "NSE", "FILLED", 10, 10, 3200.0)
        assert o.order_id == "OID2"
        assert o.client_order_id == "COID2"
        assert o.filled_quantity == 10
        assert o.avg_price == 3200.0


class TestInternalPosition:
    def test_frozen(self) -> None:
        p = InternalPosition("WIPRO", "NSE", 5, 450.0)
        with pytest.raises((AttributeError, TypeError)):
            p.quantity = 10  # type: ignore[misc]

    def test_fields(self) -> None:
        p = InternalPosition("SBIN", "NSE", 100, 750.0)
        assert p.symbol == "SBIN"
        assert p.quantity == 100


class TestInternalOrder:
    def test_frozen(self) -> None:
        o = InternalOrder("COID3", "AXISBANK", "NSE", "PLACED", 0)
        with pytest.raises((AttributeError, TypeError)):
            o.status = "CANCELLED"  # type: ignore[misc]

    def test_fields(self) -> None:
        o = InternalOrder("COID4", "MARUTI", "NSE", "FILLED", 2)
        assert o.client_order_id == "COID4"
        assert o.filled_quantity == 2


class TestReconciliationMismatch:
    def test_frozen(self) -> None:
        mm = ReconciliationMismatch(
            symbol="RELIANCE",
            exchange="NSE",
            field=MismatchField.QUANTITY,
            internal_value="10",
            broker_value="5",
            detected_at_ms=1_000_000,
        )
        with pytest.raises((AttributeError, TypeError)):
            mm.symbol = "INFY"  # type: ignore[misc]

    def test_fields(self) -> None:
        mm = ReconciliationMismatch(
            symbol="TCS",
            exchange="BSE",
            field=MismatchField.AVG_PRICE,
            internal_value="3500.00",
            broker_value="3550.00",
            detected_at_ms=9_999,
        )
        assert mm.symbol == "TCS"
        assert mm.field == MismatchField.AVG_PRICE
        assert mm.detected_at_ms == 9_999


class TestReconciliationResult:
    def test_has_mismatches_true(self) -> None:
        mm = ReconciliationMismatch(
            symbol="X",
            exchange="NSE",
            field=MismatchField.QUANTITY,
            internal_value="1",
            broker_value="2",
            detected_at_ms=1,
        )
        rr = ReconciliationResult(
            cycle_started_at_ms=0,
            cycle_completed_at_ms=10,
            mismatches=[mm],
            symbols_blocked=[],
            symbols_cleared=[],
        )
        assert rr.has_mismatches is True
        assert rr.mismatch_count == 1

    def test_has_mismatches_false_when_empty(self) -> None:
        rr = ReconciliationResult(
            cycle_started_at_ms=0,
            cycle_completed_at_ms=5,
            mismatches=[],
            symbols_blocked=[],
            symbols_cleared=[],
        )
        assert rr.has_mismatches is False
        assert rr.mismatch_count == 0

    def test_symbols_lists(self) -> None:
        rr = ReconciliationResult(
            cycle_started_at_ms=0,
            cycle_completed_at_ms=1,
            mismatches=[],
            symbols_blocked=["NSE:RELIANCE"],
            symbols_cleared=["NSE:TCS"],
        )
        assert rr.symbols_blocked == ["NSE:RELIANCE"]
        assert rr.symbols_cleared == ["NSE:TCS"]
