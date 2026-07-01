"""RULE 6: Model-promotion gate.

A retrained model (weekly MLflow pipeline) MUST independently clear every gate
below before replacing the currently-live model. No silent auto-promotion.

Gates (from MASTER_BUILD_PROMPT_FINAL.MD / RULE 6):
  1. Minimum 20 trading days in the evaluation window.
  2. Sharpe ratio > 1.5 (annualised).
  3. Win rate > 50%.
  4. Max drawdown < 5%.
"""

from __future__ import annotations

from shared.backtesting.models import BacktestMetrics
from shared.core.constants import (
    PAPER_TRADING_MAX_DRAWDOWN_PCT,
    PAPER_TRADING_MIN_DAYS,
    PAPER_TRADING_MIN_SHARPE,
    PAPER_TRADING_MIN_WIN_RATE_PCT,
)
from shared.core.logging import get_logger

logger = get_logger(__name__)

_GATE_LABELS: dict[str, str] = {
    "days": f"min_trading_days >= {PAPER_TRADING_MIN_DAYS}",
    "sharpe": f"sharpe_ratio > {PAPER_TRADING_MIN_SHARPE}",
    "win_rate": f"win_rate_pct > {PAPER_TRADING_MIN_WIN_RATE_PCT}",
    "drawdown": f"max_drawdown_pct < {PAPER_TRADING_MAX_DRAWDOWN_PCT}",
}


def check_promotion_gate(metrics: BacktestMetrics) -> list[str]:
    """Check all RULE 6 promotion gates against `metrics`.

    Args:
        metrics: Computed metrics from a completed BacktestResult.

    Returns:
        List of failed gate labels (empty list means all gates passed).
        Callers must treat a non-empty list as a hard block — not a warning.
    """
    failures: list[str] = []

    if metrics.trading_days < PAPER_TRADING_MIN_DAYS:
        failures.append(_GATE_LABELS["days"])
    if metrics.sharpe_ratio <= PAPER_TRADING_MIN_SHARPE:
        failures.append(_GATE_LABELS["sharpe"])
    if metrics.win_rate_pct <= PAPER_TRADING_MIN_WIN_RATE_PCT:
        failures.append(_GATE_LABELS["win_rate"])
    if metrics.max_drawdown_pct >= PAPER_TRADING_MAX_DRAWDOWN_PCT:
        failures.append(_GATE_LABELS["drawdown"])

    passed = len(failures) == 0
    logger.info(
        "promotion_gate_evaluated",
        passed=passed,
        sharpe=metrics.sharpe_ratio,
        win_rate_pct=metrics.win_rate_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        trading_days=metrics.trading_days,
        failures=failures,
    )
    return failures
