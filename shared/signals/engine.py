"""Signal evaluation engine: orchestrates all 9 gates.

`SignalEngine.evaluate()` is the hot-path entry point. It must complete in
< 100ms (RULE 4). All I/O happens before the call; the engine itself is
pure computation with no network or disk access.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog

from shared.core.constants import (
    GATE_2_INDICATOR_BASE_CONFIDENCE,
    SIGNAL_EXPIRY_MINUTES,
)
from shared.signals.gates import (
    compute_stop_and_targets,
    gate_1_regime,
    gate_2_indicators,
    gate_3_order_flow,
    gate_4_candlestick,
    gate_5_multi_timeframe,
    gate_6_sr_proximity,
    gate_7_session_timing,
    gate_8_divergence,
    gate_9_confidence,
)
from shared.signals.models import GateResult, SignalContext, SignalResult

logger = structlog.get_logger(__name__)

# Gates that terminate evaluation on failure (all except Gate 8).
_TERMINATING_GATES = frozenset({1, 2, 3, 4, 5, 6, 7, 9})


def _failed_result(
    ctx: SignalContext,
    gate_results: list[GateResult],
    failed_gate: int,
) -> SignalResult:
    """Build a `SignalResult` for a signal that failed at `failed_gate`."""
    regime_str: str = ctx.regime.regime.value
    return SignalResult(
        generated=False,
        symbol=ctx.symbol,
        exchange=ctx.exchange,
        direction=ctx.direction,
        confidence=0.0,
        entry_price=ctx.current_price,
        stop_loss=0.0,
        target1=0.0,
        target2=0.0,
        atr=ctx.atr,
        strategy_id=ctx.strategy_id,
        gate_results=gate_results,
        failed_at_gate=failed_gate,
        confirming_indicators=[],
        confirming_timeframes=[],
        candlestick_pattern="",
        regime=regime_str,
        evaluated_at=ctx.evaluated_at,
    )


class SignalEngine:
    """Evaluates a `SignalContext` through all 9 gates and produces a `SignalResult`.

    Thread-safe and stateless: all state is in `SignalContext`. One instance
    can serve multiple concurrent evaluations.
    """

    def evaluate(self, ctx: SignalContext) -> SignalResult:
        """Run all 9 gates and return a `SignalResult`.

        Args:
            ctx: Fully assembled signal context for one evaluation pass.

        Returns:
            `SignalResult` with ``generated=True`` only when all terminating
            gates passed and Gate 9 confidence threshold was met.
        """
        t0 = time.monotonic()

        gate_results: list[GateResult] = []
        running_confidence = GATE_2_INDICATOR_BASE_CONFIDENCE

        # --- Gates 1-7 (terminating) ---
        for gate_fn, gate_num in (
            (gate_1_regime, 1),
            (gate_2_indicators, 2),
            (gate_3_order_flow, 3),
            (gate_4_candlestick, 4),
            (gate_5_multi_timeframe, 5),
            (gate_6_sr_proximity, 6),
            (gate_7_session_timing, 7),
        ):
            result = gate_fn(ctx)
            gate_results.append(result)
            if not result.passed:
                elapsed_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "signal_gate_fail",
                    symbol=ctx.symbol,
                    gate=gate_num,
                    reason=result.reason,
                    elapsed_ms=round(elapsed_ms, 2),
                )
                return _failed_result(ctx, gate_results, gate_num)
            running_confidence += result.confidence_contribution

        # --- Gate 8 (non-terminating — modulates confidence) ---
        g8 = gate_8_divergence(ctx)
        gate_results.append(g8)
        running_confidence += g8.confidence_contribution
        running_confidence = max(0.0, min(1.0, running_confidence))

        # --- Gate 9 (terminating — confidence threshold) ---
        g9 = gate_9_confidence(running_confidence, ctx)
        gate_results.append(g9)
        if not g9.passed:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "signal_gate_fail",
                symbol=ctx.symbol,
                gate=9,
                reason=g9.reason,
                elapsed_ms=round(elapsed_ms, 2),
            )
            return _failed_result(ctx, gate_results, 9)

        # --- All gates passed — build successful result ---
        stop_loss, target1, target2 = compute_stop_and_targets(ctx)

        confirming_indicators: list[str] = []
        confirming_timeframes: list[str] = []
        candlestick_pattern = ""
        for gr in gate_results:
            if gr.confirming_indicators:
                confirming_indicators = gr.confirming_indicators
            if gr.confirming_timeframes:
                confirming_timeframes = gr.confirming_timeframes
            if gr.candlestick_pattern:
                candlestick_pattern = gr.candlestick_pattern

        regime_str: str = ctx.regime.regime.value

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "signal_generated",
            symbol=ctx.symbol,
            exchange=ctx.exchange,
            direction=ctx.direction,
            confidence=round(running_confidence, 3),
            regime=regime_str,
            elapsed_ms=round(elapsed_ms, 2),
        )

        if elapsed_ms > 100:
            logger.warning(
                "signal_engine_over_budget",
                symbol=ctx.symbol,
                elapsed_ms=round(elapsed_ms, 2),
                budget_ms=100,
            )

        return SignalResult(
            generated=True,
            symbol=ctx.symbol,
            exchange=ctx.exchange,
            direction=ctx.direction,
            confidence=round(running_confidence, 4),
            entry_price=ctx.current_price,
            stop_loss=round(stop_loss, 4),
            target1=round(target1, 4),
            target2=round(target2, 4),
            atr=ctx.atr,
            strategy_id=ctx.strategy_id,
            gate_results=gate_results,
            failed_at_gate=None,
            confirming_indicators=confirming_indicators,
            confirming_timeframes=confirming_timeframes,
            candlestick_pattern=candlestick_pattern,
            regime=regime_str,
            evaluated_at=datetime.now(UTC),
        )

    def signal_expiry_ms(self, evaluated_at: datetime) -> int:
        """Return Unix ms expiry timestamp for a signal generated at `evaluated_at`."""
        from datetime import timedelta  # noqa: PLC0415

        expiry = evaluated_at + timedelta(minutes=SIGNAL_EXPIRY_MINUTES)
        return int(expiry.timestamp() * 1000)
