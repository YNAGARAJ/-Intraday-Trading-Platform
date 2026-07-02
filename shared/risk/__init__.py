"""M12 — Risk & Position Sizing Engine.

ATR-based SL, 3-5-7 Rule, regime-adjusted sizing, snapshot-window multiplier,
correlation guard, and daily loss circuit breaker.
"""

from shared.risk.engine import RiskEngine
from shared.risk.models import (
    OpenPosition,
    PositionSize,
    RiskCheck,
    RiskDecision,
    RiskParameters,
)

__all__ = [
    "OpenPosition",
    "PositionSize",
    "RiskCheck",
    "RiskDecision",
    "RiskEngine",
    "RiskParameters",
]
