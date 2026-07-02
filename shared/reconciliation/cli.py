"""M17 VERIFY harness — 20 scenarios covering reconciliation logic end-to-end.

Run:
    python -m shared.reconciliation
"""

from __future__ import annotations

import time

import structlog

from shared.reconciliation.agent import ReconciliationAgent
from shared.reconciliation.block_registry import BlockRegistry
from shared.reconciliation.differ import diff_orders, diff_positions
from shared.reconciliation.models import (
    BrokerOrder,
    BrokerPosition,
    InternalOrder,
    InternalPosition,
    MismatchField,
    ReconciliationResult,
)
from shared.reconciliation.publisher import MismatchPublisher

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stub broker / internal providers for VERIFY
# ---------------------------------------------------------------------------


class _StubBroker:
    """Configurable stub broker state provider."""

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
    """Configurable stub internal state provider."""

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


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _check(label: str, condition: bool) -> bool:
    if condition:
        logger.info("VERIFY_PASS", scenario=label)
    else:
        logger.error("VERIFY_FAIL", scenario=label)
    return condition


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def run_verify() -> bool:
    now_ms = int(time.time() * 1000)
    results: list[bool] = []

    # --- Scenario 1: Clean slate — no mismatches ---
    broker = _StubBroker(
        positions=[BrokerPosition("RELIANCE", "NSE", 10, 2500.0, "CNC")],
    )
    internal = _StubInternal(
        positions=[InternalPosition("RELIANCE", "NSE", 10, 2500.0)],
    )
    mismatches = diff_positions(
        broker.get_positions(), internal.get_positions(), now_ms
    )
    results.append(
        _check("S01: no position mismatch when state matches", not mismatches)
    )

    # --- Scenario 2: Quantity mismatch detected ---
    broker2 = _StubBroker(
        positions=[BrokerPosition("INFY", "NSE", 5, 1800.0, "CNC")]
    )
    internal2 = _StubInternal(
        positions=[InternalPosition("INFY", "NSE", 10, 1800.0)]
    )
    m2 = diff_positions(broker2.get_positions(), internal2.get_positions(), now_ms)
    results.append(
        _check(
            "S02: quantity mismatch flagged",
            len(m2) == 1 and m2[0].field == MismatchField.QUANTITY,
        )
    )

    # --- Scenario 3: Avg price mismatch beyond 0.1% tolerance ---
    broker3 = _StubBroker(
        positions=[BrokerPosition("TCS", "NSE", 10, 3600.0, "CNC")]
    )
    internal3 = _StubInternal(
        positions=[InternalPosition("TCS", "NSE", 10, 3565.0)]  # >0.1% diff
    )
    m3 = diff_positions(broker3.get_positions(), internal3.get_positions(), now_ms)
    results.append(
        _check(
            "S03: avg_price mismatch beyond tolerance flagged",
            any(mm.field == MismatchField.AVG_PRICE for mm in m3),
        )
    )

    # --- Scenario 4: Avg price within tolerance — no mismatch ---
    broker4 = _StubBroker(
        positions=[BrokerPosition("HDFC", "NSE", 10, 1600.05, "CNC")]
    )
    internal4 = _StubInternal(
        positions=[InternalPosition("HDFC", "NSE", 10, 1600.0)]  # 0.003% diff
    )
    m4 = diff_positions(broker4.get_positions(), internal4.get_positions(), now_ms)
    results.append(
        _check(
            "S04: avg_price within tolerance ignored",
            not any(mm.field == MismatchField.AVG_PRICE for mm in m4),
        )
    )

    # --- Scenario 5: Internal position missing at broker ---
    broker5 = _StubBroker(positions=[])
    internal5 = _StubInternal(
        positions=[InternalPosition("WIPRO", "NSE", 10, 500.0)]
    )
    m5 = diff_positions(broker5.get_positions(), internal5.get_positions(), now_ms)
    results.append(
        _check(
            "S05: POSITION_MISSING flagged when broker lacks internal position",
            len(m5) == 1 and m5[0].field == MismatchField.POSITION_MISSING,
        )
    )

    # --- Scenario 6: Unexpected broker position (not in internal state) ---
    broker6 = _StubBroker(
        positions=[BrokerPosition("SBIN", "NSE", 20, 750.0, "CNC")]
    )
    internal6 = _StubInternal(positions=[])
    m6 = diff_positions(broker6.get_positions(), internal6.get_positions(), now_ms)
    results.append(
        _check(
            "S06: UNEXPECTED_POSITION flagged for broker-only position",
            len(m6) == 1 and m6[0].field == MismatchField.UNEXPECTED_POSITION,
        )
    )

    # --- Scenario 7: Order status mismatch ---
    broker7 = _StubBroker(
        orders=[
            BrokerOrder(
                "B001", "coid-001", "RELIANCE", "NSE", "FILLED", 5, 5, 2500.0
            )
        ]
    )
    internal7 = _StubInternal(
        orders=[InternalOrder("coid-001", "RELIANCE", "NSE", "PLACED", 0)]
    )
    m7 = diff_orders(broker7.get_open_orders(), internal7.get_open_orders(), now_ms)
    results.append(
        _check(
            "S07: ORDER_STATUS mismatch detected",
            len(m7) == 1 and m7[0].field == MismatchField.ORDER_STATUS,
        )
    )

    # --- Scenario 8: Order status case-insensitive match (no mismatch) ---
    broker8 = _StubBroker(
        orders=[
            BrokerOrder("B002", "coid-002", "TCS", "NSE", "PLACED", 5, 0, 0.0)
        ]
    )
    internal8 = _StubInternal(
        orders=[InternalOrder("coid-002", "TCS", "NSE", "placed", 0)]
    )
    m8 = diff_orders(broker8.get_open_orders(), internal8.get_open_orders(), now_ms)
    results.append(
        _check("S08: order status comparison is case-insensitive", not m8)
    )

    # --- Scenario 9: Internal order missing at broker ---
    broker9 = _StubBroker(orders=[])
    internal9 = _StubInternal(
        orders=[InternalOrder("coid-003", "HDFC", "NSE", "PLACED", 0)]
    )
    m9 = diff_orders(broker9.get_open_orders(), internal9.get_open_orders(), now_ms)
    results.append(
        _check(
            "S09: ORDER_MISSING flagged for internal order absent at broker",
            len(m9) == 1 and m9[0].field == MismatchField.ORDER_MISSING,
        )
    )

    # --- Scenario 10: Unexpected broker order not in internal state ---
    broker10 = _StubBroker(
        orders=[
            BrokerOrder(
                "B003", "coid-999", "INFY", "NSE", "PLACED", 10, 0, 0.0
            )
        ]
    )
    internal10 = _StubInternal(orders=[])
    m10 = diff_orders(
        broker10.get_open_orders(), internal10.get_open_orders(), now_ms
    )
    results.append(
        _check(
            "S10: UNEXPECTED_ORDER flagged for broker-only order",
            len(m10) == 1 and m10[0].field == MismatchField.UNEXPECTED_ORDER,
        )
    )

    # --- Scenario 11: BlockRegistry blocks and confirms symbol ---
    reg11 = BlockRegistry()
    reg11.block("RELIANCE", "NSE")
    results.append(
        _check(
            "S11: BlockRegistry.is_blocked() returns True after block()",
            reg11.is_blocked("RELIANCE", "NSE"),
        )
    )

    # --- Scenario 12: BlockRegistry clear removes block ---
    reg12 = BlockRegistry()
    reg12.block("TCS", "NSE")
    reg12.clear("TCS", "NSE")
    results.append(
        _check(
            "S12: BlockRegistry.is_blocked() returns False after clear()",
            not reg12.is_blocked("TCS", "NSE"),
        )
    )

    # --- Scenario 13: BlockRegistry non-existent symbol not blocked ---
    reg13 = BlockRegistry()
    results.append(
        _check(
            "S13: BlockRegistry.is_blocked() returns False for unknown symbol",
            not reg13.is_blocked("WIPRO", "NSE"),
        )
    )

    # --- Scenario 14: MismatchPublisher no-Redis logs only ---
    pub14 = MismatchPublisher(redis_client=None)
    from shared.reconciliation.models import ReconciliationMismatch

    mm14 = ReconciliationMismatch(
        symbol="INFY",
        exchange="NSE",
        field=MismatchField.QUANTITY,
        internal_value="10",
        broker_value="5",
        detected_at_ms=now_ms,
    )
    eid14 = pub14.publish(mm14)
    results.append(
        _check(
            "S14: MismatchPublisher returns None when Redis is unavailable",
            eid14 is None,
        )
    )

    # --- Scenario 15: ReconciliationResult properties ---
    rr15 = ReconciliationResult(
        cycle_started_at_ms=now_ms,
        cycle_completed_at_ms=now_ms + 10,
        mismatches=[mm14],
        symbols_blocked=["NSE:INFY"],
        symbols_cleared=[],
    )
    results.append(
        _check(
            "S15: ReconciliationResult.has_mismatches and mismatch_count correct",
            rr15.has_mismatches and rr15.mismatch_count == 1,
        )
    )

    # --- Scenario 16: Clean ReconciliationResult ---
    rr16 = ReconciliationResult(
        cycle_started_at_ms=now_ms,
        cycle_completed_at_ms=now_ms + 5,
        mismatches=[],
        symbols_blocked=[],
        symbols_cleared=[],
    )
    results.append(
        _check(
            "S16: ReconciliationResult.has_mismatches False when empty",
            not rr16.has_mismatches and rr16.mismatch_count == 0,
        )
    )

    # --- Scenario 17: Full agent cycle — no mismatches, no blocks ---
    broker17 = _StubBroker(
        positions=[BrokerPosition("RELIANCE", "NSE", 5, 2500.0, "CNC")],
    )
    internal17 = _StubInternal(
        positions=[InternalPosition("RELIANCE", "NSE", 5, 2500.0)],
    )
    agent17 = ReconciliationAgent(
        broker_state=broker17,
        internal_state=internal17,
        interval_seconds=3600,
    )
    result17 = agent17.run_cycle()
    results.append(
        _check(
            "S17: agent run_cycle returns clean result for matching state",
            not result17.has_mismatches
            and not result17.symbols_blocked
            and not result17.symbols_cleared,
        )
    )

    # --- Scenario 18: Full agent cycle detects quantity mismatch and blocks ---
    broker18 = _StubBroker(
        positions=[BrokerPosition("HDFC", "NSE", 5, 1600.0, "CNC")]
    )
    internal18 = _StubInternal(
        positions=[InternalPosition("HDFC", "NSE", 10, 1600.0)]
    )
    mismatch_log18: list[MismatchField] = []
    agent18 = ReconciliationAgent(
        broker_state=broker18,
        internal_state=internal18,
        interval_seconds=3600,
        on_mismatch=lambda mm: mismatch_log18.append(mm.field),
    )
    result18 = agent18.run_cycle()
    results.append(
        _check(
            "S18: agent cycle detects mismatch, blocks symbol, fires on_mismatch",
            result18.has_mismatches
            and len(result18.symbols_blocked) == 1
            and mismatch_log18 == [MismatchField.QUANTITY]
            and agent18.is_blocked("HDFC", "NSE"),
        )
    )

    # --- Scenario 19: Stale block cleared on next cycle ---
    broker19 = _StubBroker(
        positions=[BrokerPosition("HDFC", "NSE", 10, 1600.0, "CNC")]
    )
    # Second cycle: state is reconciled
    agent18._broker = broker19  # swap stub
    result19 = agent18.run_cycle()
    results.append(
        _check(
            "S19: stale block cleared when mismatch resolved in next cycle",
            not result19.has_mismatches
            and len(result19.symbols_cleared) == 1
            and not agent18.is_blocked("HDFC", "NSE"),
        )
    )

    # --- Scenario 20: agent.start/stop schedules and cancels timer ---
    broker20 = _StubBroker()
    internal20 = _StubInternal()
    agent20 = ReconciliationAgent(
        broker_state=broker20,
        internal_state=internal20,
        interval_seconds=3600,
    )
    agent20.start()
    timer_active = agent20._timer is not None
    agent20.stop()
    timer_none = agent20._timer is None
    results.append(
        _check(
            "S20: agent start/stop manages timer lifecycle correctly",
            timer_active and timer_none,
        )
    )

    total = len(results)
    passed = sum(results)
    logger.info("VERIFY_SUMMARY", passed=passed, total=total)
    return passed == total
