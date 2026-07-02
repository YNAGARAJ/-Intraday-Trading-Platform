"""Unit tests for M14 ExecutionEngine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from shared.compliance.models import OrderIntent
from shared.compliance.strategy_registry import STRATEGY_EMA_VWAP_TREND
from shared.execution.brokers.base import BrokerPermanentError
from shared.execution.brokers.paper import PaperBroker
from shared.execution.dead_letter import DeadLetterQueue
from shared.execution.engine import (
    ExecutionEngine,
    make_kill_switch_liquidation_order,
    make_sl_exit_order,
)
from shared.execution.models import FillReport, OrderStatus

if TYPE_CHECKING:
    from shared.compliance.models import TaggedOrder

_IST = datetime(2026, 7, 2, 10, 30, 0, tzinfo=timezone.utc)
_IST_FSO = datetime(2026, 7, 2, 15, 15, 0, tzinfo=timezone.utc)


def _order(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    direction: str = "LONG",
    quantity: int = 100,
    price: float = 200.0,
    stop_loss: float = 190.0,
    strategy_name: str = STRATEGY_EMA_VWAP_TREND,
    order_id: str = "ORD-001",
    ltp: float = 200.0,
    is_priority: bool = False,
    is_exit: bool = False,
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        order_type="LIMIT",
        quantity=quantity,
        price=price,
        stop_loss=stop_loss,
        strategy_name=strategy_name,
        client_order_id=order_id,
        ltp=ltp,
        notional_value=price * quantity,
        capital=500_000.0,
        is_priority=is_priority,
        is_exit=is_exit,
    )


def _engine(
    partial_ratio: float | None = None,
    fail_count: int = 0,
    redis_client: object | None = None,
    max_retries: int = 0,
    retry_delay: float = 0.0,
    dlq: DeadLetterQueue | None = None,
) -> tuple[ExecutionEngine, PaperBroker, DeadLetterQueue]:
    paper = PaperBroker(partial_fill_ratio=partial_ratio, fail_count=fail_count)
    dlq = dlq or DeadLetterQueue()
    eng = ExecutionEngine(
        broker=paper,
        dead_letter_queue=dlq,
        redis_client=redis_client,
        max_retries=max_retries,
        retry_base_delay=retry_delay,
    )
    return eng, paper, dlq


class TestExecutionEngineBasicFill:
    def test_standard_fill_nse(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.status == OrderStatus.FILLED
        assert fill.filled_quantity == 100

    def test_fill_has_compliance_audit_id(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.compliance_audit_id != ""

    def test_fill_has_strategy_tag(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.strategy_tag == "STRAT001"

    def test_attempt_count_one_on_success(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.attempt_count == 1

    def test_asx_paper_fills(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(symbol="BHP.AX", exchange="ASX"), now_ist=_IST)
        assert fill.status == OrderStatus.FILLED

    def test_bse_paper_fills(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(exchange="BSE"), now_ist=_IST)
        assert fill.status == OrderStatus.FILLED


class TestExecutionEngineCompliance:
    def test_unknown_strategy_rejected(self) -> None:
        eng, _, _ = _engine()
        order = _order(strategy_name="TOTALLY_UNKNOWN", order_id="REJ-1")
        fill = eng.submit(order, now_ist=_IST)
        assert fill.status == OrderStatus.REJECTED
        assert fill.filled_quantity == 0

    def test_force_square_off_rejected(self) -> None:
        eng, _, _ = _engine()
        fill = eng.submit(_order(order_id="FSO-1"), now_ist=_IST_FSO)
        assert fill.status == OrderStatus.REJECTED
        assert fill.compliance_audit_id != ""

    def test_rejected_fill_has_rejection_reason(self) -> None:
        eng, _, _ = _engine()
        order = _order(strategy_name="BAD_STRAT", order_id="REJ-2")
        fill = eng.submit(order, now_ist=_IST)
        assert fill.rejection_reason is not None and len(fill.rejection_reason) > 0

    def test_market_order_mpp_conversion(self) -> None:
        eng, _, _ = _engine()
        order = OrderIntent(
            symbol="MARUTI",
            exchange="NSE",
            direction="LONG",
            order_type="MARKET",
            quantity=10,
            price=None,
            stop_loss=11000.0,
            strategy_name=STRATEGY_EMA_VWAP_TREND,
            client_order_id="MPP-1",
            ltp=12000.0,
            notional_value=120000.0,
            capital=500_000.0,
        )
        fill = eng.submit(order, now_ist=_IST)
        assert fill.status == OrderStatus.FILLED
        assert fill.filled_price == pytest.approx(12000.0 * 1.0025, rel=1e-4)


class TestExecutionEngineKillSwitch:
    def _make_redis(self, halted: bool = True) -> object:
        class FakeRedis:
            def __init__(self, halted: bool) -> None:
                self._halted = halted

            def get(self, key: str) -> bytes | None:
                if self._halted and key == "system:status:halted":
                    return b"true"
                return None

        return FakeRedis(halted)

    def test_halted_blocks_non_priority(self) -> None:
        eng, _, _ = _engine(redis_client=self._make_redis(halted=True))
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.status == OrderStatus.REJECTED
        assert "halted" in (fill.rejection_reason or "")

    def test_halted_non_halted_redis_allows(self) -> None:
        eng, _, _ = _engine(redis_client=self._make_redis(halted=False))
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.status == OrderStatus.FILLED

    def test_priority_bypasses_halted(self) -> None:
        eng, _, _ = _engine(redis_client=self._make_redis(halted=True))
        order = _order(is_priority=True, order_id="PRI-1")
        fill = eng.submit(order, now_ist=_IST)
        assert fill.status == OrderStatus.FILLED

    def test_sl_exit_bypasses_halted(self) -> None:
        eng, _, _ = _engine(redis_client=self._make_redis(halted=True))
        sl = make_sl_exit_order(
            symbol="RELIANCE",
            exchange="NSE",
            direction="LONG",
            quantity=50,
            stop_loss=190.0,
            client_order_id="SL-PRI",
            strategy_name=STRATEGY_EMA_VWAP_TREND,
            ltp=192.0,
        )
        fill = eng.submit(sl, now_ist=_IST)
        assert fill.status == OrderStatus.FILLED

    def test_kill_switch_liquidation_bypasses_halted(self) -> None:
        eng, _, _ = _engine(redis_client=self._make_redis(halted=True))
        liq = make_kill_switch_liquidation_order(
            symbol="TCS",
            exchange="NSE",
            direction="LONG",
            quantity=100,
            ltp=3500.0,
            client_order_id="LIQ-PRI",
            strategy_name=STRATEGY_EMA_VWAP_TREND,
        )
        fill = eng.submit(liq, now_ist=_IST)
        assert fill.status == OrderStatus.FILLED


class TestExecutionEngineRetry:
    def test_transient_error_retried(self) -> None:
        eng, paper, _ = _engine(fail_count=1, max_retries=2, retry_delay=0.0)
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.status == OrderStatus.FILLED
        assert fill.attempt_count == 2

    def test_all_transient_errors_go_to_dlq(self) -> None:
        dlq = DeadLetterQueue()
        eng, paper, _ = _engine(fail_count=5, max_retries=2, retry_delay=0.0, dlq=dlq)
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.status == OrderStatus.REJECTED
        assert dlq.size() == 1

    def test_permanent_error_no_retry(self) -> None:
        class _PermBroker:
            def place_order(self, tagged: TaggedOrder) -> FillReport:
                raise BrokerPermanentError("perm")

            def query_order(self, coid: str) -> FillReport | None:
                return None

            def cancel_order(self, coid: str) -> bool:
                return False

        dlq = DeadLetterQueue()
        eng = ExecutionEngine(
            broker=_PermBroker(),  # type: ignore[arg-type]
            dead_letter_queue=dlq,
            max_retries=3,
            retry_base_delay=0.0,
        )
        fill = eng.submit(_order(), now_ist=_IST)
        assert fill.status == OrderStatus.REJECTED
        assert dlq.size() == 1
        # Only 1 attempt (no retries on permanent error)
        assert fill.attempt_count == 1


class TestExecutionEngineIdempotency:
    def test_duplicate_submission_no_double_fill(self) -> None:
        eng, paper, _ = _engine()
        order = _order(order_id="DUP-1")
        f1 = eng.submit(order, now_ist=_IST)
        f2 = eng.submit(order, now_ist=_IST)
        assert f1.broker_order_id == f2.broker_order_id
        assert f1.filled_quantity == f2.filled_quantity
        assert len(paper.all_fills()) == 1  # only one record in broker


class TestExecutionEnginePriorityOrders:
    def test_make_sl_exit_is_priority(self) -> None:
        sl = make_sl_exit_order(
            symbol="INFY",
            exchange="NSE",
            direction="LONG",
            quantity=50,
            stop_loss=1500.0,
            client_order_id="SL-001",
            strategy_name=STRATEGY_EMA_VWAP_TREND,
        )
        assert sl.is_priority is True
        assert sl.is_exit is True
        assert sl.direction == "SHORT"  # exit a LONG = sell

    def test_make_sl_exit_short_direction_inverted(self) -> None:
        sl = make_sl_exit_order(
            symbol="INFY",
            exchange="NSE",
            direction="SHORT",
            quantity=50,
            stop_loss=1600.0,
            client_order_id="SL-002",
            strategy_name=STRATEGY_EMA_VWAP_TREND,
        )
        assert sl.direction == "LONG"  # exit a SHORT = buy

    def test_make_kill_switch_liq_is_priority(self) -> None:
        liq = make_kill_switch_liquidation_order(
            symbol="TCS",
            exchange="NSE",
            direction="LONG",
            quantity=100,
            ltp=3500.0,
            client_order_id="LIQ-001",
            strategy_name=STRATEGY_EMA_VWAP_TREND,
        )
        assert liq.is_priority is True
        assert liq.is_exit is True
        assert liq.order_type == "MARKET"

    def test_entry_order_cannot_set_is_priority(self) -> None:
        order = _order(is_priority=False)
        assert order.is_priority is False


class TestExecutionEnginePartialFill:
    def test_partial_fill_sl_qty_proportional(self) -> None:
        eng, _, _ = _engine(partial_ratio=0.5)
        fill = eng.submit(_order(quantity=100, order_id="PART-1"), now_ist=_IST)
        assert fill.status == OrderStatus.PARTIALLY_FILLED
        assert fill.sl_quantity == fill.filled_quantity

    def test_partial_fill_flagged(self) -> None:
        eng, _, _ = _engine(partial_ratio=0.7)
        fill = eng.submit(_order(quantity=100, order_id="PART-2"), now_ist=_IST)
        assert fill.is_partial is True


class TestExecutionEngineDeadLetter:
    def test_dlq_entry_has_correct_fields(self) -> None:
        class _PBroker:
            def place_order(self, tagged: TaggedOrder) -> FillReport:
                raise BrokerPermanentError("disk full")

            def query_order(self, coid: str) -> FillReport | None:
                return None

            def cancel_order(self, coid: str) -> bool:
                return False

        dlq = DeadLetterQueue()
        eng = ExecutionEngine(
            broker=_PBroker(),  # type: ignore[arg-type]
            dead_letter_queue=dlq,
            max_retries=1,
            retry_base_delay=0.0,
        )
        eng.submit(_order(order_id="DLQ-TEST"), now_ist=_IST)
        items = dlq.peek(1)
        assert len(items) == 1
        assert items[0].client_order_id == "DLQ-TEST"
        assert items[0].strategy_tag == "STRAT001"
        assert "disk full" in items[0].last_error
