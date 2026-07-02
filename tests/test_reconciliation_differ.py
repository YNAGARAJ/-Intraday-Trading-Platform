"""Tests for M17 position and order diff logic."""

from __future__ import annotations

from shared.reconciliation.differ import diff_orders, diff_positions
from shared.reconciliation.models import (
    BrokerOrder,
    BrokerPosition,
    InternalOrder,
    InternalPosition,
    MismatchField,
)

NOW_MS = 1_700_000_000_000


class TestDiffPositions:
    def test_exact_match_no_mismatches(self) -> None:
        broker = [BrokerPosition("RELIANCE", "NSE", 10, 2500.0, "CNC")]
        internal = [InternalPosition("RELIANCE", "NSE", 10, 2500.0)]
        assert diff_positions(broker, internal, NOW_MS) == []

    def test_quantity_mismatch(self) -> None:
        broker = [BrokerPosition("INFY", "NSE", 5, 1800.0, "CNC")]
        internal = [InternalPosition("INFY", "NSE", 10, 1800.0)]
        m = diff_positions(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.QUANTITY
        assert m[0].internal_value == "10"
        assert m[0].broker_value == "5"

    def test_avg_price_mismatch_beyond_tolerance(self) -> None:
        # 1% diff — beyond 0.1% threshold
        broker = [BrokerPosition("TCS", "NSE", 10, 3636.0, "CNC")]
        internal = [InternalPosition("TCS", "NSE", 10, 3600.0)]
        m = diff_positions(broker, internal, NOW_MS)
        assert any(mm.field == MismatchField.AVG_PRICE for mm in m)

    def test_avg_price_within_tolerance_ignored(self) -> None:
        # 0.005% diff — below 0.1% threshold
        broker = [BrokerPosition("HDFC", "NSE", 10, 1600.08, "CNC")]
        internal = [InternalPosition("HDFC", "NSE", 10, 1600.0)]
        m = diff_positions(broker, internal, NOW_MS)
        assert not any(mm.field == MismatchField.AVG_PRICE for mm in m)

    def test_position_missing_at_broker(self) -> None:
        broker: list[BrokerPosition] = []
        internal = [InternalPosition("WIPRO", "NSE", 10, 500.0)]
        m = diff_positions(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.POSITION_MISSING
        assert m[0].symbol == "WIPRO"

    def test_zero_quantity_internal_no_mismatch_when_broker_missing(self) -> None:
        broker: list[BrokerPosition] = []
        internal = [InternalPosition("MARUTI", "NSE", 0, 0.0)]
        m = diff_positions(broker, internal, NOW_MS)
        assert m == []

    def test_unexpected_position_at_broker(self) -> None:
        broker = [BrokerPosition("SBIN", "NSE", 20, 750.0, "CNC")]
        internal: list[InternalPosition] = []
        m = diff_positions(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.UNEXPECTED_POSITION

    def test_unexpected_position_zero_qty_ignored(self) -> None:
        broker = [BrokerPosition("AXISBANK", "NSE", 0, 1000.0, "CNC")]
        internal: list[InternalPosition] = []
        m = diff_positions(broker, internal, NOW_MS)
        assert m == []

    def test_multiple_symbols_partial_match(self) -> None:
        broker = [
            BrokerPosition("RELIANCE", "NSE", 10, 2500.0, "CNC"),
            BrokerPosition("TCS", "NSE", 5, 3600.0, "CNC"),
        ]
        internal = [
            InternalPosition("RELIANCE", "NSE", 10, 2500.0),
            InternalPosition("TCS", "NSE", 10, 3600.0),  # quantity mismatch
        ]
        m = diff_positions(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].symbol == "TCS"

    def test_uses_now_ms_parameter(self) -> None:
        broker: list[BrokerPosition] = []
        internal = [InternalPosition("INFY", "NSE", 5, 1800.0)]
        m = diff_positions(broker, internal, 12345)
        assert m[0].detected_at_ms == 12345


class TestDiffOrders:
    def test_exact_match_no_mismatches(self) -> None:
        broker = [BrokerOrder("O1", "COID1", "RELIANCE", "NSE", "PLACED", 5, 0, 0.0)]
        internal = [InternalOrder("COID1", "RELIANCE", "NSE", "PLACED", 0)]
        assert diff_orders(broker, internal, NOW_MS) == []

    def test_order_status_mismatch(self) -> None:
        broker = [BrokerOrder("O1", "COID1", "INFY", "NSE", "FILLED", 5, 5, 1800.0)]
        internal = [InternalOrder("COID1", "INFY", "NSE", "PLACED", 0)]
        m = diff_orders(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.ORDER_STATUS

    def test_status_case_insensitive(self) -> None:
        broker = [BrokerOrder("O1", "COID1", "TCS", "NSE", "PLACED", 5, 0, 0.0)]
        internal = [InternalOrder("COID1", "TCS", "NSE", "placed", 0)]
        assert diff_orders(broker, internal, NOW_MS) == []

    def test_order_missing_at_broker(self) -> None:
        broker: list[BrokerOrder] = []
        internal = [InternalOrder("COID2", "HDFC", "NSE", "PLACED", 0)]
        m = diff_orders(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.ORDER_MISSING
        assert m[0].broker_value == "NOT_FOUND"

    def test_unexpected_order_at_broker(self) -> None:
        broker = [BrokerOrder("O99", "COID99", "WIPRO", "NSE", "PLACED", 10, 0, 0.0)]
        internal: list[InternalOrder] = []
        m = diff_orders(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.UNEXPECTED_ORDER
        assert m[0].internal_value == "NOT_FOUND"

    def test_multiple_orders_mixed(self) -> None:
        broker = [
            BrokerOrder("O1", "COID1", "RELIANCE", "NSE", "PLACED", 5, 0, 0.0),
        ]
        internal = [
            InternalOrder("COID1", "RELIANCE", "NSE", "PLACED", 0),
            InternalOrder("COID2", "SBIN", "NSE", "PLACED", 0),  # missing at broker
        ]
        m = diff_orders(broker, internal, NOW_MS)
        assert len(m) == 1
        assert m[0].field == MismatchField.ORDER_MISSING
        assert m[0].symbol == "SBIN"

    def test_empty_both_sides(self) -> None:
        assert diff_orders([], [], NOW_MS) == []

    def test_timestamp_propagated(self) -> None:
        broker: list[BrokerOrder] = []
        internal = [InternalOrder("COID-X", "NIFTY", "NSE", "PLACED", 0)]
        m = diff_orders(broker, internal, 99999)
        assert m[0].detected_at_ms == 99999
