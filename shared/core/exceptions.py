"""System exception hierarchy.

Every exception that crosses a module boundary for a trading-relevant reason should
derive from `TradingSystemError` so callers can catch broadly when needed (e.g., the
orchestrator's error tracking fields in TradingSystemState) while still catching
narrowly in normal operation.
"""


class TradingSystemError(Exception):
    """Base class for all trading-system-specific exceptions."""


class ConfigValidationError(TradingSystemError):
    """Raised when Settings or region config fails fail-fast validation at startup."""


class MarketClosedError(TradingSystemError):
    """Raised by the `@market_hours_only` decorator (M02) outside the session window."""


class NoStopLossError(TradingSystemError):
    """Raised before any broker call if an order lacks stop-loss metadata (RULE 7)."""


class InsufficientMarginError(TradingSystemError):
    """Raised when `margin_guard.lua` / `sl_linkage.lua` reject insufficient margin."""


class RateLimitExceededError(TradingSystemError):
    """Raised when `rate_limiter.lua` rejects a non-priority request over the
    throttle."""


class ComplianceViolationError(TradingSystemError):
    """Raised by the Compliance & Regulatory Engine (M13) on a hard-blocked order."""


class KillSwitchActiveError(TradingSystemError):
    """Raised when an operation is attempted while `system:status:halted` is set."""


class ReconciliationMismatchError(TradingSystemError):
    """Raised by the Reconciliation Agent (M17) on internal-vs-broker divergence."""


class OrderIdempotencyError(TradingSystemError):
    """Raised by the Execution Engine (M14) on a duplicate client_order_id without a
    corresponding broker-side resolution -- signals a retry-safety invariant violation.
    """
