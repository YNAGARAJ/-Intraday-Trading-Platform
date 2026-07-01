"""Data models for the M11 Signal Generation Agent.

`SignalContext` is the complete input bundle for one signal evaluation pass.
`SignalResult` is the output: gate verdicts, confidence, and trade parameters.
`GateResult` captures each gate's pass/fail and its contribution to confidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.patterns.models import MultiTimeframePatterns, PatternSnapshot
    from shared.regime.models import RegimeClassification
    from shared.sentiment.models import MarketSentiment
    from shared.storage.models import OHLCVCandle


class SignalDirection(str, Enum):
    """Direction of a generated signal."""

    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class GateResult:
    """Outcome of a single gate evaluation.

    Args:
        gate_number: Gate index 1-9.
        passed: True if the gate allowed the signal to proceed.
        reason: Human-readable description of the gate decision.
        confidence_contribution: Amount added to running confidence (gates 1-8).
            Zero for failed gates. Gate 8 may be negative (divergence penalty).
        confirming_indicators: Indicator names that agreed with the signal
            direction (populated by Gate 2 only).
        confirming_timeframes: Timeframes that confirmed the signal
            (populated by Gate 5 only).
        candlestick_pattern: Name of the candlestick pattern (Gate 4 only).
    """

    gate_number: int
    passed: bool
    reason: str
    confidence_contribution: float = 0.0
    confirming_indicators: list[str] = field(default_factory=list)
    confirming_timeframes: list[str] = field(default_factory=list)
    candlestick_pattern: str = ""


@dataclass(frozen=True)
class SignalContext:
    """All inputs required for one signal evaluation pass.

    The caller (M18 orchestrator or CLI) assembles this from live data
    snapshots and passes it to `SignalEngine.evaluate()`.

    Args:
        symbol: Instrument symbol, e.g. ``'RELIANCE'``.
        exchange: Exchange code, ``'NSE'`` or ``'ASX'``.
        direction: Proposed trade direction (``'LONG'`` or ``'SHORT'``).
        strategy_id: Up to 8-char strategy tag assigned by M09 watchlist.
        regime: Latest regime classification from M08.
        indicator_values: Indicator output dict keyed by indicator name
            for the primary timeframe (e.g. ``{'EMA': {'EMA_9': 22300.0, ...}}``.
        pattern_snapshot: Pattern detection results for the primary timeframe.
        multi_tf_patterns: Cross-timeframe pattern confirmation from M06 engine.
            ``None`` when only one timeframe is available.
        current_price: Most recent close price.
        current_volume: Volume of the current (most recent) bar.
        avg_volume: Rolling average volume (used for volume confirmation).
        atr: ATR(14) for stop-loss and target computation.
        is_snapshot_window: True when current time is within 14:45-15:30 IST.
        session_open: Session start time in UTC (for Gate 7).
        session_close: Session end time in UTC (for Gate 7 closing-window check).
        evaluated_at: Wall-clock UTC time when evaluation begins.
        candles: Raw OHLCV candles keyed by timeframe (oldest first).
            Used for divergence estimation in Gate 8.
        sentiment: Latest market sentiment from M10 (optional; Gate 8 input).
    """

    symbol: str
    exchange: str
    direction: str
    strategy_id: str
    regime: RegimeClassification
    indicator_values: Mapping[str, Mapping[str, float | None]]
    pattern_snapshot: PatternSnapshot
    multi_tf_patterns: MultiTimeframePatterns | None
    current_price: float
    current_volume: float
    avg_volume: float
    atr: float
    is_snapshot_window: bool
    session_open: datetime
    session_close: datetime
    evaluated_at: datetime
    candles: Mapping[str, Sequence[OHLCVCandle]]
    sentiment: MarketSentiment | None = None


@dataclass(frozen=True)
class SignalResult:
    """Output of a complete 9-gate signal evaluation.

    Args:
        generated: True only when all terminating gates passed and Gate 9
            confidence threshold was met.
        symbol: Instrument symbol.
        exchange: Exchange code.
        direction: Signal direction (``'LONG'`` or ``'SHORT'``).
        confidence: Final composite confidence in ``[0.0, 1.0]``.
        entry_price: Recommended entry price (current close).
        stop_loss: Hard stop-loss price (``entry ± ATR_STOP_LOSS_MULTIPLIER * atr``).
        target1: First profit target.
        target2: Second profit target.
        atr: ATR(14) used for stop/target calculation.
        strategy_id: Strategy tag (≤ 8 chars).
        gate_results: All gate outcomes in order (gates 1-9).
        failed_at_gate: Gate number that terminated evaluation, or ``None`` if
            all gates passed.
        confirming_indicators: Indicator names that agreed (from Gate 2).
        confirming_timeframes: Timeframes that confirmed (from Gate 5).
        candlestick_pattern: First confirming CDL pattern name (from Gate 4).
        regime: Regime string at evaluation time.
        evaluated_at: Wall-clock UTC time when evaluation completed.
    """

    generated: bool
    symbol: str
    exchange: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss: float
    target1: float
    target2: float
    atr: float
    strategy_id: str
    gate_results: list[GateResult]
    failed_at_gate: int | None
    confirming_indicators: list[str]
    confirming_timeframes: list[str]
    candlestick_pattern: str
    regime: str
    evaluated_at: datetime
