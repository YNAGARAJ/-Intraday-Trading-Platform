"""Position size computation for M12.

Two sizing methods:
- ATR_FIXED_RISK: risk a fixed % of capital, size = risk_amount / stop_distance.
- KELLY: fractional Kelly criterion (quarter-Kelly by default; off by default).

Regime and snapshot-window multipliers are applied before dividing by stop_distance,
so the quantity itself already reflects the reduced risk posture.
"""

from __future__ import annotations

import math

import structlog

from shared.core.constants import (
    KELLY_FRACTION,
    MIN_STOP_DISTANCE_PCT,
    SNAPSHOT_WINDOW_SIZE_MULTIPLIER,
)
from shared.risk.models import PositionSize

logger = structlog.get_logger(__name__)


def compute_atr_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    base_risk_pct: float,
    regime_multiplier: float,
    is_snapshot_window: bool,
) -> PositionSize:
    """ATR-based fixed-risk position sizing.

    Args:
        capital: Total account capital.
        entry_price: Proposed entry price.
        stop_loss: Hard stop-loss price (pre-computed by M11).
        base_risk_pct: Base % of capital to risk (regime-dependent, e.g. 1.0%).
        regime_multiplier: Scaling factor from regime (1.0 for BULL, 0.75 BEAR, etc.).
        is_snapshot_window: If True, apply 0.5× snapshot window multiplier.

    Returns:
        ``PositionSize`` with quantity rounded down to the nearest whole share.

    Raises:
        ValueError: When stop distance is zero or entry price is non-positive.
    """
    if entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price}")

    stop_distance = abs(entry_price - stop_loss)
    min_distance = entry_price * (MIN_STOP_DISTANCE_PCT / 100.0)
    if stop_distance < min_distance:
        raise ValueError(
            f"stop_distance {stop_distance:.4f} below minimum "
            f"{min_distance:.4f} ({MIN_STOP_DISTANCE_PCT}% of entry)"
        )

    snapshot_mult = SNAPSHOT_WINDOW_SIZE_MULTIPLIER if is_snapshot_window else 1.0
    effective_risk_pct = base_risk_pct * regime_multiplier * snapshot_mult
    risk_amount = capital * (effective_risk_pct / 100.0)

    raw_qty = risk_amount / stop_distance
    quantity = max(1, math.floor(raw_qty))

    actual_risk = quantity * stop_distance
    actual_risk_pct = (actual_risk / capital) * 100.0 if capital > 0 else 0.0

    logger.debug(
        "atr_position_sized",
        entry=entry_price,
        stop=stop_loss,
        stop_distance=round(stop_distance, 4),
        effective_risk_pct=round(effective_risk_pct, 4),
        quantity=quantity,
        actual_risk_pct=round(actual_risk_pct, 4),
    )

    return PositionSize(
        quantity=quantity,
        notional_value=round(quantity * entry_price, 4),
        risk_amount=round(actual_risk, 4),
        risk_pct=round(actual_risk_pct, 4),
        sizing_method="ATR_FIXED_RISK",
        regime_multiplier=regime_multiplier,
        snapshot_multiplier=snapshot_mult,
    )


def compute_kelly_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    win_rate: float,
    avg_win_loss_ratio: float,
    regime_multiplier: float,
    is_snapshot_window: bool,
) -> PositionSize:
    """Fractional Kelly criterion position sizing.

    Uses quarter-Kelly (``KELLY_FRACTION = 0.25``) for conservative risk control.
    Kelly is off by default; callers must explicitly opt in and must have completed
    the 20-day paper-trading validation gate before enabling in live mode.

    Args:
        capital: Total account capital.
        entry_price: Proposed entry price.
        stop_loss: Hard stop-loss price.
        win_rate: Historical win rate in ``[0.0, 1.0]``.
        avg_win_loss_ratio: Mean win size / mean loss size.
        regime_multiplier: Regime-based scaling factor.
        is_snapshot_window: If True, apply 0.5× snapshot-window multiplier.

    Returns:
        ``PositionSize`` using Kelly-derived fraction, clamped to ≥ 0.

    Raises:
        ValueError: When stop distance is zero, win_rate is outside (0, 1),
            or avg_win_loss_ratio is not positive.
    """
    if not 0.0 < win_rate < 1.0:
        raise ValueError(f"win_rate must be in (0, 1), got {win_rate}")
    if avg_win_loss_ratio <= 0:
        raise ValueError(
            f"avg_win_loss_ratio must be > 0, got {avg_win_loss_ratio}"
        )

    b = avg_win_loss_ratio
    q = 1.0 - win_rate
    kelly_full = (b * win_rate - q) / b
    kelly_full = max(0.0, kelly_full)
    fraction = KELLY_FRACTION * kelly_full

    snapshot_mult = SNAPSHOT_WINDOW_SIZE_MULTIPLIER if is_snapshot_window else 1.0
    effective_fraction = fraction * regime_multiplier * snapshot_mult
    risk_amount = capital * effective_fraction

    stop_distance = abs(entry_price - stop_loss)
    min_distance = entry_price * (MIN_STOP_DISTANCE_PCT / 100.0)
    if stop_distance < min_distance:
        raise ValueError(
            f"stop_distance {stop_distance:.4f} below minimum {min_distance:.4f}"
        )

    raw_qty = risk_amount / stop_distance if stop_distance > 0 else 0.0
    quantity = max(1, math.floor(raw_qty))

    actual_risk = quantity * stop_distance
    actual_risk_pct = (actual_risk / capital) * 100.0 if capital > 0 else 0.0

    logger.debug(
        "kelly_position_sized",
        kelly_full=round(kelly_full, 4),
        kelly_fraction=KELLY_FRACTION,
        effective_fraction=round(effective_fraction, 4),
        quantity=quantity,
        actual_risk_pct=round(actual_risk_pct, 4),
    )

    return PositionSize(
        quantity=quantity,
        notional_value=round(quantity * entry_price, 4),
        risk_amount=round(actual_risk, 4),
        risk_pct=round(actual_risk_pct, 4),
        sizing_method="KELLY",
        regime_multiplier=regime_multiplier,
        snapshot_multiplier=snapshot_mult,
    )
