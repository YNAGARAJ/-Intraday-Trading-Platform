"""CLI for M12 Risk & Position Sizing Engine.

Runs a VERIFY scenario: demonstrates all risk guards with synthetic data.
Tests 3-5-7 rule, correlation guard, circuit breaker, and snapshot-window halving.

Usage:
    python -m shared.risk --help
    python -m shared.risk verify
    python -m shared.risk verify --scenario all
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

import structlog

from shared.core.logging import configure_logging

logger = structlog.get_logger(__name__)


def _make_regime(
    regime_name: str = "BULL_TREND",
) -> object:
    """Build a minimal ``RegimeClassification`` for CLI scenarios."""
    from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures

    mapping = {
        "BULL_TREND": MarketRegime.BULL_TREND,
        "BEAR_TREND": MarketRegime.BEAR_TREND,
        "MEAN_REVERTING": MarketRegime.MEAN_REVERTING,
        "HIGH_VOL_CHAOS": MarketRegime.HIGH_VOL_CHAOS,
    }
    regime_val = mapping.get(regime_name, MarketRegime.BULL_TREND)
    features = RegimeFeatures(
        adx=30.0,
        rsi=60.0,
        bb_width_pct=2.0,
        atr_pct=1.0,
        vwap_deviation_pct=0.2,
        volume_ratio=1.5,
        vix=14.0,
        atr_spike=False,
    )
    return RegimeClassification(
        regime=regime_val,
        confidence=0.85,
        features=features,
        hmm_state=0,
        classified_at=datetime.now(UTC),
    )


def _print_decision(label: str, decision: object) -> None:
    """Print a RiskDecision summary to stdout."""
    from shared.risk.models import RiskDecision

    d: RiskDecision = decision  # type: ignore[assignment]
    print(f"\n--- {label} ---")
    print(f"  Approved: {d.approved}")
    if d.approved and d.position_size is not None:
        ps = d.position_size
        print(f"  Quantity:  {ps.quantity}")
        print(f"  Notional:  {ps.notional_value:.2f}")
        print(f"  Risk:      {ps.risk_pct:.3f}%")
        print(f"  Method:    {ps.sizing_method}")
        print(f"  Regime ×:  {ps.regime_multiplier:.2f}")
        print(f"  Snapshot ×:{ps.snapshot_multiplier:.2f}")
    else:
        print(f"  Rejected:  {d.rejection_reason}")
    for chk in d.checks:
        status = "PASS" if chk.passed else "FAIL"
        print(f"  [{status}] {chk.name}: {chk.detail}")


def _scenario_normal(capital: float = 100_000.0) -> object:
    """Normal approved trade scenario."""
    from shared.risk.engine import RiskEngine
    from shared.risk.models import RiskParameters

    engine = RiskEngine()
    params = RiskParameters(
        capital=capital,
        open_positions=[],
        daily_pnl=0.0,
        daily_trade_count=2,
        is_snapshot_window=False,
        regime=_make_regime("BULL_TREND"),  # type: ignore[arg-type]
    )
    return engine.evaluate(
        entry_price=2450.0,
        stop_loss=2413.0,
        params=params,
    )


def _scenario_circuit_breaker(capital: float = 100_000.0) -> object:
    """Circuit breaker triggered (-2.1% daily P&L)."""
    from shared.risk.engine import RiskEngine
    from shared.risk.models import RiskParameters

    engine = RiskEngine()
    params = RiskParameters(
        capital=capital,
        open_positions=[],
        daily_pnl=-2_100.0,
        daily_trade_count=3,
        is_snapshot_window=False,
        regime=_make_regime("BULL_TREND"),  # type: ignore[arg-type]
    )
    return engine.evaluate(
        entry_price=2450.0,
        stop_loss=2413.0,
        params=params,
    )


def _scenario_halted(capital: float = 100_000.0) -> object:
    """System already halted via Redis kill-switch flag."""
    from shared.risk.engine import RiskEngine
    from shared.risk.models import RiskParameters

    engine = RiskEngine()
    params = RiskParameters(
        capital=capital,
        open_positions=[],
        daily_pnl=500.0,
        daily_trade_count=1,
        is_snapshot_window=False,
        regime=_make_regime("BULL_TREND"),  # type: ignore[arg-type]
        halted=True,
    )
    return engine.evaluate(
        entry_price=2450.0,
        stop_loss=2413.0,
        params=params,
    )


def _scenario_portfolio_heat(capital: float = 100_000.0) -> object:
    """Portfolio heat at 7% — new trade blocked."""
    from shared.risk.engine import RiskEngine
    from shared.risk.models import OpenPosition, RiskParameters

    engine = RiskEngine()
    existing = [
        OpenPosition(
            symbol=f"STOCK{i}",
            exchange="NSE",
            direction="LONG",
            quantity=100,
            entry_price=500.0,
            stop_loss=485.0,
            sector="IT",
            risk_amount=1_500.0,  # sum = 7 × 1000 = 7,000 = 7% of 100k
        )
        for i in range(5)
    ]
    params = RiskParameters(
        capital=capital,
        open_positions=existing,
        daily_pnl=0.0,
        daily_trade_count=5,
        is_snapshot_window=False,
        regime=_make_regime("BULL_TREND"),  # type: ignore[arg-type]
        proposed_sector="IT",
    )
    return engine.evaluate(
        entry_price=2450.0,
        stop_loss=2413.0,
        params=params,
    )


def _scenario_snapshot_window(capital: float = 100_000.0) -> object:
    """Snapshot window: position size halved."""
    from shared.risk.engine import RiskEngine
    from shared.risk.models import RiskParameters

    engine = RiskEngine()
    params = RiskParameters(
        capital=capital,
        open_positions=[],
        daily_pnl=0.0,
        daily_trade_count=2,
        is_snapshot_window=True,
        regime=_make_regime("BULL_TREND"),  # type: ignore[arg-type]
    )
    return engine.evaluate(
        entry_price=2450.0,
        stop_loss=2413.0,
        params=params,
    )


def _scenario_correlation(capital: float = 100_000.0) -> object:
    """Correlation guard: new position too correlated with open position."""
    from shared.risk.engine import RiskEngine
    from shared.risk.models import OpenPosition, RiskParameters

    returns = [0.01, -0.005, 0.008, -0.003, 0.012, 0.006, -0.002, 0.009] * 3
    existing = OpenPosition(
        symbol="RELIANCE",
        exchange="NSE",
        direction="LONG",
        quantity=100,
        entry_price=2400.0,
        stop_loss=2364.0,
        sector="ENERGY",
        risk_amount=3_600.0,
        returns=returns,
    )
    engine = RiskEngine()
    params = RiskParameters(
        capital=capital,
        open_positions=[existing],
        daily_pnl=0.0,
        daily_trade_count=1,
        is_snapshot_window=False,
        regime=_make_regime("BULL_TREND"),  # type: ignore[arg-type]
        proposed_sector="ENERGY",
        proposed_returns=returns,  # perfectly correlated
    )
    return engine.evaluate(
        entry_price=2450.0,
        stop_loss=2413.0,
        params=params,
    )


def cmd_verify(args: argparse.Namespace) -> int:
    """Run VERIFY scenario(s) and print results."""
    scenario = getattr(args, "scenario", "all")
    capital = 100_000.0

    scenarios: dict[str, object] = {}
    if scenario in ("all", "normal"):
        scenarios["Normal approved trade"] = _scenario_normal(capital)
    if scenario in ("all", "circuit_breaker"):
        scenarios["Circuit breaker (-2.1% P&L)"] = _scenario_circuit_breaker(capital)
    if scenario in ("all", "halted"):
        scenarios["System halted flag"] = _scenario_halted(capital)
    if scenario in ("all", "heat"):
        scenarios["Portfolio heat (7% filled)"] = _scenario_portfolio_heat(capital)
    if scenario in ("all", "snapshot"):
        scenarios["Snapshot window (0.5× size)"] = _scenario_snapshot_window(capital)
    if scenario in ("all", "correlation"):
        scenarios["Correlation guard (>0.7)"] = _scenario_correlation(capital)

    print("\n=== M12 Risk & Position Sizing Engine — VERIFY ===")
    print(f"Capital: {capital:,.0f}")

    all_passed = True
    from shared.risk.models import RiskDecision

    expected_approved = {
        "Normal approved trade": True,
        "Circuit breaker (-2.1% P&L)": False,
        "System halted flag": False,
        "Portfolio heat (7% filled)": False,
        "Snapshot window (0.5× size)": True,
        "Correlation guard (>0.7)": False,
    }

    for label, decision in scenarios.items():
        _print_decision(label, decision)
        d: RiskDecision = decision  # type: ignore[assignment]
        expected = expected_approved.get(label)
        if expected is not None and d.approved != expected:
            print(f"  VERIFY FAIL: expected approved={expected}, got {d.approved}")
            all_passed = False

    print(f"\n{'VERIFY PASS' if all_passed else 'VERIFY FAIL'}: all scenarios ran.")
    return 0 if all_passed else 1


def main() -> None:
    """CLI entry point."""
    configure_logging()

    parser = argparse.ArgumentParser(
        prog="python -m shared.risk",
        description="M12 Risk & Position Sizing Engine — VERIFY and scenario runner",
    )
    sub = parser.add_subparsers(dest="command")

    verify_p = sub.add_parser("verify", help="Run VERIFY scenario(s)")
    verify_p.add_argument(
        "--scenario",
        choices=[
            "all", "normal", "circuit_breaker", "halted",
            "heat", "snapshot", "correlation",
        ],
        default="all",
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    sys.exit(cmd_verify(args))
