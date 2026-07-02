"""Risk & Position Sizing Engine (M12).

`RiskEngine.evaluate()` is the single entry point. It runs all guards in order and
returns a `RiskDecision`. Pure computation: no I/O, no Redis calls — all external
state is passed in via `RiskParameters` (caller reads Redis before calling).

Guard evaluation order (fail-fast):
  1. System halted flag  (kills new entries if Kill Switch was previously triggered)
  2. Circuit breaker     (-2% daily P&L → block, caller must trigger Kill Switch)
  3. Daily trade count   (MAX_DAILY_TRADES cap)
  4. 3% per-trade limit  (RULE: MAX_SINGLE_TRADE_LOSS_PCT)
  5. 5% per-sector limit (RULE: MAX_SECTOR_EXPOSURE_PCT)
  6. 7% portfolio heat   (RULE: MAX_PORTFOLIO_HEAT_PCT)
  7. Correlation guard   (MAX_POSITION_CORRELATION = 0.7)
  8. Compute position size (ATR fixed-risk or Kelly — Kelly is off by default)
  9. Final 3% check on computed size (verifies sizing respects per-trade limit)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from shared.core.constants import (
    MAX_PORTFOLIO_HEAT_PCT,
    MAX_SECTOR_EXPOSURE_PCT,
    MAX_SINGLE_TRADE_LOSS_PCT,
    RISK_PCT_BEAR_TREND,
    RISK_PCT_BULL_TREND,
    RISK_PCT_HIGH_VOL_CHAOS,
    RISK_PCT_MEAN_REVERTING,
    SNAPSHOT_WINDOW_SIZE_MULTIPLIER,
)
from shared.risk.circuit_breaker import (
    check_daily_loss_limit,
    check_daily_trade_count,
    check_halted_flag,
)
from shared.risk.correlation import check_correlation_guard
from shared.risk.models import (
    RiskCheck,
    RiskDecision,
    RiskParameters,
)
from shared.risk.sizing import compute_atr_position_size, compute_kelly_position_size

if TYPE_CHECKING:
    from shared.regime.models import RegimeClassification
    from shared.risk.models import PositionSize

logger = structlog.get_logger(__name__)


def _regime_risk_pct(regime: RegimeClassification) -> float:
    """Return the base risk-per-trade percentage for the given regime."""
    from shared.regime.models import MarketRegime  # noqa: PLC0415

    mapping = {
        MarketRegime.BULL_TREND: RISK_PCT_BULL_TREND,
        MarketRegime.BEAR_TREND: RISK_PCT_BEAR_TREND,
        MarketRegime.MEAN_REVERTING: RISK_PCT_MEAN_REVERTING,
        MarketRegime.HIGH_VOL_CHAOS: RISK_PCT_HIGH_VOL_CHAOS,
    }
    return mapping.get(regime.regime, RISK_PCT_MEAN_REVERTING)


def _check_three_five_seven(
    params: RiskParameters,
    proposed_risk_amount: float,
) -> list[RiskCheck]:
    """Evaluate the 3-5-7 Rule against the proposed risk amount.

    Args:
        params: Current risk parameters (open positions, capital, sector).
        proposed_risk_amount: Estimated risk amount for the proposed trade.
            This is a preliminary estimate used for 3-5-7 gating; the exact
            amount is reconfirmed after position sizing.

    Returns:
        List of ``RiskCheck`` results, one per rule. Evaluation stops at
        the first failure (remaining rules return early with ``passed=True``
        placeholders — caller is responsible for checking the list).
    """
    checks: list[RiskCheck] = []
    capital = params.capital
    if capital <= 0:
        checks.append(
            RiskCheck(
                name="THREE_FIVE_SEVEN",
                passed=False,
                detail="Capital is zero or negative",
            )
        )
        return checks

    proposed_pct = (proposed_risk_amount / capital) * 100.0

    # Rule 1: max 3% per-trade
    per_trade_check = RiskCheck(
        name="MAX_PER_TRADE_RISK",
        passed=proposed_pct <= MAX_SINGLE_TRADE_LOSS_PCT,
        detail=(
            f"Proposed risk {proposed_pct:.2f}% "
            + (
                f"≤ limit {MAX_SINGLE_TRADE_LOSS_PCT}%"
                if proposed_pct <= MAX_SINGLE_TRADE_LOSS_PCT
                else f"exceeds limit {MAX_SINGLE_TRADE_LOSS_PCT}%"
            )
        ),
    )
    checks.append(per_trade_check)
    if not per_trade_check.passed:
        return checks

    # Rule 2: max 5% per-sector
    sector_risk = sum(
        p.risk_amount
        for p in params.open_positions
        if p.sector == params.proposed_sector
    )
    sector_total_pct = ((sector_risk + proposed_risk_amount) / capital) * 100.0
    sector_check = RiskCheck(
        name="MAX_SECTOR_RISK",
        passed=sector_total_pct <= MAX_SECTOR_EXPOSURE_PCT,
        detail=(
            f"Sector '{params.proposed_sector}' total risk "
            f"{sector_total_pct:.2f}% "
            + (
                f"≤ limit {MAX_SECTOR_EXPOSURE_PCT}%"
                if sector_total_pct <= MAX_SECTOR_EXPOSURE_PCT
                else f"exceeds limit {MAX_SECTOR_EXPOSURE_PCT}%"
            )
        ),
    )
    checks.append(sector_check)
    if not sector_check.passed:
        return checks

    # Rule 3: max 7% portfolio heat
    total_heat = sum(p.risk_amount for p in params.open_positions)
    heat_pct = ((total_heat + proposed_risk_amount) / capital) * 100.0
    heat_check = RiskCheck(
        name="MAX_PORTFOLIO_HEAT",
        passed=heat_pct <= MAX_PORTFOLIO_HEAT_PCT,
        detail=(
            f"Portfolio heat {heat_pct:.2f}% "
            + (
                f"≤ limit {MAX_PORTFOLIO_HEAT_PCT}%"
                if heat_pct <= MAX_PORTFOLIO_HEAT_PCT
                else f"exceeds limit {MAX_PORTFOLIO_HEAT_PCT}%"
            )
        ),
    )
    checks.append(heat_check)
    return checks


class RiskEngine:
    """Evaluates risk parameters and computes an approved position size.

    Thread-safe and stateless: all state is in ``RiskParameters``. One instance
    can serve multiple concurrent evaluations.
    """

    def evaluate(
        self,
        entry_price: float,
        stop_loss: float,
        params: RiskParameters,
    ) -> RiskDecision:
        """Run all risk guards and return a ``RiskDecision``.

        Args:
            entry_price: Proposed entry price for the new position.
            stop_loss: Hard stop-loss price (from M11 / M12 ATR calc).
            params: Complete risk context assembled by the caller.

        Returns:
            ``RiskDecision`` with ``approved=True`` and a valid ``PositionSize``
            only when all guards passed and sizing succeeded.
        """
        checks: list[RiskCheck] = []

        def _reject(reason: str) -> RiskDecision:
            return RiskDecision(
                approved=False,
                position_size=None,
                rejection_reason=reason,
                checks=checks,
            )

        # --- 1. System halted flag ---
        halted_check = check_halted_flag(params.halted)
        checks.append(halted_check)
        if not halted_check.passed:
            return _reject(halted_check.detail)

        # --- 2. Circuit breaker (-2% daily P&L) ---
        cb_check = check_daily_loss_limit(params.daily_pnl, params.capital)
        checks.append(cb_check)
        if not cb_check.passed:
            return _reject(cb_check.detail)

        # --- 3. Daily trade count ---
        tc_check = check_daily_trade_count(params.daily_trade_count)
        checks.append(tc_check)
        if not tc_check.passed:
            return _reject(tc_check.detail)

        # --- 4-6. 3-5-7 Rule (preliminary estimate) ---
        regime_pct = _regime_risk_pct(params.regime)
        snapshot_mult = (
            SNAPSHOT_WINDOW_SIZE_MULTIPLIER if params.is_snapshot_window else 1.0
        )
        preliminary_risk = params.capital * (regime_pct / 100.0) * snapshot_mult
        three_five_seven = _check_three_five_seven(params, preliminary_risk)
        checks.extend(three_five_seven)
        for check in three_five_seven:
            if not check.passed:
                return _reject(check.detail)

        # --- 7. Correlation guard ---
        corr_check = check_correlation_guard(
            params.proposed_returns,
            params.open_positions,
        )
        checks.append(corr_check)
        if not corr_check.passed:
            return _reject(corr_check.detail)

        # --- 8. Compute position size ---
        regime_multiplier = regime_pct / RISK_PCT_BULL_TREND
        size: PositionSize
        try:
            win_rate = params.win_rate
            avg_wl = params.avg_win_loss_ratio
            if params.use_kelly and win_rate is not None and avg_wl is not None:
                size = compute_kelly_position_size(
                    capital=params.capital,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    win_rate=win_rate,
                    avg_win_loss_ratio=avg_wl,
                    regime_multiplier=regime_multiplier,
                    is_snapshot_window=params.is_snapshot_window,
                )
            else:
                size = compute_atr_position_size(
                    capital=params.capital,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    base_risk_pct=regime_pct,
                    regime_multiplier=regime_multiplier,
                    is_snapshot_window=params.is_snapshot_window,
                )
        except ValueError as exc:
            sizing_fail = RiskCheck(
                name="SIZING",
                passed=False,
                detail=str(exc),
            )
            checks.append(sizing_fail)
            return _reject(str(exc))

        sizing_ok = RiskCheck(
            name="SIZING",
            passed=True,
            detail=(
                f"qty={size.quantity} notional={size.notional_value:.2f} "
                f"risk={size.risk_pct:.3f}% method={size.sizing_method}"
            ),
        )
        checks.append(sizing_ok)

        # --- 9. Final per-trade cap on actual computed risk ---
        if size.risk_pct > MAX_SINGLE_TRADE_LOSS_PCT:
            final_check = RiskCheck(
                name="FINAL_PER_TRADE_CAP",
                passed=False,
                detail=(
                    f"Computed risk {size.risk_pct:.3f}% exceeds "
                    f"{MAX_SINGLE_TRADE_LOSS_PCT}% per-trade cap after sizing"
                ),
            )
            checks.append(final_check)
            return _reject(final_check.detail)

        checks.append(
            RiskCheck(
                name="FINAL_PER_TRADE_CAP",
                passed=True,
                detail=f"Computed risk {size.risk_pct:.3f}% within cap",
            )
        )

        logger.info(
            "risk_approved",
            entry=entry_price,
            stop=stop_loss,
            quantity=size.quantity,
            risk_pct=size.risk_pct,
            method=size.sizing_method,
        )

        return RiskDecision(
            approved=True,
            position_size=size,
            rejection_reason=None,
            checks=checks,
        )
