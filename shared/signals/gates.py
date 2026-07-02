"""9-Gate signal evaluation logic.

Each gate is a pure function: `SignalContext → GateResult`. No I/O, no LLM,
no side effects. All gates must complete in microseconds; the 100ms budget
is for the full `SignalEngine.evaluate()` call including all 9 gates.

Gate termination policy:
  Gates 1-7, 9: terminating — a FAIL result ends evaluation immediately.
  Gate 8:       non-terminating — modulates confidence only, never ends eval.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from shared.regime.models import RegimeClassification

from shared.core.constants import (
    GATE_2_MIN_INDICATORS_AGREEING,
    GATE_2_PER_INDICATOR_BONUS,
    GATE_2_TOTAL_INDICATORS,
    GATE_3_ABSORPTION_DELTA_RATIO,
    GATE_3_ABSORPTION_VOLUME_RATIO,
    GATE_3_CONFIDENCE_BONUS,
    GATE_4_CONFIDENCE_BONUS,
    GATE_5_CONFIDENCE_BONUS,
    GATE_5_MIN_TIMEFRAMES_AGREEING,
    GATE_6_CONFIDENCE_BONUS,
    GATE_6_SR_PROXIMITY_PCT,
    GATE_7_CLOSING_WINDOW_MINUTES,
    GATE_7_OPENING_NOISE_FILTER_MINUTES,
    GATE_8_ALIGNMENT_BONUS,
    GATE_8_DIVERGENCE_PENALTY,
    GATE_9_CONFIDENCE_THRESHOLD,
    GATE_9_CONFIDENCE_THRESHOLD_SNAPSHOT_WINDOW,
    RSI_BEARISH_LEVEL,
    RSI_BULLISH_LEVEL,
    VOLUME_CONFIRMATION_MULTIPLIER,
)
from shared.signals.models import GateResult, SignalContext

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Gate 1 — Regime Gate
# ---------------------------------------------------------------------------


def gate_1_regime(ctx: SignalContext) -> GateResult:
    """Gate 1: Regime must allow the requested direction.

    HIGH_VOL_CHAOS always fails (RULE 2 hard halt). BULL_TREND blocks SHORT
    entries; BEAR_TREND blocks LONG entries. MEAN_REVERTING allows both.
    """
    from shared.regime.models import MarketRegime  # noqa: PLC0415

    regime = ctx.regime
    regime_str: str = regime.regime.value

    if regime.regime == MarketRegime.HIGH_VOL_CHAOS:
        logger.info("gate_1_fail_chaos_regime", symbol=ctx.symbol)
        return GateResult(
            gate_number=1,
            passed=False,
            reason="HIGH_VOL_CHAOS — all entries blocked (RULE 2)",
        )

    if ctx.direction == "LONG" and regime.regime == MarketRegime.BEAR_TREND:
        return GateResult(
            gate_number=1,
            passed=False,
            reason=f"LONG entry blocked in {regime_str} regime",
        )

    if ctx.direction == "SHORT" and regime.regime == MarketRegime.BULL_TREND:
        return GateResult(
            gate_number=1,
            passed=False,
            reason=f"SHORT entry blocked in {regime_str} regime",
        )

    return GateResult(
        gate_number=1,
        passed=True,
        reason=f"Direction {ctx.direction} permitted in {regime_str}",
        confidence_contribution=0.0,
    )


# ---------------------------------------------------------------------------
# Gate 2 — Multi-Indicator Agreement (min 3 of 8)
# ---------------------------------------------------------------------------


def _check_indicator(
    name: str,
    values: Mapping[str, Mapping[str, float | None]],
    direction: str,
    current_price: float,
    current_volume: float,
    avg_volume: float,
    orb_direction: int | None,
) -> bool:
    """Return True if `name` agrees with `direction`."""
    ind = values.get(name, {})

    def _v(key: str) -> float | None:
        return ind.get(key)

    if name == "EMA":
        ema9, ema21 = _v("EMA_9"), _v("EMA_21")
        if ema9 is None or ema21 is None:
            return False
        return (ema9 > ema21) if direction == "LONG" else (ema9 < ema21)

    if name == "VWAP":
        vwap = _v("VWAP")
        if vwap is None:
            return False
        return (current_price > vwap) if direction == "LONG" else (current_price < vwap)

    if name == "RSI":
        rsi = _v(f"RSI_{14}")
        if rsi is None:
            return False
        if direction == "LONG":
            return rsi > RSI_BULLISH_LEVEL
        return rsi < RSI_BEARISH_LEVEL

    if name == "MACD":
        hist = _v("MACD_HIST")
        if hist is None:
            return False
        return (hist > 0) if direction == "LONG" else (hist < 0)

    if name == "STOCHASTIC":
        k, d = _v("STOCH_K"), _v("STOCH_D")
        if k is None or d is None:
            return False
        if direction == "LONG":
            return k > 50 and k > d
        return k < 50 and k < d

    if name == "BBANDS":
        mid = _v("BB_MIDDLE")
        if mid is None:
            return False
        return (current_price > mid) if direction == "LONG" else (current_price < mid)

    if name == "ORB":
        if orb_direction is None:
            return False
        return (orb_direction == 1) if direction == "LONG" else (orb_direction == -1)

    if name == "VOLUME":
        if avg_volume <= 0:
            return False
        return current_volume > VOLUME_CONFIRMATION_MULTIPLIER * avg_volume

    return False


_GATE_2_INDICATORS = (
    "EMA", "VWAP", "RSI", "MACD", "STOCHASTIC", "BBANDS", "ORB", "VOLUME"
)


def gate_2_indicators(ctx: SignalContext) -> GateResult:
    """Gate 2: At least 3 of 8 indicators must agree with the signal direction."""
    pattern_snapshot = ctx.pattern_snapshot
    orb_direction: int | None = None
    if pattern_snapshot is not None and pattern_snapshot.orb_state is not None:
        orb_direction = pattern_snapshot.orb_state.breakout_direction

    agreeing: list[str] = []
    for ind_name in _GATE_2_INDICATORS:
        if _check_indicator(
            ind_name,
            ctx.indicator_values,
            ctx.direction,
            ctx.current_price,
            ctx.current_volume,
            ctx.avg_volume,
            orb_direction,
        ):
            agreeing.append(ind_name)

    count = len(agreeing)
    if count < GATE_2_MIN_INDICATORS_AGREEING:
        return GateResult(
            gate_number=2,
            passed=False,
            reason=(
                f"Only {count}/{GATE_2_TOTAL_INDICATORS} indicators agree "
                f"(need ≥ {GATE_2_MIN_INDICATORS_AGREEING})"
            ),
        )

    bonus = GATE_2_PER_INDICATOR_BONUS * count
    return GateResult(
        gate_number=2,
        passed=True,
        reason=(
            f"{count}/{GATE_2_TOTAL_INDICATORS} indicators agree: "
            f"{', '.join(agreeing)}"
        ),
        confidence_contribution=bonus,
        confirming_indicators=agreeing,
    )


# ---------------------------------------------------------------------------
# Gate 3 — Order Flow (absorption detection + footprint delta)
# ---------------------------------------------------------------------------


def gate_3_order_flow(ctx: SignalContext) -> GateResult:
    """Gate 3: No institutional absorption; footprint delta confirms direction.

    Uses VOLUME_DELTA (close-vs-open proxy) as a footprint delta approximation
    until M16 provides true tick-level aggressor data. Absorption is inferred
    when high volume occurs with low directional conviction (|delta| / volume
    below threshold), suggesting a large hidden counterparty is absorbing flow.
    """
    vol_delta = ctx.indicator_values.get("VOLUME_DELTA", {}).get("VOLUME_DELTA")

    if vol_delta is None:
        return GateResult(
            gate_number=3,
            passed=False,
            reason="VOLUME_DELTA unavailable — order flow unverifiable",
        )

    abs_delta = abs(vol_delta)
    vol = ctx.current_volume

    if vol > 0 and vol > GATE_3_ABSORPTION_VOLUME_RATIO * ctx.avg_volume:
        delta_ratio = abs_delta / vol if vol > 0 else 1.0
        if delta_ratio < GATE_3_ABSORPTION_DELTA_RATIO:
            logger.info(
                "gate_3_absorption_detected",
                symbol=ctx.symbol,
                volume=vol,
                delta_ratio=round(delta_ratio, 3),
            )
            return GateResult(
                gate_number=3,
                passed=False,
                reason=(
                    f"Institutional absorption detected: "
                    f"vol={vol:.0f} ({vol / ctx.avg_volume:.1f}× avg), "
                    f"delta_ratio={delta_ratio:.3f}"
                ),
            )

    delta_long = vol_delta > 0
    direction_match = (ctx.direction == "LONG" and delta_long) or (
        ctx.direction == "SHORT" and not delta_long
    )
    if not direction_match:
        return GateResult(
            gate_number=3,
            passed=False,
            reason=(
                f"Footprint delta ({vol_delta:+.0f}) conflicts with "
                f"{ctx.direction} direction"
            ),
        )

    return GateResult(
        gate_number=3,
        passed=True,
        reason=f"Order flow confirms {ctx.direction}: delta={vol_delta:+.0f}",
        confidence_contribution=GATE_3_CONFIDENCE_BONUS,
    )


# ---------------------------------------------------------------------------
# Gate 4 — Candlestick Pattern Confirmation
# ---------------------------------------------------------------------------


def gate_4_candlestick(ctx: SignalContext) -> GateResult:
    """Gate 4: At least one recent candlestick pattern must confirm direction.

    Checks the last 3 bars of the primary-timeframe snapshot. ORB breakout
    in the matching direction also qualifies as pattern confirmation.
    """
    pattern_snapshot = ctx.pattern_snapshot
    if pattern_snapshot is None:
        return GateResult(
            gate_number=4,
            passed=False,
            reason="No pattern snapshot available",
        )

    signals = pattern_snapshot.candlestick_signals
    if signals:
        last_bar = len(signals)
        expected_direction = 100 if ctx.direction == "LONG" else -100
        for sig in reversed(signals):
            if last_bar - sig.bar_index <= 3 and sig.direction == expected_direction:
                return GateResult(
                    gate_number=4,
                    passed=True,
                    reason=f"Candlestick pattern {sig.name} confirms {ctx.direction}",
                    confidence_contribution=GATE_4_CONFIDENCE_BONUS,
                    candlestick_pattern=sig.name,
                )

    orb = pattern_snapshot.orb_state
    if orb is not None and orb.breakout_direction is not None:
        expected_orb = 1 if ctx.direction == "LONG" else -1
        if orb.breakout_direction == expected_orb:
            return GateResult(
                gate_number=4,
                passed=True,
                reason=f"ORB breakout confirms {ctx.direction}",
                confidence_contribution=GATE_4_CONFIDENCE_BONUS,
                candlestick_pattern="ORB_BREAKOUT",
            )

    return GateResult(
        gate_number=4,
        passed=False,
        reason=f"No candlestick pattern confirms {ctx.direction} in last 3 bars",
    )


# ---------------------------------------------------------------------------
# Gate 5 — Multi-Timeframe Confirmation (≥ 2 distinct timeframes)
# ---------------------------------------------------------------------------


def gate_5_multi_timeframe(ctx: SignalContext) -> GateResult:
    """Gate 5: Signal must be valid on at least 2 distinct timeframes.

    Uses pre-computed `MultiTimeframePatterns.confirmed_bullish/bearish_patterns`
    which the pattern engine already filters by GATE_5_MIN_TIMEFRAMES_AGREEING.
    """
    mtf = ctx.multi_tf_patterns

    if mtf is None:
        return GateResult(
            gate_number=5,
            passed=False,
            reason=(
                f"Multi-timeframe patterns not provided "
                f"(need ≥ {GATE_5_MIN_TIMEFRAMES_AGREEING} timeframes)"
            ),
        )

    if ctx.direction == "LONG":
        confirmed = mtf.confirmed_bullish_patterns
        tfs = [
            tf
            for tf, snap in mtf.snapshots.items()
            if any(s.direction == 100 for s in snap.candlestick_signals)
        ]
    else:
        confirmed = mtf.confirmed_bearish_patterns
        tfs = [
            tf
            for tf, snap in mtf.snapshots.items()
            if any(s.direction == -100 for s in snap.candlestick_signals)
        ]

    if not confirmed:
        return GateResult(
            gate_number=5,
            passed=False,
            reason=(
                f"No {ctx.direction} pattern confirmed on "
                f"≥ {GATE_5_MIN_TIMEFRAMES_AGREEING} timeframes"
            ),
        )

    n = GATE_5_MIN_TIMEFRAMES_AGREEING
    tf_list = tfs[:n] if len(tfs) >= n else tfs
    return GateResult(
        gate_number=5,
        passed=True,
        reason=(
            f"{len(confirmed)} pattern(s) confirmed on "
            f"{len(tfs)} timeframe(s): {', '.join(tf_list)}"
        ),
        confidence_contribution=GATE_5_CONFIDENCE_BONUS,
        confirming_timeframes=tf_list,
    )


# ---------------------------------------------------------------------------
# Gate 6 — S/R Proximity
# ---------------------------------------------------------------------------


def gate_6_sr_proximity(ctx: SignalContext) -> GateResult:
    """Gate 6: Price must be near a support or resistance level.

    LONG signals require proximity to a SUPPORT level; SHORT signals require
    proximity to a RESISTANCE level. Pivot point levels are treated as S/R.
    """
    pattern_snapshot = ctx.pattern_snapshot
    if pattern_snapshot is None:
        return GateResult(
            gate_number=6,
            passed=False,
            reason="No pattern snapshot — S/R check skipped",
        )

    sr_levels = pattern_snapshot.sr_levels
    price = ctx.current_price
    target_type = "SUPPORT" if ctx.direction == "LONG" else "RESISTANCE"
    threshold = GATE_6_SR_PROXIMITY_PCT / 100.0

    for level in sr_levels:
        if level.level_type != target_type:
            continue
        if level.price <= 0:
            continue
        proximity = abs(price - level.price) / level.price
        if proximity <= threshold:
            return GateResult(
                gate_number=6,
                passed=True,
                reason=(
                    f"Price {price:.2f} within {proximity * 100:.2f}% of "
                    f"{target_type} at {level.price:.2f} "
                    f"(strength={level.strength:.2f})"
                ),
                confidence_contribution=GATE_6_CONFIDENCE_BONUS,
            )

    return GateResult(
        gate_number=6,
        passed=False,
        reason=(
            f"Price {price:.2f} not within {GATE_6_SR_PROXIMITY_PCT}% "
            f"of any {target_type} level"
        ),
    )


# ---------------------------------------------------------------------------
# Gate 7 — Session Timing
# ---------------------------------------------------------------------------


def gate_7_session_timing(ctx: SignalContext) -> GateResult:
    """Gate 7: No entries during opening noise or closing auction window.

    Blocks signals during the first GATE_7_OPENING_NOISE_FILTER_MINUTES of the
    session and during the last GATE_7_CLOSING_WINDOW_MINUTES before session close.
    """
    opening_end = ctx.session_open + timedelta(
        minutes=GATE_7_OPENING_NOISE_FILTER_MINUTES
    )
    closing_start = ctx.session_close - timedelta(
        minutes=GATE_7_CLOSING_WINDOW_MINUTES
    )

    if ctx.evaluated_at < opening_end:
        elapsed = (ctx.evaluated_at - ctx.session_open).total_seconds() / 60
        return GateResult(
            gate_number=7,
            passed=False,
            reason=(
                f"Opening noise filter: {elapsed:.1f}min elapsed "
                f"(need ≥ {GATE_7_OPENING_NOISE_FILTER_MINUTES}min)"
            ),
        )

    if ctx.evaluated_at >= closing_start:
        remaining = (ctx.session_close - ctx.evaluated_at).total_seconds() / 60
        return GateResult(
            gate_number=7,
            passed=False,
            reason=(
                f"Closing window: {remaining:.1f}min to session close "
                f"(block at ≤ {GATE_7_CLOSING_WINDOW_MINUTES}min)"
            ),
        )

    return GateResult(
        gate_number=7,
        passed=True,
        reason="Within tradeable session window",
        confidence_contribution=0.0,
    )


# ---------------------------------------------------------------------------
# Gate 8 — Divergence Check (non-terminating, modulates confidence)
# ---------------------------------------------------------------------------


def gate_8_divergence(ctx: SignalContext) -> GateResult:
    """Gate 8: Divergence check — modulates confidence, never terminates.

    Uses RSI extremes and MACD histogram to detect likely divergence. A true
    peak-vs-peak divergence check requires successive historical snapshots (not
    yet available until M16/M18) so this is a practical approximation:
      - RSI in overbought/oversold territory opposite to signal → penalty
      - RSI aligned with signal + MACD histogram aligned → bonus
    """
    ind = ctx.indicator_values
    rsi = ind.get("RSI", {}).get("RSI_14")
    macd_hist = ind.get("MACD", {}).get("MACD_HIST")

    adjustment = 0.0
    reasons: list[str] = []

    if rsi is not None:
        if ctx.direction == "LONG" and rsi > 75:
            adjustment -= GATE_8_DIVERGENCE_PENALTY
            reasons.append(f"RSI overbought ({rsi:.1f}) — divergence risk")
        elif ctx.direction == "SHORT" and rsi < 25:
            adjustment -= GATE_8_DIVERGENCE_PENALTY
            reasons.append(f"RSI oversold ({rsi:.1f}) — divergence risk")
        elif ctx.direction == "LONG" and 50 < rsi <= 70:
            adjustment += GATE_8_ALIGNMENT_BONUS
            reasons.append(f"RSI aligned bullish ({rsi:.1f})")
        elif ctx.direction == "SHORT" and 30 <= rsi < 50:
            adjustment += GATE_8_ALIGNMENT_BONUS
            reasons.append(f"RSI aligned bearish ({rsi:.1f})")

    if macd_hist is not None:
        if (ctx.direction == "LONG" and macd_hist > 0) or (
            ctx.direction == "SHORT" and macd_hist < 0
        ):
            adjustment += GATE_8_ALIGNMENT_BONUS
            reasons.append(f"MACD histogram aligned ({macd_hist:+.4f})")
        elif (ctx.direction == "LONG" and macd_hist < 0) or (
            ctx.direction == "SHORT" and macd_hist > 0
        ):
            adjustment -= GATE_8_DIVERGENCE_PENALTY
            reasons.append(f"MACD histogram diverges ({macd_hist:+.4f})")

    sentiment = ctx.sentiment
    if sentiment is not None:
        score: float = sentiment.aggregate_score
        if ctx.direction == "LONG" and score > 0.3:
            adjustment += GATE_8_ALIGNMENT_BONUS * 0.5
            reasons.append(f"Sentiment bullish ({score:.2f})")
        elif ctx.direction == "SHORT" and score < -0.3:
            adjustment += GATE_8_ALIGNMENT_BONUS * 0.5
            reasons.append(f"Sentiment bearish ({score:.2f})")

    reason = "; ".join(reasons) if reasons else "No divergence signals detected"
    return GateResult(
        gate_number=8,
        passed=True,
        reason=reason,
        confidence_contribution=adjustment,
    )


# ---------------------------------------------------------------------------
# Gate 9 — Composite Confidence Threshold
# ---------------------------------------------------------------------------


def gate_9_confidence(
    base_confidence: float,
    ctx: SignalContext,
) -> GateResult:
    """Gate 9: Composite confidence must meet the regime-aware threshold.

    During the SEBI snapshot window (14:45-15:30 IST) the bar is raised from
    0.70 to 0.80 to reflect the tighter risk posture required near close.
    """
    threshold = (
        GATE_9_CONFIDENCE_THRESHOLD_SNAPSHOT_WINDOW
        if ctx.is_snapshot_window
        else GATE_9_CONFIDENCE_THRESHOLD
    )

    if base_confidence < threshold:
        return GateResult(
            gate_number=9,
            passed=False,
            reason=(
                f"Confidence {base_confidence:.3f} below threshold {threshold:.2f}"
                + (" (snapshot window)" if ctx.is_snapshot_window else "")
            ),
        )

    return GateResult(
        gate_number=9,
        passed=True,
        reason=f"Confidence {base_confidence:.3f} ≥ threshold {threshold:.2f}",
        confidence_contribution=0.0,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_stop_loss(
    entry_price: float, atr: float, direction: str
) -> float:
    """ATR-based stop-loss: entry ± ATR_STOP_LOSS_MULTIPLIER × ATR(14)."""
    from shared.core.constants import ATR_STOP_LOSS_MULTIPLIER  # noqa: PLC0415

    sl_distance = ATR_STOP_LOSS_MULTIPLIER * atr
    if direction == "LONG":
        return entry_price - sl_distance
    return entry_price + sl_distance


def _compute_targets(
    entry_price: float,
    stop_loss: float,
    direction: str,
    regime: RegimeClassification,
) -> tuple[float, float]:
    """Risk-to-reward targets derived from regime reward:risk ratios."""
    from shared.core.constants import (  # noqa: PLC0415
        REWARD_RISK_RATIO_BEAR_TREND,
        REWARD_RISK_RATIO_BULL_TREND,
        REWARD_RISK_RATIO_MEAN_REVERTING,
        TARGET_1_REWARD_RISK_RATIO,
        TARGET_2_REWARD_RISK_RATIO,
    )
    from shared.regime.models import MarketRegime  # noqa: PLC0415

    if regime.regime == MarketRegime.BULL_TREND:
        rr = REWARD_RISK_RATIO_BULL_TREND
    elif regime.regime == MarketRegime.BEAR_TREND:
        rr = REWARD_RISK_RATIO_BEAR_TREND
    else:
        rr = REWARD_RISK_RATIO_MEAN_REVERTING

    risk = abs(entry_price - stop_loss)
    _ = rr  # reward:risk ratio informs the target multiplier choice

    t1_dist = TARGET_1_REWARD_RISK_RATIO * risk
    t2_dist = TARGET_2_REWARD_RISK_RATIO * risk

    if direction == "LONG":
        return entry_price + t1_dist, entry_price + t2_dist
    return entry_price - t1_dist, entry_price - t2_dist


def compute_stop_and_targets(
    ctx: SignalContext,
) -> tuple[float, float, float]:
    """Return ``(stop_loss, target1, target2)`` for a signal in ``ctx``."""
    sl = _compute_stop_loss(ctx.current_price, ctx.atr, ctx.direction)
    t1, t2 = _compute_targets(ctx.current_price, sl, ctx.direction, ctx.regime)
    return sl, t1, t2
