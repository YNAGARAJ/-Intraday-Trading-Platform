"""CLI for M11 Signal Generation Agent.

Replays historical ticks for one symbol and evaluates the 9-gate system.
Used for the VERIFY scenario: confirm signals fire correctly and that zero
signals are generated during HIGH_VOL_CHAOS periods.

Usage:
    python -m shared.signals --help
    python -m shared.signals replay RELIANCE.NS --exchange NSE
    python -m shared.signals replay RELIANCE.NS --exchange NSE --chaos-only
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

import structlog

from shared.core.logging import configure_logging

logger = structlog.get_logger(__name__)


def _build_mock_context(
    symbol: str,
    exchange: str,
    direction: str,
    chaos: bool,
) -> object:
    """Build a minimal SignalContext suitable for VERIFY / CLI replay."""

    from shared.patterns.models import MultiTimeframePatterns, PatternSnapshot
    from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures
    from shared.signals.models import SignalContext

    if chaos:
        regime_val = MarketRegime.HIGH_VOL_CHAOS
    elif direction == "LONG":
        regime_val = MarketRegime.BULL_TREND
    else:
        regime_val = MarketRegime.BEAR_TREND

    features = RegimeFeatures(
        adx=30.0 if not chaos else 10.0,
        rsi=60.0 if direction == "LONG" else 40.0,
        bb_width_pct=2.0,
        atr_pct=1.0,
        vwap_deviation_pct=0.2,
        volume_ratio=1.8,
        vix=14.0 if not chaos else 30.0,
        atr_spike=chaos,
    )
    regime = RegimeClassification(
        regime=regime_val,
        confidence=0.85,
        features=features,
        hmm_state=0,
        classified_at=datetime.now(UTC),
    )

    price = 2450.0
    vwap = price * 0.998 if direction == "LONG" else price * 1.002
    ema9 = price * 1.001 if direction == "LONG" else price * 0.999
    ema21 = price * 0.998 if direction == "LONG" else price * 1.002
    rsi_val = 62.0 if direction == "LONG" else 38.0
    macd_hist = 5.0 if direction == "LONG" else -5.0
    stoch_k = 60.0 if direction == "LONG" else 40.0
    stoch_d = 55.0 if direction == "LONG" else 45.0
    bb_mid = price * 0.999 if direction == "LONG" else price * 1.001

    indicator_values = {
        "EMA": {
            "EMA_9": ema9, "EMA_21": ema21,
            "EMA_50": ema21 * 0.99, "EMA_200": ema21 * 0.97,
        },
        "VWAP": {"VWAP": vwap},
        "RSI": {"RSI_14": rsi_val},
        "MACD": {"MACD": 10.0, "MACD_SIGNAL": 8.0, "MACD_HIST": macd_hist},
        "STOCHASTIC": {"STOCH_K": stoch_k, "STOCH_D": stoch_d},
        "BBANDS": {
            "BB_UPPER": price * 1.01, "BB_MIDDLE": bb_mid, "BB_LOWER": price * 0.99,
        },
        "VOLUME_DELTA": {"VOLUME_DELTA": 50000.0 if direction == "LONG" else -50000.0},
    }

    from shared.patterns.models import (  # noqa: PLC0415
        CandlestickSignal,
        ORBState,
        SRLevel,
    )
    from shared.storage.models import OHLCVCandle  # noqa: PLC0415

    now = datetime.now(UTC)
    session_open = now.replace(hour=3, minute=45, second=0, microsecond=0)

    candles = [
        OHLCVCandle(
            time=session_open + timedelta(minutes=i),
            symbol=symbol,
            exchange=exchange,
            open=price,
            high=price * 1.003,
            low=price * 0.997,
            close=price * (1.001 if direction == "LONG" else 0.999),
            volume=120000,
        )
        for i in range(30)
    ]

    cdl_dir = 100 if direction == "LONG" else -100
    cdl_signal = CandlestickSignal(name="CDLHAMMER", direction=cdl_dir, bar_index=28)
    orb_dir = 1 if direction == "LONG" else -1
    orb_state = ORBState(
        orb_high=price * 1.002,
        orb_low=price * 0.998,
        orb_range=price * 0.004,
        session_open=session_open,
        range_formed=True,
        breakout_direction=orb_dir,
        breakout_price=price * (1.002 if direction == "LONG" else 0.998),
    )
    sr_type = "SUPPORT" if direction == "LONG" else "RESISTANCE"
    sr_level = SRLevel(
        price=price * (0.999 if direction == "LONG" else 1.001),
        level_type=sr_type,
        strength=0.8,
        touches=3,
        last_touch_bar=25,
    )
    snap = PatternSnapshot(
        symbol=symbol,
        exchange=exchange,
        timeframe="5m",
        computed_at=now,
        candle_time=candles[-1].time,
        candlestick_signals=[cdl_signal],
        orb_state=orb_state,
        sr_levels=[sr_level],
    )
    snap_1h = PatternSnapshot(
        symbol=symbol,
        exchange=exchange,
        timeframe="1h",
        computed_at=now,
        candle_time=candles[-1].time,
        candlestick_signals=[cdl_signal],
        orb_state=None,
        sr_levels=[sr_level],
    )
    mtf = MultiTimeframePatterns(
        symbol=symbol,
        exchange=exchange,
        computed_at=now,
        snapshots={"5m": snap, "1h": snap_1h},
        confirmed_bullish_patterns=["CDLHAMMER"] if direction == "LONG" else [],
        confirmed_bearish_patterns=["CDLHAMMER"] if direction == "SHORT" else [],
    )

    session_close = now.replace(hour=10, minute=0, second=0, microsecond=0)
    eval_time = now.replace(hour=7, minute=0, second=0, microsecond=0)

    return SignalContext(
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        strategy_id="EMAVWAP1",
        regime=regime,
        indicator_values=indicator_values,
        pattern_snapshot=snap,
        multi_tf_patterns=mtf,
        current_price=price,
        current_volume=150000.0,
        avg_volume=100000.0,
        atr=25.0,
        is_snapshot_window=False,
        session_open=session_open,
        session_close=session_close,
        evaluated_at=eval_time,
        candles={"5m": candles},
        sentiment=None,
    )


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a synthetic signal evaluation and print results."""
    from shared.signals.engine import SignalEngine  # noqa: PLC0415

    engine = SignalEngine()
    directions = ["LONG", "SHORT"] if not args.direction else [args.direction.upper()]

    print(f"\n=== M11 Signal Generation Agent — VERIFY replay for {args.symbol} ===\n")

    if args.chaos_only:
        ctx = _build_mock_context(args.symbol, args.exchange, "LONG", chaos=True)
        result = engine.evaluate(ctx)  # type: ignore[arg-type]
        print("Chaos regime test:")
        print(f"  Generated: {result.generated}")
        if not result.generated:
            gate_num = result.failed_at_gate
            if gate_num is not None:
                reason = result.gate_results[gate_num - 1].reason
                print(f"  Blocked at Gate {gate_num}: {reason}")
        assert not result.generated, "VERIFY FAIL: signal generated in HIGH_VOL_CHAOS!"
        print("  PASS: Zero signals during chaos regime confirmed.\n")
        return 0

    all_passed = True
    for direction in directions:
        ctx = _build_mock_context(args.symbol, args.exchange, direction, chaos=False)
        result = engine.evaluate(ctx)  # type: ignore[arg-type]

        print(f"Direction: {direction}")
        print(f"  Generated:  {result.generated}")
        print(f"  Confidence: {result.confidence:.3f}")
        print(f"  Regime:     {result.regime}")
        if result.generated:
            print(f"  Entry:      {result.entry_price:.2f}")
            print(f"  Stop:       {result.stop_loss:.2f}")
            print(f"  Target1:    {result.target1:.2f}")
            print(f"  Target2:    {result.target2:.2f}")
            print(f"  Indicators: {', '.join(result.confirming_indicators)}")
            print(f"  Timeframes: {', '.join(result.confirming_timeframes)}")
            print(f"  Pattern:    {result.candlestick_pattern}")
        else:
            gate_num = result.failed_at_gate
            if gate_num is not None:
                reason = result.gate_results[gate_num - 1].reason
                print(f"  Failed at Gate {gate_num}: {reason}")
        print()

    chaos_ctx = _build_mock_context(args.symbol, args.exchange, "LONG", chaos=True)
    chaos_result = engine.evaluate(chaos_ctx)  # type: ignore[arg-type]
    print("Chaos regime test: ", end="")
    if chaos_result.generated:
        print("FAIL — signal should not generate during HIGH_VOL_CHAOS!")
        all_passed = False
    else:
        print(f"PASS — blocked at Gate {chaos_result.failed_at_gate}")

    print()
    return 0 if all_passed else 1


def main() -> None:
    """CLI entry point."""
    configure_logging()

    parser = argparse.ArgumentParser(
        prog="python -m shared.signals",
        description="M11 Signal Generation Agent — replay and test",
    )
    sub = parser.add_subparsers(dest="command")

    replay_p = sub.add_parser("replay", help="Replay signal evaluation for a symbol")
    replay_p.add_argument("symbol", help="Symbol, e.g. RELIANCE.NS")
    replay_p.add_argument("--exchange", default="NSE", choices=["NSE", "ASX"])
    replay_p.add_argument("--direction", choices=["LONG", "SHORT"], default=None)
    replay_p.add_argument(
        "--chaos-only",
        action="store_true",
        help="Only test HIGH_VOL_CHAOS blocks (VERIFY scenario)",
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    sys.exit(cmd_replay(args))
