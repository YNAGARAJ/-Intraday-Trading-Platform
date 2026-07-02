"""India (NSE/BSE) compliance checks — SEBI April 2026 Framework.

All checks return ``list[ComplianceViolation]``.  An empty list means the check
passed.  The engine collects violations from all applicable checks and rejects
the order if any violations are present.

Regulatory context (as of build date):
- Strategy-ID / Generic Algo ID tagging: mandatory for all algo orders on NSE/BSE
  from April 1, 2026.
- MPP conversion: converting MARKET orders to protected limit structures is sound
  execution-quality practice; confirm with broker compliance whether an outright
  MARKET-order ban is itself a hard legal mandate before citing it as such in audit
  documentation (change-log item 5 in MASTER_BUILD_PROMPT_FINAL.MD).
- Max leverage 5× (20% upfront margin required).
- MWPL filter: exclude symbols where OI > 90% of Market Wide Position Limit.
- Force square-off: all positions closed by 15:10 IST (compliance cron, App 1).

All checks are pure functions: no I/O, no Redis, no network calls.  All external
state (MWPL %, current time, recent orders) must be pre-fetched by the caller.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from shared.core.constants import (
    FORCE_SQUARE_OFF_IST_HOUR,
    FORCE_SQUARE_OFF_IST_MINUTE,
    MAX_LEVERAGE,
    MPP_SLIPPAGE_BUFFER_PCT,
    MWPL_EXCLUSION_THRESHOLD_PCT,
)

if TYPE_CHECKING:
    from shared.compliance.models import ComplianceViolation, OrderIntent

INDIA_EXCHANGES: frozenset[str] = frozenset({"NSE", "BSE"})


def _v(code: str, detail: str) -> ComplianceViolation:
    from shared.compliance.models import ComplianceViolation  # noqa: PLC0415

    return ComplianceViolation(code=code, detail=detail)


def check_strategy_id(
    order: OrderIntent,
    strategy_tag: str | None,
) -> list[ComplianceViolation]:
    """Verify that a strategy tag was resolved.

    A ``None`` tag means the strategy name is unregistered — order is blocked
    before any broker call is made (mandatory, see SEBI April 2026 framework).

    Args:
        order: The order being checked.
        strategy_tag: Resolved compressed tag from ``StrategyRegistry.resolve()``,
            or ``None`` if the strategy name was not found.

    Returns:
        Empty list on pass; single-element list on violation.
    """
    if order.exchange not in INDIA_EXCHANGES:
        return []
    if strategy_tag is None:
        return [
            _v(
                "NO_STRATEGY_ID",
                f"Strategy '{order.strategy_name}' is not registered; "
                "order rejected before broker submission (SEBI April 2026).",
            )
        ]
    return []


def compute_mpp_price(order: OrderIntent) -> float | None:
    """Compute the Market Price Protection limit price for a MARKET-type order.

    For buys: ``ltp × (1 + buffer)``.
    For sells: ``ltp × (1 - buffer)``.

    Args:
        order: Order with ``order_type == 'MARKET'`` and a valid ``ltp``.

    Returns:
        MPP limit price, or ``None`` when LTP is unavailable.
    """
    if order.ltp is None or order.ltp <= 0.0:
        return None
    buf = MPP_SLIPPAGE_BUFFER_PCT / 100.0
    if order.direction == "LONG":
        return round(order.ltp * (1.0 + buf), 2)
    return round(order.ltp * (1.0 - buf), 2)


def check_market_order(
    order: OrderIntent,
) -> tuple[list[ComplianceViolation], str, float | None]:
    """Intercept MARKET orders and compute MPP conversion parameters.

    MARKET orders on NSE/BSE are converted to protected limit (MPP) structures as
    an execution-quality safeguard.  If LTP is missing, the order is rejected.

    Args:
        order: Incoming order (any type).

    Returns:
        Tuple of (violations, effective_order_type, mpp_price).
        On MARKET with valid LTP: violations=[], type='MPP', mpp_price=computed.
        On MARKET without LTP: violations=[NO_LTP], type='MARKET', mpp_price=None.
        On non-MARKET: violations=[], type=original, mpp_price=None.
    """
    if order.exchange not in INDIA_EXCHANGES or order.order_type != "MARKET":
        return [], order.order_type, None
    mpp = compute_mpp_price(order)
    if mpp is None:
        return (
            [
                _v(
                    "MARKET_ORDER_NO_LTP",
                    "MARKET order on NSE/BSE requires LTP for MPP limit conversion; "
                    "LTP not provided.",
                )
            ],
            "MARKET",
            None,
        )
    return [], "MPP", mpp


def check_leverage(order: OrderIntent) -> list[ComplianceViolation]:
    """Block orders where notional / capital exceeds max leverage (5×).

    Skipped for exit orders (SL exits must always be allowed through).

    Args:
        order: Order with ``notional_value`` and ``capital`` populated by caller.

    Returns:
        Empty list on pass; violation list on breach.
    """
    if order.exchange not in INDIA_EXCHANGES:
        return []
    if order.is_exit:
        return []
    if order.capital <= 0 or order.notional_value <= 0:
        return []
    leverage = order.notional_value / order.capital
    if leverage > MAX_LEVERAGE:
        return [
            _v(
                "LEVERAGE_EXCEEDED",
                f"Leverage {leverage:.2f}× exceeds max {MAX_LEVERAGE}× "
                "(20% upfront margin required — SEBI April 2026).",
            )
        ]
    return []


def check_mwpl(order: OrderIntent) -> list[ComplianceViolation]:
    """Block new entry orders where OI exceeds 90% of MWPL.

    Skipped for exits.  ``mwpl_pct=None`` means the caller did not have data —
    the check is skipped (fails-open) to avoid blocking valid orders when the
    MWPL feed is temporarily unavailable.

    Args:
        order: Order with optional ``mwpl_pct`` field.

    Returns:
        Empty list on pass or when data unavailable; violation list on breach.
    """
    if order.exchange not in INDIA_EXCHANGES:
        return []
    if order.is_exit:
        return []
    if order.mwpl_pct is None:
        return []
    if order.mwpl_pct > MWPL_EXCLUSION_THRESHOLD_PCT:
        return [
            _v(
                "MWPL_EXCEEDED",
                f"Symbol '{order.symbol}' OI at {order.mwpl_pct:.1f}% of MWPL "
                f"(threshold {MWPL_EXCLUSION_THRESHOLD_PCT}%) — entry blocked.",
            )
        ]
    return []


def check_force_square_off(
    order: OrderIntent,
    now_ist: datetime,
) -> list[ComplianceViolation]:
    """Block new entries at or after the force square-off time (15:10 IST).

    Exit orders (SL exits, manual exits) are always allowed through — the
    compliance cron itself will be issuing exit orders after this time.

    Args:
        order: The order being checked.
        now_ist: Current wall-clock time in IST (offset-aware or naive).

    Returns:
        Empty list on pass; violation on new entry at/after 15:10 IST.
    """
    if order.exchange not in INDIA_EXCHANGES:
        return []
    if order.is_exit:
        return []
    if now_ist.hour > FORCE_SQUARE_OFF_IST_HOUR or (
        now_ist.hour == FORCE_SQUARE_OFF_IST_HOUR
        and now_ist.minute >= FORCE_SQUARE_OFF_IST_MINUTE
    ):
        return [
            _v(
                "FORCE_SQUARE_OFF",
                f"New entry blocked at {now_ist.strftime('%H:%M')} IST — "
                f"force square-off active from "
                f"{FORCE_SQUARE_OFF_IST_HOUR:02d}:"
                f"{FORCE_SQUARE_OFF_IST_MINUTE:02d} IST.",
            )
        ]
    return []


def run_india_checks(
    order: OrderIntent,
    strategy_tag: str | None,
    now_ist: datetime | None = None,
) -> tuple[list[ComplianceViolation], str, float | None]:
    """Run all India-specific compliance checks in sequence.

    Args:
        order: The order being evaluated.
        strategy_tag: Resolved compressed tag (``None`` if unregistered).
        now_ist: Current IST datetime for force square-off check.
            Pass ``None`` to skip the time-based check (e.g. in paper mode).

    Returns:
        Tuple of (all_violations, effective_order_type, mpp_price).
        ``effective_order_type`` is ``'MPP'`` when a MARKET was converted.
    """
    all_violations: list[ComplianceViolation] = []

    all_violations.extend(check_strategy_id(order, strategy_tag))

    mkt_violations, effective_type, mpp_price = check_market_order(order)
    all_violations.extend(mkt_violations)

    all_violations.extend(check_leverage(order))
    all_violations.extend(check_mwpl(order))

    if now_ist is not None:
        all_violations.extend(check_force_square_off(order, now_ist))

    return all_violations, effective_type, mpp_price
