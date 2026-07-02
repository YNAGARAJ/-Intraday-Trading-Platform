"""Australia (ASX) compliance checks — ASIC obligations.

All checks return ``list[ComplianceViolation]``.  Pure functions: no I/O.

Regulatory context (ASIC, current obligations + CP 386 forward-looking):
- No wash trading: no matching own orders in the same symbol within 60 s.
- No layering: never maintain simultaneous orders on both sides of the same symbol.
- Short-sell restriction: only if symbol on the approved short list.
- ASX staggered open: 15-min noise filter per ticker from its group open time.
- Post-close session: residual position clearance window 16:11–16:21:30 AEST.
  Any position still open after 16:21:30 AEST is a compliance violation.
- 7-year trade log retention (S3 lifecycle, configured in M23 infra/).

CP 386 note: CP 386 is a consultation paper (submissions closed Oct 2025) with
final rules targeted by 31 March 2026 and PROPOSED commencement April 2027.
This module is built to the stricter 3-tier standard as engineering best practice
and to meet EXISTING ASIC automated-trading kill-switch obligations.  Do not cite
CP 386 as currently-in-force law until the final rules are published.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from shared.core.constants import (
    ASX_POST_CLOSE_CUTOFF_HOUR,
    ASX_POST_CLOSE_CUTOFF_MINUTE,
    ASX_POST_CLOSE_CUTOFF_SECOND,
    ASX_STAGGERED_OPEN_NOISE_FILTER_MINUTES,
    WASH_TRADE_LOOKBACK_SECONDS,
)

if TYPE_CHECKING:
    from shared.compliance.models import ComplianceViolation, OrderIntent, RecentOrder

ASX_EXCHANGES: frozenset[str] = frozenset({"ASX"})


def _v(code: str, detail: str) -> ComplianceViolation:
    from shared.compliance.models import ComplianceViolation  # noqa: PLC0415

    return ComplianceViolation(code=code, detail=detail)


def check_wash_trading(
    order: OrderIntent,
    recent_orders: list[RecentOrder],
    now_ms: int,
) -> list[ComplianceViolation]:
    """Block an order if the same symbol was traded in the opposing direction within
    the wash-trade lookback window (ASIC: no wash trading).

    Wash trading is detected when the same symbol has a RECENT order in the
    OPPOSITE direction within ``WASH_TRADE_LOOKBACK_SECONDS`` — indicates a
    round-trip intended to create artificial volume.

    Args:
        order: The new order being evaluated.
        recent_orders: Orders placed by this system in the last session.
        now_ms: Current Unix epoch in milliseconds.

    Returns:
        Empty list on pass; violation list on wash-trade detection.
    """
    if order.exchange not in ASX_EXCHANGES:
        return []
    opposite = "SHORT" if order.direction == "LONG" else "LONG"
    cutoff_ms = now_ms - (WASH_TRADE_LOOKBACK_SECONDS * 1000)
    for recent in recent_orders:
        if (
            recent.symbol == order.symbol
            and recent.direction == opposite
            and recent.placed_at_ms >= cutoff_ms
        ):
            elapsed_s = (now_ms - recent.placed_at_ms) / 1000
            return [
                _v(
                    "WASH_TRADING",
                    f"Opposing {recent.direction} order for '{order.symbol}' "
                    f"placed {elapsed_s:.0f}s ago "
                    f"(lookback {WASH_TRADE_LOOKBACK_SECONDS}s) — "
                    "potential wash trade blocked (ASIC).",
                )
            ]
    return []


def check_layering(
    order: OrderIntent,
    pending_orders: list[RecentOrder],
) -> list[ComplianceViolation]:
    """Block orders that would create simultaneous bids and asks on the same symbol
    (ASIC: no layering / spoofing).

    Layering is detected when there is already a PENDING order on the same symbol
    in the OPPOSITE direction (i.e. both long and short at the same time).

    Args:
        order: The new order being evaluated.
        pending_orders: Orders that are currently live / open in the broker book.

    Returns:
        Empty list on pass; violation list on layering detection.
    """
    if order.exchange not in ASX_EXCHANGES:
        return []
    opposite = "SHORT" if order.direction == "LONG" else "LONG"
    for pending in pending_orders:
        if pending.symbol == order.symbol and pending.direction == opposite:
            return [
                _v(
                    "LAYERING",
                    f"Simultaneous {opposite} order pending for '{order.symbol}' — "
                    "placing opposing direction would create layering (ASIC).",
                )
            ]
    return []


def check_short_sell(
    order: OrderIntent,
    approved_short_list: frozenset[str],
) -> list[ComplianceViolation]:
    """Block short-sell orders on symbols not on the IBKR-verified short list.

    Args:
        order: The new order being evaluated.
        approved_short_list: Set of symbols approved for short selling on ASX.
            Verified via IBKR before order placement (M14 populates this).

    Returns:
        Empty list on pass; violation list when symbol not approved.
    """
    if order.exchange not in ASX_EXCHANGES:
        return []
    if order.direction != "SHORT":
        return []
    if order.is_exit:
        return []
    if order.symbol not in approved_short_list:
        return [
            _v(
                "SHORT_SELL_NOT_APPROVED",
                f"Symbol '{order.symbol}' is not on the IBKR-verified ASX short list — "
                "short entry blocked (ASIC).",
            )
        ]
    return []


def check_staggered_open(
    order: OrderIntent,
    group_open_ms: int | None,
    now_ms: int,
) -> list[ComplianceViolation]:
    """Block new ASX entries during the 15-min noise filter after ticker group open.

    Only applies to new entries (``is_exit=False``).  SL exits bypass this.

    Args:
        order: The new order being evaluated.
        group_open_ms: Unix epoch milliseconds when this ticker's ASX group opened.
            ``None`` means the open time is unknown — check is skipped (fails-open).
        now_ms: Current Unix epoch in milliseconds.

    Returns:
        Empty list on pass; violation during noise-filter window.
    """
    if order.exchange not in ASX_EXCHANGES:
        return []
    if order.is_exit:
        return []
    if group_open_ms is None:
        return []
    elapsed_min = (now_ms - group_open_ms) / 60_000.0
    if elapsed_min < ASX_STAGGERED_OPEN_NOISE_FILTER_MINUTES:
        remaining = ASX_STAGGERED_OPEN_NOISE_FILTER_MINUTES - elapsed_min
        return [
            _v(
                "STAGGERED_OPEN_NOISE_FILTER",
                f"'{order.symbol}' is within {remaining:.1f} min of its ASX group open"
                " — 15-min noise filter active (ASIC staggered open).",
            )
        ]
    return []


def check_post_close_cutoff(
    order: OrderIntent,
    now_aest: datetime,
) -> list[ComplianceViolation]:
    """Detect new entries placed after the ASX post-close cutoff (16:21:30 AEST).

    Any OPEN position after 16:21:30 AEST is a compliance violation.  This check
    blocks new entries; M19/M18 are responsible for alerting on open positions.

    Args:
        order: The new order being evaluated.
        now_aest: Current wall-clock time in AEST (offset-aware or naive).

    Returns:
        Empty list on pass; violation when entry placed past cutoff.
    """
    if order.exchange not in ASX_EXCHANGES:
        return []
    if order.is_exit:
        return []
    cutoff_hit = (
        now_aest.hour > ASX_POST_CLOSE_CUTOFF_HOUR
        or (
            now_aest.hour == ASX_POST_CLOSE_CUTOFF_HOUR
            and now_aest.minute > ASX_POST_CLOSE_CUTOFF_MINUTE
        )
        or (
            now_aest.hour == ASX_POST_CLOSE_CUTOFF_HOUR
            and now_aest.minute == ASX_POST_CLOSE_CUTOFF_MINUTE
            and now_aest.second >= ASX_POST_CLOSE_CUTOFF_SECOND
        )
    )
    if cutoff_hit:
        return [
            _v(
                "POST_CLOSE_CUTOFF",
                f"New entry blocked at {now_aest.strftime('%H:%M:%S')} AEST — "
                f"post-close cutoff is "
                f"{ASX_POST_CLOSE_CUTOFF_HOUR:02d}:"
                f"{ASX_POST_CLOSE_CUTOFF_MINUTE:02d}:"
                f"{ASX_POST_CLOSE_CUTOFF_SECOND:02d} AEST (ASIC).",
            )
        ]
    return []


def run_australia_checks(
    order: OrderIntent,
    recent_orders: list[RecentOrder],
    pending_orders: list[RecentOrder],
    approved_short_list: frozenset[str],
    now_ms: int,
    group_open_ms: int | None = None,
    now_aest: datetime | None = None,
) -> list[ComplianceViolation]:
    """Run all Australia-specific compliance checks in sequence.

    Args:
        order: The order being evaluated.
        recent_orders: Orders placed in the last session (for wash-trade check).
        pending_orders: Currently live orders in the broker book (for layering check).
        approved_short_list: IBKR-verified short-sell approved symbols.
        now_ms: Current Unix epoch in milliseconds.
        group_open_ms: ASX group open timestamp for this ticker (``None`` = skip).
        now_aest: Current AEST datetime (``None`` = skip post-close check).

    Returns:
        All violations from every applicable check (may be multiple).
    """
    all_violations: list[ComplianceViolation] = []
    all_violations.extend(check_wash_trading(order, recent_orders, now_ms))
    all_violations.extend(check_layering(order, pending_orders))
    all_violations.extend(check_short_sell(order, approved_short_list))
    all_violations.extend(check_staggered_open(order, group_open_ms, now_ms))
    if now_aest is not None:
        all_violations.extend(check_post_close_cutoff(order, now_aest))
    return all_violations
