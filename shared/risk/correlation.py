"""Correlation guard for M12.

Computes Pearson correlation between a proposed position's return series and every
open position's return series. Blocks entry when any pair exceeds the threshold
(MAX_POSITION_CORRELATION = 0.7). A short lookback (< 2 points) is treated as
zero correlation (insufficient data — allow through).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import structlog

from shared.core.constants import CORRELATION_LOOKBACK_DAYS, MAX_POSITION_CORRELATION
from shared.risk.models import OpenPosition, RiskCheck

logger = structlog.get_logger(__name__)


def pearson_correlation(
    returns_a: Sequence[float],
    returns_b: Sequence[float],
) -> float:
    """Pearson correlation between two return series (aligned to shortest).

    Args:
        returns_a: Daily returns for series A (oldest first).
        returns_b: Daily returns for series B (oldest first).

    Returns:
        Correlation coefficient in ``[-1, 1]``, or ``0.0`` when there are
        fewer than 2 aligned data points (insufficient data).
    """
    n = min(len(returns_a), len(returns_b), CORRELATION_LOOKBACK_DAYS)
    if n < 2:
        return 0.0
    a = np.asarray(returns_a[-n:], dtype=float)
    b = np.asarray(returns_b[-n:], dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    corr_matrix = np.corrcoef(a, b)
    return float(corr_matrix[0, 1])


def check_correlation_guard(
    proposed_returns: Sequence[float],
    open_positions: Sequence[OpenPosition],
    max_correlation: float = MAX_POSITION_CORRELATION,
) -> RiskCheck:
    """Return a ``RiskCheck`` for the correlation guard.

    Iterates every open position and computes Pearson correlation with the
    proposed position's return series. Fails at the first breach.

    Args:
        proposed_returns: Recent daily returns for the proposed symbol.
        open_positions: All currently open positions.
        max_correlation: Absolute correlation threshold (default 0.7).

    Returns:
        ``RiskCheck(passed=True)`` when no open position is too correlated,
        otherwise ``RiskCheck(passed=False)`` naming the breaching position.
    """
    if not open_positions:
        return RiskCheck(
            name="CORRELATION_GUARD",
            passed=True,
            detail="No open positions — correlation guard skipped",
        )

    if len(proposed_returns) < 2:
        return RiskCheck(
            name="CORRELATION_GUARD",
            passed=True,
            detail=(
                "Insufficient return history for proposed symbol "
                "(< 2 points) — correlation guard skipped"
            ),
        )

    for pos in open_positions:
        corr = pearson_correlation(proposed_returns, pos.returns)
        abs_corr = abs(corr)
        if abs_corr > max_correlation:
            logger.info(
                "correlation_guard_fail",
                symbol=pos.symbol,
                correlation=round(corr, 4),
                threshold=max_correlation,
            )
            return RiskCheck(
                name="CORRELATION_GUARD",
                passed=False,
                detail=(
                    f"Correlation with open position {pos.symbol} = {corr:.3f} "
                    f"exceeds threshold ±{max_correlation}"
                ),
            )

    return RiskCheck(
        name="CORRELATION_GUARD",
        passed=True,
        detail=(
            f"All open-position correlations within ±{max_correlation} "
            f"({len(open_positions)} checked)"
        ),
    )
