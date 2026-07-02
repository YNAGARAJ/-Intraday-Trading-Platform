"""Data models for M13 Compliance & Regulatory Engine.

``OrderIntent`` is the canonical pre-execution order descriptor used by M13
and imported by M14. ``ComplianceDecision`` is the output of every compliance
check — M14 refuses to submit any order that did not receive ``approved=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OrderIntent:
    """Pre-trade order descriptor submitted to the compliance engine before execution.

    Args:
        symbol: Instrument symbol (e.g. ``'RELIANCE'`` or ``'BHP'``).
        exchange: Market identifier — ``'NSE'``, ``'BSE'``, ``'ASX'``, or ``'PAPER'``.
        direction: ``'LONG'`` (buy) or ``'SHORT'`` (sell short).
        order_type: ``'MARKET'``, ``'LIMIT'``, ``'SL'``, or ``'MPP'``.
        quantity: Number of shares/contracts.
        price: Limit price; ``None`` for MARKET orders.
        stop_loss: Hard stop-loss price — mandatory, no exceptions (RULE 7).
        strategy_name: Logical strategy identifier (e.g. ``'EMA_VWAP_TREND'``).
            Resolved to a compressed broker tag by the compliance engine.
        client_order_id: Globally-unique idempotency key for this order intent.
            M14 uses this to detect duplicates on broker retry (never blind-retry).
        ltp: Last-traded price at the time of order construction, used for MPP
            limit price computation. Required when ``order_type`` is ``'MARKET'``.
        notional_value: Estimated notional (``quantity × entry_price``).
            Used for leverage and margin checks.
        capital: Total account capital. Used for leverage ratio computation.
        is_exit: True for SL-triggered exits and manual exits; False for entries.
            Exit orders bypass some entry-specific checks (MWPL, leverage entry guard).
        mwpl_pct: Current open-interest as % of Market Wide Position Limit for this
            symbol (India only). Caller fetches from M09/NSE. None = check skipped.
        sector: Sector label for the instrument (passed through from M09 watchlist).
    """

    symbol: str
    exchange: str
    direction: str
    order_type: str
    quantity: int
    price: float | None
    stop_loss: float
    strategy_name: str
    client_order_id: str
    ltp: float | None = None
    notional_value: float = 0.0
    capital: float = 0.0
    is_exit: bool = False
    mwpl_pct: float | None = None
    sector: str = "UNKNOWN"
    is_priority: bool = False


@dataclass(frozen=True)
class TaggedOrder:
    """``OrderIntent`` with compliance-resolved fields ready for M14 submission.

    Args:
        original: The input ``OrderIntent`` (unmodified).
        strategy_tag: Compressed ≤ 8-char broker tag resolved from ``strategy_name``.
        effective_order_type: Final order type after MPP conversion
            (``'MARKET'`` → ``'MPP'`` for NSE/BSE entries).
        mpp_price: Computed MPP limit price when ``effective_order_type`` is
            ``'MPP'``; ``None`` otherwise.
    """

    original: OrderIntent
    strategy_tag: str
    effective_order_type: str
    mpp_price: float | None = None


@dataclass(frozen=True)
class ComplianceViolation:
    """A single compliance rule violation.

    Args:
        code: Short machine-readable identifier (e.g. ``'NO_STRATEGY_ID'``).
        detail: Human-readable explanation.
    """

    code: str
    detail: str


@dataclass(frozen=True)
class ComplianceDecision:
    """Output of the compliance engine for one order.

    Args:
        approved: ``True`` only when all applicable rules passed.
        violations: Non-empty list describes every rule that fired. Empty on approve.
        tagged_order: Compliance-resolved order ready for M14. ``None`` on rejection.
        audit_id: Unique identifier for the compliance audit log entry.
    """

    approved: bool
    violations: list[ComplianceViolation]
    tagged_order: TaggedOrder | None
    audit_id: str


@dataclass(frozen=True)
class KillSwitchEvent:
    """Record of a kill switch activation (all three tiers produce this).

    Args:
        tier: Tier number that triggered (1, 2, or 3).
        reason: Human-readable trigger reason.
        triggered_at_ms: Unix epoch milliseconds at trigger time.
        is_priority: Always ``True`` — ONLY this dataclass ever sets it. Kill-switch
            and SL-exit code paths are the ONLY authorized setters (RULE 8).
    """

    tier: int
    reason: str
    triggered_at_ms: int
    is_priority: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if self.tier not in (1, 2, 3):
            raise ValueError(f"Kill switch tier must be 1, 2, or 3; got {self.tier}")


@dataclass(frozen=True)
class RecentOrder:
    """Lightweight snapshot of a recently placed order for wash-trade / layering checks.

    Args:
        symbol: Instrument symbol.
        direction: ``'LONG'`` or ``'SHORT'``.
        placed_at_ms: Unix epoch milliseconds when the order was placed.
    """

    symbol: str
    direction: str
    placed_at_ms: int
