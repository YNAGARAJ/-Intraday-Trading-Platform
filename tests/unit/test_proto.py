"""Protobuf schema import and round-trip serialization tests."""

from shared.proto import messages_pb2


def test_signal_generated_roundtrip() -> None:
    msg = messages_pb2.SignalGenerated(
        signal_id="sig-1",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BUY",
        confidence=0.82,
        entry_price=2450.5,
        stop_loss=2410.0,
        target1=2510.0,
        target2=2580.0,
        atr=18.3,
        confirming_indicators=["EMA_CROSS", "RSI"],
        confirming_timeframes=["5m", "15m"],
        candlestick_pattern="BULLISH_ENGULFING",
        strategy_id="STRAT001",
        generated_at_ms=1_700_000_000_000,
        expires_at_ms=1_700_000_060_000,
        regime="BULL_TREND",
    )

    decoded = messages_pb2.SignalGenerated()
    decoded.ParseFromString(msg.SerializeToString())

    assert decoded.signal_id == "sig-1"
    assert decoded.strategy_id == "STRAT001"
    assert list(decoded.confirming_indicators) == ["EMA_CROSS", "RSI"]
    assert decoded.regime == "BULL_TREND"


def test_order_intent_is_priority_defaults_false() -> None:
    msg = messages_pb2.OrderIntent(symbol="RELIANCE", client_order_id="abc-123")
    assert msg.is_priority is False


def test_order_intent_roundtrip_with_priority_flag() -> None:
    msg = messages_pb2.OrderIntent(
        signal_id="sig-1",
        symbol="RELIANCE",
        exchange="NSE",
        side="SELL",
        order_type="MPP",
        quantity=10,
        client_order_id="client-order-001",
        is_priority=True,
    )

    decoded = messages_pb2.OrderIntent()
    decoded.ParseFromString(msg.SerializeToString())

    assert decoded.client_order_id == "client-order-001"
    assert decoded.is_priority is True


def test_order_filled_echoes_client_order_id() -> None:
    msg = messages_pb2.OrderFilled(
        order_id="order-1",
        client_order_id="client-order-001",
        symbol="RELIANCE",
        status="FILLED",
        filled_quantity=10,
        filled_price=2451.0,
    )
    decoded = messages_pb2.OrderFilled()
    decoded.ParseFromString(msg.SerializeToString())
    assert decoded.client_order_id == "client-order-001"


def test_reconciliation_mismatch_roundtrip() -> None:
    msg = messages_pb2.ReconciliationMismatch(
        symbol="RELIANCE",
        field="quantity",
        internal_value="10",
        broker_value="8",
        detected_at_ms=1_700_000_000_000,
    )
    decoded = messages_pb2.ReconciliationMismatch()
    decoded.ParseFromString(msg.SerializeToString())
    assert decoded.field == "quantity"
    assert decoded.internal_value == "10"
    assert decoded.broker_value == "8"


def test_kill_switch_activated_roundtrip() -> None:
    msg = messages_pb2.KillSwitchActivated(
        trigger="DAILY_LOSS_LIMIT",
        triggered_by="circuit_breaker.py",
        daily_pnl_pct=-2.3,
        timestamp_ms=1_700_000_000_000,
    )
    decoded = messages_pb2.KillSwitchActivated()
    decoded.ParseFromString(msg.SerializeToString())
    assert decoded.trigger == "DAILY_LOSS_LIMIT"
    assert round(decoded.daily_pnl_pct, 1) == -2.3
