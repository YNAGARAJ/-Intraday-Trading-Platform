"""SEBI and ASIC compliance engine — M13.

Public API:
- ``ComplianceEngine`` — single entry point for all pre-trade compliance checks.
- ``KillSwitchManager`` — tiered kill switch (Tier 1 autonomous, Tier 2 external,
  Tier 3 heartbeat failsafe).
- ``StrategyRegistry`` — strategy name → compressed broker tag mapping.
- ``OrderIntent``, ``ComplianceDecision``, ``TaggedOrder`` — core data models.
"""

from shared.compliance.engine import ComplianceEngine
from shared.compliance.kill_switch import KillSwitchManager, KillSwitchTrigger
from shared.compliance.models import (
    ComplianceDecision,
    ComplianceViolation,
    KillSwitchEvent,
    OrderIntent,
    RecentOrder,
    TaggedOrder,
)
from shared.compliance.strategy_registry import StrategyRegistry

__all__ = [
    "ComplianceDecision",
    "ComplianceEngine",
    "ComplianceViolation",
    "KillSwitchEvent",
    "KillSwitchManager",
    "KillSwitchTrigger",
    "OrderIntent",
    "RecentOrder",
    "StrategyRegistry",
    "TaggedOrder",
]
