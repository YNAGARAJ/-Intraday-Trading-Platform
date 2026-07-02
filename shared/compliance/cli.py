"""CLI for M13 Compliance & Regulatory Engine.

VERIFY command: runs 20 non-compliant and compliant scenarios; all
non-compliant orders must be blocked, all compliant orders must pass.

Usage:
    python -m shared.compliance verify
    python -m shared.compliance verify --scenario missing_strategy_id
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import datetime

from shared.compliance.engine import ComplianceEngine
from shared.compliance.kill_switch import KillSwitchManager
from shared.compliance.models import OrderIntent, RecentOrder
from shared.compliance.strategy_registry import (
    STRATEGY_EMA_VWAP_TREND,
    STRATEGY_MEAN_REVERT_PIVOT,
    STRATEGY_MOMENTUM_RSI,
    STRATEGY_ORB_BREAKOUT,
    STRATEGY_ORDER_FLOW_ABSORPTION,
    StrategyRegistry,
)

# ---------------------------------------------------------------------------
# Shared test fixture builders
# ---------------------------------------------------------------------------

_NOW_MS = int(time.time() * 1000)
_IST_OPEN = datetime(2026, 7, 2, 10, 30, 0)  # 10:30 IST — well within market hours
_IST_AFTER_SQUAREOFF = datetime(2026, 7, 2, 15, 15, 0)  # 15:15 IST — after 15:10
_AEST_OPEN = datetime(2026, 7, 2, 11, 0, 0)  # 11:00 AEST — normal session
_AEST_AFTER_CUTOFF = datetime(2026, 7, 2, 16, 30, 0)  # 16:30 AEST — after cutoff


def _nse_entry(
    strategy_name: str = STRATEGY_EMA_VWAP_TREND,
    order_type: str = "LIMIT",
    price: float | None = 2450.0,
    ltp: float | None = 2450.0,
    notional_value: float = 24500.0,
    capital: float = 100_000.0,
    mwpl_pct: float | None = None,
    is_exit: bool = False,
) -> OrderIntent:
    return OrderIntent(
        symbol="RELIANCE",
        exchange="NSE",
        direction="LONG",
        order_type=order_type,
        quantity=10,
        price=price,
        stop_loss=2413.0,
        strategy_name=strategy_name,
        client_order_id="TEST-NSE-001",
        ltp=ltp,
        notional_value=notional_value,
        capital=capital,
        is_exit=is_exit,
        mwpl_pct=mwpl_pct,
    )


def _asx_entry(
    direction: str = "LONG",
    is_exit: bool = False,
    strategy_name: str = STRATEGY_EMA_VWAP_TREND,
) -> OrderIntent:
    return OrderIntent(
        symbol="BHP",
        exchange="ASX",
        direction=direction,
        order_type="LIMIT",
        quantity=100,
        price=45.0,
        stop_loss=43.5,
        strategy_name=strategy_name,
        client_order_id="TEST-ASX-001",
        ltp=45.0,
        notional_value=4500.0,
        capital=100_000.0,
        is_exit=is_exit,
    )


# ---------------------------------------------------------------------------
# 20 VERIFY scenarios
# ---------------------------------------------------------------------------

Scenario = tuple[str, bool, str]  # (name, expect_approved, description)


def _scenario_01_missing_strategy_id(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: unknown strategy name → rejected (NO_STRATEGY_ID)."""
    order = _nse_entry(strategy_name="UNKNOWN_ALGO")
    dec = engine.check(order, now_ist=_IST_OPEN)
    codes = [v.code for v in dec.violations]
    return dec.approved, "NO_STRATEGY_ID" in codes


def _scenario_02_ema_vwap_trend(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: EMA_VWAP_TREND → approved with STRAT001 tag."""
    order = _nse_entry(strategy_name=STRATEGY_EMA_VWAP_TREND)
    dec = engine.check(order, now_ist=_IST_OPEN)
    tag = dec.tagged_order.strategy_tag if dec.tagged_order else ""
    return dec.approved, tag == "STRAT001"


def _scenario_03_orb_breakout(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: ORB_BREAKOUT → approved with STRAT002 tag."""
    order = _nse_entry(strategy_name=STRATEGY_ORB_BREAKOUT)
    dec = engine.check(order, now_ist=_IST_OPEN)
    tag = dec.tagged_order.strategy_tag if dec.tagged_order else ""
    return dec.approved, tag == "STRAT002"


def _scenario_04_momentum_rsi(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: MOMENTUM_RSI → approved with STRAT003 tag."""
    order = _nse_entry(strategy_name=STRATEGY_MOMENTUM_RSI)
    dec = engine.check(order, now_ist=_IST_OPEN)
    tag = dec.tagged_order.strategy_tag if dec.tagged_order else ""
    return dec.approved, tag == "STRAT003"


def _scenario_05_mean_revert_pivot(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: MEAN_REVERT_PIVOT → approved with STRAT004 tag."""
    order = _nse_entry(strategy_name=STRATEGY_MEAN_REVERT_PIVOT)
    dec = engine.check(order, now_ist=_IST_OPEN)
    tag = dec.tagged_order.strategy_tag if dec.tagged_order else ""
    return dec.approved, tag == "STRAT004"


def _scenario_06_order_flow_absorption(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: ORDER_FLOW_ABSORPTION → approved with STRAT005 tag."""
    order = _nse_entry(strategy_name=STRATEGY_ORDER_FLOW_ABSORPTION)
    dec = engine.check(order, now_ist=_IST_OPEN)
    tag = dec.tagged_order.strategy_tag if dec.tagged_order else ""
    return dec.approved, tag == "STRAT005"


def _scenario_07_generic_algo_id() -> tuple[bool, bool]:
    """India: USE_GENERIC_ALGO_ID=true → approved with GENALG01 tag."""
    generic_engine = ComplianceEngine(registry=StrategyRegistry(use_generic=True))
    order = _nse_entry(strategy_name="UNKNOWN_ALGO")
    dec = generic_engine.check(order, now_ist=_IST_OPEN)
    tag = dec.tagged_order.strategy_tag if dec.tagged_order else ""
    return dec.approved, tag == "GENALG01"


def _scenario_08_market_order_buy_mpp(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: MARKET buy → converted to MPP limit at LTP + 0.25%."""
    order = _nse_entry(order_type="MARKET", price=None, ltp=2450.0)
    dec = engine.check(order, now_ist=_IST_OPEN)
    if dec.tagged_order is None:
        return dec.approved, False
    expected_mpp = round(2450.0 * 1.0025, 2)
    type_ok = dec.tagged_order.effective_order_type == "MPP"
    price_ok = dec.tagged_order.mpp_price == expected_mpp
    return dec.approved, type_ok and price_ok


def _scenario_09_market_order_sell_mpp(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: MARKET sell → converted to MPP limit at LTP - 0.25%."""
    order = OrderIntent(
        symbol="RELIANCE",
        exchange="NSE",
        direction="SHORT",
        order_type="MARKET",
        quantity=10,
        price=None,
        stop_loss=2490.0,
        strategy_name=STRATEGY_EMA_VWAP_TREND,
        client_order_id="TEST-NSE-SHORT",
        ltp=2450.0,
        notional_value=24500.0,
        capital=100_000.0,
    )
    dec = engine.check(order, now_ist=_IST_OPEN)
    if dec.tagged_order is None:
        return dec.approved, False
    expected_mpp = round(2450.0 * 0.9975, 2)
    type_ok = dec.tagged_order.effective_order_type == "MPP"
    price_ok = dec.tagged_order.mpp_price == expected_mpp
    return dec.approved, type_ok and price_ok


def _scenario_10_leverage_exceeded(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: leverage > 5× → rejected (LEVERAGE_EXCEEDED)."""
    order = _nse_entry(notional_value=600_001.0, capital=100_000.0)
    dec = engine.check(order, now_ist=_IST_OPEN)
    codes = [v.code for v in dec.violations]
    return dec.approved, "LEVERAGE_EXCEEDED" in codes


def _scenario_11_mwpl_exceeded(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: MWPL > 90% → rejected (MWPL_EXCEEDED)."""
    order = _nse_entry(mwpl_pct=91.5)
    dec = engine.check(order, now_ist=_IST_OPEN)
    codes = [v.code for v in dec.violations]
    return dec.approved, "MWPL_EXCEEDED" in codes


def _scenario_12_force_square_off(engine: ComplianceEngine) -> tuple[bool, bool]:
    """India: new entry at 15:15 IST → rejected (FORCE_SQUARE_OFF)."""
    order = _nse_entry()
    dec = engine.check(order, now_ist=_IST_AFTER_SQUAREOFF)
    codes = [v.code for v in dec.violations]
    return dec.approved, "FORCE_SQUARE_OFF" in codes


def _scenario_13_wash_trading(engine: ComplianceEngine) -> tuple[bool, bool]:
    """Australia: opposing direction placed 30 s ago → rejected (WASH_TRADING)."""
    order = _asx_entry(direction="LONG")
    recent = [
        RecentOrder(symbol="BHP", direction="SHORT", placed_at_ms=_NOW_MS - 30_000)
    ]
    dec = engine.check(order, recent_orders=recent, now_ms=_NOW_MS)
    codes = [v.code for v in dec.violations]
    return dec.approved, "WASH_TRADING" in codes


def _scenario_14_layering(engine: ComplianceEngine) -> tuple[bool, bool]:
    """Australia: opposing direction already pending → rejected (LAYERING)."""
    order = _asx_entry(direction="LONG")
    pending = [
        RecentOrder(symbol="BHP", direction="SHORT", placed_at_ms=_NOW_MS - 5_000)
    ]
    dec = engine.check(order, pending_orders=pending, now_ms=_NOW_MS)
    codes = [v.code for v in dec.violations]
    return dec.approved, "LAYERING" in codes


def _scenario_15_short_sell_not_approved(engine: ComplianceEngine) -> tuple[bool, bool]:
    """Australia: unapproved short sell → SHORT_SELL_NOT_APPROVED."""
    order = _asx_entry(direction="SHORT")
    dec = engine.check(
        order, approved_short_list=frozenset({"CBA", "ANZ"}), now_ms=_NOW_MS
    )
    codes = [v.code for v in dec.violations]
    return dec.approved, "SHORT_SELL_NOT_APPROVED" in codes


def _scenario_16_short_sell_approved(engine: ComplianceEngine) -> tuple[bool, bool]:
    """Australia: short sell on approved symbol → passes."""
    order = _asx_entry(direction="SHORT")
    dec = engine.check(
        order, approved_short_list=frozenset({"BHP", "CBA"}), now_ms=_NOW_MS
    )
    return dec.approved, dec.violations == []


def _scenario_17_staggered_open(engine: ComplianceEngine) -> tuple[bool, bool]:
    """Australia: entry within 15 min of group open → STAGGERED_OPEN_NOISE_FILTER."""
    order = _asx_entry()
    group_open_ms = _NOW_MS - (5 * 60 * 1000)  # only 5 min ago
    dec = engine.check(order, group_open_ms=group_open_ms, now_ms=_NOW_MS)
    codes = [v.code for v in dec.violations]
    return dec.approved, "STAGGERED_OPEN_NOISE_FILTER" in codes


def _scenario_18_post_close_cutoff(engine: ComplianceEngine) -> tuple[bool, bool]:
    """Australia: new entry after 16:21:30 AEST → rejected (POST_CLOSE_CUTOFF)."""
    order = _asx_entry()
    dec = engine.check(order, now_aest=_AEST_AFTER_CUTOFF, now_ms=_NOW_MS)
    codes = [v.code for v in dec.violations]
    return dec.approved, "POST_CLOSE_CUTOFF" in codes


def _scenario_19_kill_switch_tier1() -> tuple[bool, bool]:
    """Kill switch Tier 1 (circuit breaker) sets SYSTEM_HALTED in memory."""
    ks = KillSwitchManager(redis_client=None)
    event = ks.trigger_tier1(daily_pnl_pct=-2.1)
    halted_after = ks.is_halted
    tier_ok = event.tier == 1
    priority_ok = event.is_priority is True
    return halted_after, tier_ok and priority_ok


def _scenario_20_kill_switch_tiers_23() -> tuple[bool, bool]:
    """Kill switch Tier 2 (external) and Tier 3 (heartbeat) also set SYSTEM_HALTED."""
    ks2 = KillSwitchManager(redis_client=None)
    ev2 = ks2.trigger_tier2("telegram_bot")
    t2_ok = ev2.tier == 2 and ev2.is_priority is True and ks2.is_halted

    ks3 = KillSwitchManager(redis_client=None)
    ev3 = ks3.trigger_tier3("SignalAgent", 2)
    t3_ok = ev3.tier == 3 and ev3.is_priority is True and ks3.is_halted

    return t2_ok and t3_ok, True


_SCENARIO_TABLE: list[tuple[str, str, bool]] = [
    ("01_missing_strategy_id", "India: unknown strategy → NO_STRATEGY_ID", False),
    ("02_ema_vwap_trend", "India: EMA_VWAP_TREND → approved STRAT001", True),
    ("03_orb_breakout", "India: ORB_BREAKOUT → approved STRAT002", True),
    ("04_momentum_rsi", "India: MOMENTUM_RSI → approved STRAT003", True),
    ("05_mean_revert_pivot", "India: MEAN_REVERT_PIVOT → STRAT004", True),
    ("06_order_flow_absorption", "India: ORDER_FLOW_ABSORPTION → STRAT005", True),
    ("07_generic_algo_id", "India: USE_GENERIC_ALGO_ID=true → GENALG01", True),
    ("08_market_order_buy_mpp", "India: MARKET buy → MPP at LTP+0.25%", True),
    ("09_market_order_sell_mpp", "India: MARKET sell → MPP at LTP-0.25%", True),
    ("10_leverage_exceeded", "India: leverage > 5× → LEVERAGE_EXCEEDED", False),
    ("11_mwpl_exceeded", "India: OI > 90% MWPL → MWPL_EXCEEDED", False),
    ("12_force_square_off", "India: entry at 15:15 IST → FORCE_SQUARE_OFF", False),
    ("13_wash_trading", "Australia: opposing trade 30s ago → WASH_TRADING", False),
    ("14_layering", "Australia: opposing order pending → LAYERING", False),
    (
        "15_short_sell_not_approved",
        "Australia: unapproved short → SHORT_SELL_NOT_APPROVED",
        False,
    ),
    ("16_short_sell_approved", "Australia: approved short BHP → passes", True),
    (
        "17_staggered_open",
        "Australia: entry 5min after open → STAGGERED_OPEN_NOISE_FILTER",
        False,
    ),
    ("18_post_close_cutoff", "Australia: after 16:21:30 → POST_CLOSE_CUTOFF", False),
    ("19_kill_switch_tier1", "Kill switch Tier 1 → SYSTEM_HALTED", True),
    ("20_kill_switch_tiers_23", "Kill switch Tier 2+3 → SYSTEM_HALTED", True),
]


def _run_scenario(name: str, engine: ComplianceEngine) -> tuple[bool, bool]:
    """Dispatch to the correct scenario function by name."""
    dispatch: dict[str, Callable[[], tuple[bool, bool]]] = {
        "01_missing_strategy_id": lambda: _scenario_01_missing_strategy_id(engine),
        "02_ema_vwap_trend": lambda: _scenario_02_ema_vwap_trend(engine),
        "03_orb_breakout": lambda: _scenario_03_orb_breakout(engine),
        "04_momentum_rsi": lambda: _scenario_04_momentum_rsi(engine),
        "05_mean_revert_pivot": lambda: _scenario_05_mean_revert_pivot(engine),
        "06_order_flow_absorption": lambda: _scenario_06_order_flow_absorption(engine),
        "07_generic_algo_id": lambda: _scenario_07_generic_algo_id(),
        "08_market_order_buy_mpp": lambda: _scenario_08_market_order_buy_mpp(engine),
        "09_market_order_sell_mpp": lambda: _scenario_09_market_order_sell_mpp(engine),
        "10_leverage_exceeded": lambda: _scenario_10_leverage_exceeded(engine),
        "11_mwpl_exceeded": lambda: _scenario_11_mwpl_exceeded(engine),
        "12_force_square_off": lambda: _scenario_12_force_square_off(engine),
        "13_wash_trading": lambda: _scenario_13_wash_trading(engine),
        "14_layering": lambda: _scenario_14_layering(engine),
        "15_short_sell_not_approved": (
            lambda: _scenario_15_short_sell_not_approved(engine)
        ),
        "16_short_sell_approved": lambda: _scenario_16_short_sell_approved(engine),
        "17_staggered_open": lambda: _scenario_17_staggered_open(engine),
        "18_post_close_cutoff": lambda: _scenario_18_post_close_cutoff(engine),
        "19_kill_switch_tier1": lambda: _scenario_19_kill_switch_tier1(),
        "20_kill_switch_tiers_23": lambda: _scenario_20_kill_switch_tiers_23(),
    }
    fn = dispatch.get(name)
    if fn is None:
        raise ValueError(f"Unknown scenario: {name}")
    return fn()


def cmd_verify(args: argparse.Namespace) -> int:
    """Run VERIFY scenarios and print results.

    Returns:
        0 on all pass, 1 on any failure.
    """
    engine = ComplianceEngine()
    target = getattr(args, "scenario", "all")
    table = (
        _SCENARIO_TABLE
        if target == "all"
        else [(n, d, e) for (n, d, e) in _SCENARIO_TABLE if n == target]
    )
    if not table:
        print(f"Unknown scenario: {target}")
        return 1

    passed = 0
    failed = 0
    for name, description, expect_approved in table:
        result_approved, extra_ok = _run_scenario(name, engine)
        outcome_ok = result_approved == expect_approved and extra_ok
        status = "PASS" if outcome_ok else "FAIL"
        approved_label = "approved" if result_approved else "blocked"
        expected_label = "approved" if expect_approved else "blocked"
        print(
            f"  [{status}] {name}: {description}"
            + (
                ""
                if outcome_ok
                else f" (got {approved_label}, expected {expected_label})"
            )
        )
        if outcome_ok:
            passed += 1
        else:
            failed += 1

    print()
    if failed == 0:
        print(f"VERIFY PASS — {passed}/20 scenarios correct.")
    else:
        print(f"VERIFY FAIL — {failed} scenario(s) failed.")
    return 0 if failed == 0 else 1


def main() -> None:
    """Entry point for ``python -m shared.compliance``."""
    parser = argparse.ArgumentParser(
        description="M13 Compliance & Regulatory Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")
    verify_parser = sub.add_parser("verify", help="Run VERIFY scenarios")
    verify_parser.add_argument(
        "--scenario",
        default="all",
        choices=["all"] + [n for (n, _, _) in _SCENARIO_TABLE],
        help="Run a single scenario or all (default: all)",
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    if args.command == "verify":
        sys.exit(cmd_verify(args))
