"""Unit tests for M14 PaperBroker."""

from __future__ import annotations

import threading

import pytest

from shared.compliance.models import OrderIntent, TaggedOrder
from shared.execution.brokers.base import BrokerTransientError
from shared.execution.brokers.paper import PaperBroker
from shared.execution.models import OrderStatus


def _tagged(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    direction: str = "LONG",
    quantity: int = 100,
    price: float = 200.0,
    stop_loss: float = 190.0,
    client_order_id: str = "ORD-TEST",
    strategy_tag: str = "STRAT001",
    mpp_price: float | None = None,
) -> TaggedOrder:
    original = OrderIntent(
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        order_type="LIMIT",
        quantity=quantity,
        price=price,
        stop_loss=stop_loss,
        strategy_name="EMA_VWAP_TREND",
        client_order_id=client_order_id,
        ltp=price,
    )
    return TaggedOrder(
        original=original,
        strategy_tag=strategy_tag,
        effective_order_type="LIMIT",
        mpp_price=mpp_price,
    )


class TestPaperBrokerFullFill:
    def test_fills_immediately(self) -> None:
        broker = PaperBroker()
        t = _tagged()
        fill = broker.place_order(t)
        assert fill.status == OrderStatus.FILLED
        assert fill.filled_quantity == 100
        assert fill.requested_quantity == 100
        assert fill.is_partial is False
        assert fill.sl_quantity == 100

    def test_fill_price_uses_order_price(self) -> None:
        broker = PaperBroker()
        t = _tagged(price=350.0)
        fill = broker.place_order(t)
        assert fill.filled_price == 350.0

    def test_mpp_price_overrides_fill_price(self) -> None:
        broker = PaperBroker()
        t = _tagged(price=200.0, mpp_price=200.5)
        fill = broker.place_order(t)
        assert fill.filled_price == 200.5

    def test_broker_id_assigned(self) -> None:
        broker = PaperBroker()
        fill = broker.place_order(_tagged())
        assert fill.broker_order_id is not None
        assert fill.broker_order_id.startswith("PAPER-")

    def test_sequential_broker_ids_unique(self) -> None:
        broker = PaperBroker()
        f1 = broker.place_order(_tagged(client_order_id="A"))
        f2 = broker.place_order(_tagged(client_order_id="B"))
        assert f1.broker_order_id != f2.broker_order_id

    def test_strategy_tag_propagated(self) -> None:
        broker = PaperBroker()
        fill = broker.place_order(_tagged(strategy_tag="STRAT003"))
        assert fill.strategy_tag == "STRAT003"


class TestPaperBrokerPartialFill:
    def test_partial_fill_ratio(self) -> None:
        broker = PaperBroker(partial_fill_ratio=0.5)
        t = _tagged(quantity=100)
        fill = broker.place_order(t)
        assert fill.status == OrderStatus.PARTIALLY_FILLED
        assert fill.filled_quantity == 50
        assert fill.is_partial is True
        assert fill.sl_quantity == 50  # sl_qty == filled_qty

    def test_partial_fill_sl_qty_matches_filled(self) -> None:
        broker = PaperBroker(partial_fill_ratio=0.3)
        fill = broker.place_order(_tagged(quantity=200))
        assert fill.sl_quantity == fill.filled_quantity

    def test_full_ratio_still_gives_filled(self) -> None:
        broker = PaperBroker(partial_fill_ratio=1.0)
        fill = broker.place_order(_tagged(quantity=100))
        assert fill.status == OrderStatus.FILLED

    def test_minimum_one_share(self) -> None:
        broker = PaperBroker(partial_fill_ratio=0.001)
        fill = broker.place_order(_tagged(quantity=100))
        assert fill.filled_quantity >= 1


class TestPaperBrokerIdempotency:
    def test_same_coid_returns_same_fill(self) -> None:
        broker = PaperBroker()
        t = _tagged(client_order_id="ORD-IDEM")
        f1 = broker.place_order(t)
        f2 = broker.place_order(t)
        assert f1.broker_order_id == f2.broker_order_id
        assert f1.filled_quantity == f2.filled_quantity

    def test_idempotent_does_not_increment_broker_seq(self) -> None:
        broker = PaperBroker()
        broker.place_order(_tagged(client_order_id="A"))
        broker.place_order(_tagged(client_order_id="A"))  # idempotent
        broker.place_order(_tagged(client_order_id="B"))
        fills = broker.all_fills()
        assert len(fills) == 2  # A and B only

    def test_query_returns_fill(self) -> None:
        broker = PaperBroker()
        broker.place_order(_tagged(client_order_id="Q1"))
        result = broker.query_order("Q1")
        assert result is not None
        assert result.client_order_id == "Q1"

    def test_query_unknown_returns_none(self) -> None:
        broker = PaperBroker()
        assert broker.query_order("NO-SUCH-ORDER") is None


class TestPaperBrokerTransientErrors:
    def test_fail_count_raises_transient(self) -> None:
        broker = PaperBroker(fail_count=2)
        t = _tagged()
        with pytest.raises(BrokerTransientError):
            broker.place_order(t)
        with pytest.raises(BrokerTransientError):
            broker.place_order(t)
        # Third call succeeds
        fill = broker.place_order(t)
        assert fill.status == OrderStatus.FILLED

    def test_zero_fail_count_no_errors(self) -> None:
        broker = PaperBroker(fail_count=0)
        fill = broker.place_order(_tagged())
        assert fill.status == OrderStatus.FILLED


class TestPaperBrokerCancel:
    def test_cancel_unknown_returns_false(self) -> None:
        broker = PaperBroker()
        assert broker.cancel_order("NO-SUCH") is False

    def test_cancel_filled_returns_false(self) -> None:
        broker = PaperBroker()
        broker.place_order(_tagged(client_order_id="FILL-1"))
        assert broker.cancel_order("FILL-1") is False

    def test_open_orders_empty_initially(self) -> None:
        broker = PaperBroker()
        assert broker.open_orders() == []

    def test_all_fills_includes_cancelled(self) -> None:
        broker = PaperBroker()
        broker.place_order(_tagged(client_order_id="X"))
        broker.cancel_order("X")  # Already filled → returns False, no change
        fills = broker.all_fills()
        assert len(fills) == 1


class TestPaperBrokerConcurrency:
    def test_thread_safe_submission(self) -> None:
        broker = PaperBroker()
        results: list[str | None] = []
        lock = threading.Lock()

        def submit(i: int) -> None:
            t = _tagged(client_order_id=f"ORD-{i:03d}")
            fill = broker.place_order(t)
            with lock:
                results.append(fill.broker_order_id)

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert len(results) == 20
        assert len(set(results)) == 20  # all unique broker IDs
