"""M11 Signal Generation Agent — 9-gate pure-Python signal evaluation system.

Public API:
  - `SignalEngine.evaluate(ctx)` → `SignalResult`  (< 100ms, zero LLM)
  - `SignalPublisher.publish(result)`               (atomic Redis Lua dedup)
  - `explain_signal(result)`                        (async Groq 70B, non-blocking)
"""

from shared.signals.engine import SignalEngine
from shared.signals.models import (
    GateResult,
    SignalContext,
    SignalDirection,
    SignalResult,
)
from shared.signals.publisher import SignalPublisher

__all__ = [
    "GateResult",
    "SignalContext",
    "SignalDirection",
    "SignalEngine",
    "SignalPublisher",
    "SignalResult",
]
