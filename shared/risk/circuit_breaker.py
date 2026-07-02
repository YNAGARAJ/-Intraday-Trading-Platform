"""Daily loss circuit breaker for M12.

Enforces RULE 8: autonomous halt at -2% daily P&L. Cannot be disabled in LIVE mode.
M12 detects the breach; M18 orchestrates the full Kill Switch sequence (cancel orders,
emergency exit, set Redis flag, Telegram alert). M12 only reads the Redis flag and
the daily P&L — it never writes to Redis directly.

Two failure modes:
1. ``halted=True`` — ``system:status:halted`` was already set in Redis by a prior
   Kill Switch activation. Block unconditionally.
2. Daily P&L ≤ -2% of capital — fresh breach detected this evaluation cycle.
   Block the trade; caller/M18 is responsible for triggering the Kill Switch.
"""

from __future__ import annotations

import structlog

from shared.core.constants import DAILY_LOSS_LIMIT_PCT, MAX_DAILY_TRADES
from shared.risk.models import RiskCheck

logger = structlog.get_logger(__name__)


def check_halted_flag(halted: bool) -> RiskCheck:
    """Check if the system is already halted via the Redis kill-switch flag.

    Args:
        halted: True when caller read ``system:status:halted = 'true'`` from Redis.

    Returns:
        ``RiskCheck`` that fails immediately if halted.
    """
    if halted:
        logger.warning("risk_check_halted_flag_set")
        return RiskCheck(
            name="SYSTEM_HALTED",
            passed=False,
            detail="system:status:halted=true — all new entries blocked",
        )
    return RiskCheck(
        name="SYSTEM_HALTED",
        passed=True,
        detail="System not halted",
    )


def check_daily_loss_limit(daily_pnl: float, capital: float) -> RiskCheck:
    """Check whether today's P&L has breached the -2% circuit breaker.

    Args:
        daily_pnl: Today's realized + unrealized P&L (negative = loss).
        capital: Total account capital.

    Returns:
        ``RiskCheck`` that fails when ``daily_pnl / capital × 100 ≤ -2.0``.
    """
    if capital <= 0:
        return RiskCheck(
            name="CIRCUIT_BREAKER",
            passed=False,
            detail=f"Invalid capital value: {capital}",
        )
    pnl_pct = (daily_pnl / capital) * 100.0
    if pnl_pct <= DAILY_LOSS_LIMIT_PCT:
        logger.warning(
            "risk_circuit_breaker_triggered",
            daily_pnl=round(daily_pnl, 2),
            pnl_pct=round(pnl_pct, 3),
            limit_pct=DAILY_LOSS_LIMIT_PCT,
        )
        return RiskCheck(
            name="CIRCUIT_BREAKER",
            passed=False,
            detail=(
                f"Daily P&L {pnl_pct:.2f}% ≤ circuit-breaker limit "
                f"{DAILY_LOSS_LIMIT_PCT}% — Kill Switch must be triggered"
            ),
        )
    return RiskCheck(
        name="CIRCUIT_BREAKER",
        passed=True,
        detail=f"Daily P&L {pnl_pct:.2f}% within limit {DAILY_LOSS_LIMIT_PCT}%",
    )


def check_circuit_breaker(
    daily_pnl: float,
    capital: float,
    halted: bool = False,
) -> RiskCheck:
    """Combined circuit-breaker check: halted flag first, then daily P&L.

    Convenience wrapper for callers who want a single check. The engine
    calls ``check_halted_flag`` and ``check_daily_loss_limit`` individually
    so each appears as a separate entry in ``RiskDecision.checks``.

    Args:
        daily_pnl: Today's realized + unrealized P&L.
        capital: Total account capital.
        halted: True when ``system:status:halted`` is set in Redis.

    Returns:
        First failing check, or a pass if both pass.
    """
    halted_check = check_halted_flag(halted)
    if not halted_check.passed:
        return halted_check
    return check_daily_loss_limit(daily_pnl, capital)


def check_daily_trade_count(daily_trade_count: int) -> RiskCheck:
    """Check whether the daily trade count limit has been reached.

    Args:
        daily_trade_count: Number of trades already completed today.

    Returns:
        ``RiskCheck`` that fails when count is at or above ``MAX_DAILY_TRADES``.
    """
    if daily_trade_count >= MAX_DAILY_TRADES:
        return RiskCheck(
            name="DAILY_TRADE_LIMIT",
            passed=False,
            detail=(
                f"Daily trade count {daily_trade_count} ≥ limit {MAX_DAILY_TRADES}"
            ),
        )
    return RiskCheck(
        name="DAILY_TRADE_LIMIT",
        passed=True,
        detail=(
            f"Daily trade count {daily_trade_count}/{MAX_DAILY_TRADES}"
        ),
    )
