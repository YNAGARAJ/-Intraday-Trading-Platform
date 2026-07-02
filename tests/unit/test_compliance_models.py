"""Unit tests for M13 compliance data models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from shared.compliance.models import (
    ComplianceDecision,
    ComplianceViolation,
    KillSwitchEvent,
    OrderIntent,
    RecentOrder,
    TaggedOrder,
)


class TestOrderIntent:
    def _make(self, **kwargs: object) -> OrderIntent:
        defaults: dict[str, object] = {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "direction": "LONG",
            "order_type": "LIMIT",
            "quantity": 10,
            "price": 2450.0,
            "stop_loss": 2413.0,
            "strategy_name": "EMA_VWAP_TREND",
            "client_order_id": "CLI-001",
        }
        defaults.update(kwargs)
        return OrderIntent(**defaults)  # type: ignore[arg-type]

    def test_minimal_fields(self) -> None:
        o = self._make()
        assert o.symbol == "RELIANCE"
        assert o.exchange == "NSE"
        assert o.is_exit is False

    def test_ltp_default_none(self) -> None:
        o = self._make()
        assert o.ltp is None

    def test_frozen(self) -> None:
        o = self._make()
        with pytest.raises(FrozenInstanceError):
            o.symbol = "X"  # type: ignore[misc]

    def test_exit_flag(self) -> None:
        o = self._make(is_exit=True)
        assert o.is_exit is True

    def test_mwpl_pct_none_default(self) -> None:
        o = self._make()
        assert o.mwpl_pct is None


class TestTaggedOrder:
    def test_mpp_fields(self) -> None:
        base = OrderIntent(
            symbol="RELIANCE",
            exchange="NSE",
            direction="LONG",
            order_type="MARKET",
            quantity=10,
            price=None,
            stop_loss=2413.0,
            strategy_name="EMA_VWAP_TREND",
            client_order_id="CLI-002",
            ltp=2450.0,
        )
        tagged = TaggedOrder(
            original=base,
            strategy_tag="STRAT001",
            effective_order_type="MPP",
            mpp_price=2456.13,
        )
        assert tagged.effective_order_type == "MPP"
        assert tagged.mpp_price == 2456.13
        assert tagged.strategy_tag == "STRAT001"
        assert tagged.original.symbol == "RELIANCE"


class TestComplianceViolation:
    def test_fields(self) -> None:
        v = ComplianceViolation(code="NO_STRATEGY_ID", detail="Missing tag")
        assert v.code == "NO_STRATEGY_ID"
        assert v.detail == "Missing tag"

    def test_frozen(self) -> None:
        v = ComplianceViolation(code="X", detail="y")
        with pytest.raises(FrozenInstanceError):
            v.code = "Z"  # type: ignore[misc]


class TestComplianceDecision:
    def test_approved(self) -> None:
        base = OrderIntent(
            symbol="BHP",
            exchange="ASX",
            direction="LONG",
            order_type="LIMIT",
            quantity=100,
            price=45.0,
            stop_loss=43.5,
            strategy_name="EMA_VWAP_TREND",
            client_order_id="ASX-001",
        )
        tagged = TaggedOrder(
            original=base, strategy_tag="STRAT001", effective_order_type="LIMIT"
        )
        dec = ComplianceDecision(
            approved=True, violations=[], tagged_order=tagged, audit_id="abc123"
        )
        assert dec.approved is True
        assert dec.tagged_order is tagged
        assert dec.violations == []

    def test_rejected(self) -> None:
        dec = ComplianceDecision(
            approved=False,
            violations=[ComplianceViolation(code="X", detail="y")],
            tagged_order=None,
            audit_id="def456",
        )
        assert dec.approved is False
        assert dec.tagged_order is None
        assert len(dec.violations) == 1


class TestKillSwitchEvent:
    def test_is_priority_always_true(self) -> None:
        ev = KillSwitchEvent(tier=1, reason="test", triggered_at_ms=0)
        assert ev.is_priority is True

    def test_is_priority_not_settable_by_caller(self) -> None:
        """is_priority is a frozen field — callers cannot override it."""
        ev = KillSwitchEvent(tier=2, reason="x", triggered_at_ms=0)
        with pytest.raises(FrozenInstanceError):
            ev.is_priority = False  # type: ignore[misc]

    def test_invalid_tier(self) -> None:
        with pytest.raises(ValueError, match="tier must be 1, 2, or 3"):
            KillSwitchEvent(tier=4, reason="bad", triggered_at_ms=0)

    def test_all_valid_tiers(self) -> None:
        for tier in (1, 2, 3):
            ev = KillSwitchEvent(tier=tier, reason="ok", triggered_at_ms=1_000)
            assert ev.tier == tier


class TestRecentOrder:
    def test_fields(self) -> None:
        r = RecentOrder(symbol="BHP", direction="LONG", placed_at_ms=1_000_000)
        assert r.symbol == "BHP"
        assert r.direction == "LONG"
        assert r.placed_at_ms == 1_000_000
