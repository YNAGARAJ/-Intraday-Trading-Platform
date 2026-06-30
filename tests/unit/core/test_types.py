"""Tests for shared.core.types: enum membership and string values."""

from shared.core.types import (
    AppId,
    BrokerName,
    Exchange,
    MarketRegime,
    OrderSide,
    OrderStatus,
    OrderType,
    SessionState,
    TradingMode,
)


def test_trading_mode_values() -> None:
    assert {m.value for m in TradingMode} == {"PAPER", "LIVE"}


def test_app_id_values() -> None:
    assert {a.value for a in AppId} == {"india", "australia"}


def test_exchange_values() -> None:
    assert {e.value for e in Exchange} == {"NSE", "BSE", "ASX"}


def test_market_regime_includes_high_vol_chaos() -> None:
    assert MarketRegime.HIGH_VOL_CHAOS.value == "HIGH_VOL_CHAOS"
    assert {r.value for r in MarketRegime} == {
        "BULL_TREND",
        "BEAR_TREND",
        "MEAN_REVERTING",
        "HIGH_VOL_CHAOS",
    }


def test_session_state_full_cycle_present() -> None:
    assert {s.value for s in SessionState} == {
        "CLOSED",
        "PRE_MARKET",
        "OPEN",
        "SNAPSHOT_WINDOW",
        "APPROACHING_CLOSE",
    }


def test_order_side_values() -> None:
    assert {s.value for s in OrderSide} == {"BUY", "SELL"}


def test_order_type_values() -> None:
    assert {t.value for t in OrderType} == {"LIMIT", "MPP", "SL"}


def test_order_status_lifecycle_values() -> None:
    assert {s.value for s in OrderStatus} == {
        "PENDING",
        "PLACED",
        "FILLED",
        "REJECTED",
        "CANCELLED",
    }


def test_broker_name_values() -> None:
    assert {b.value for b in BrokerName} == {"paper", "kite", "ibkr"}


def test_enums_are_str_subclasses_for_json_compat() -> None:
    assert isinstance(TradingMode.PAPER, str)
    assert isinstance(MarketRegime.HIGH_VOL_CHAOS, str)
