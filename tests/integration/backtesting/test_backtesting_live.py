"""M07 VERIFY integration test — EMA crossover backtest on synthetic RELIANCE/NSE data.

Requires a live TimescaleDB instance (same as conftest.py pg_connection fixture).
Verifies:
  - Slippage is non-zero (RULE 6 — log-normal slippage, NOT mid-price fills)
  - Report files are generated (HTML + CSV)
  - All metric fields are floats
  - PostgreSQL round-trip via save_result / load_result
  - Promotion gate is evaluated (passed_promotion_gate is a bool)
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.backtesting.engine import (
    default_config,
    ema_crossover_signals,
    run_backtest,
)
from shared.backtesting.models import BacktestMetrics, BacktestResult
from shared.backtesting.report import generate_reports
from shared.backtesting.repository import load_result, save_result
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

_SYMBOL = "RELIANCE"
_EXCHANGE = "NSE"
_T0 = datetime(2024, 1, 2, 9, 15, tzinfo=timezone.utc)
_N_CANDLES = 252  # ~1 trading year of daily bars


def _make_candles(n: int = _N_CANDLES) -> list[OHLCVCandle]:
    """Synthesize daily RELIANCE/NSE candles with a strong uptrend."""
    candles = []
    base = 2500.0
    for i in range(n):
        close = base + i * 5.0  # 5 rupees per day — strongly trending
        candles.append(
            OHLCVCandle(
                time=_T0 + timedelta(days=i),
                symbol=_SYMBOL,
                exchange=_EXCHANGE,
                open=close * 0.999,
                high=close * 1.002,
                low=close * 0.997,
                close=close,
                volume=500_000,
            )
        )
    return candles


@pytest.fixture()
def inserted_candles(pg_connection: PGConnection) -> list[OHLCVCandle]:
    """Insert synthetic candles into ohlcv_1m, return the list for downstream use."""
    candles = _make_candles()
    repo = OHLCVRepository(pg_connection)
    repo.upsert_1m(candles)
    return candles


@pytest.fixture()
def queried_candles(
    pg_connection: PGConnection, inserted_candles: list[OHLCVCandle]
) -> list[OHLCVCandle]:
    """Query back the inserted candles via OHLCVRepository."""
    repo = OHLCVRepository(pg_connection)
    start = _T0
    end = _T0 + timedelta(days=_N_CANDLES + 1)
    return repo.query_candles(_SYMBOL, _EXCHANGE, "1m", start, end)


class TestBacktestingVerify:
    """VERIFY: EMA crossover on RELIANCE.NS 1yr with non-zero slippage metrics."""

    def test_candles_inserted_and_queried(
        self, queried_candles: list[OHLCVCandle]
    ) -> None:
        assert len(queried_candles) == _N_CANDLES
        assert queried_candles[0].symbol == _SYMBOL
        assert queried_candles[0].exchange == _EXCHANGE

    def test_ema_crossover_generates_trades(
        self, queried_candles: list[OHLCVCandle]
    ) -> None:
        entries, exits = ema_crossover_signals(queried_candles)
        assert len(entries) == _N_CANDLES
        assert any(
            entries
        ), "Strongly-trending series must produce at least one EMA entry signal"

    def test_backtest_runs_end_to_end(self, queried_candles: list[OHLCVCandle]) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(
            config, queried_candles, entries, exits, spread_bps=5.0, slippage_rng=rng
        )
        assert isinstance(result, BacktestResult)
        assert result.metrics.total_trades > 0

    def test_slippage_is_nonzero(self, queried_candles: list[OHLCVCandle]) -> None:
        """Core RULE 6 verify: slippage must be non-zero (log-normal, not mid-price)."""
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(
            config, queried_candles, entries, exits, spread_bps=5.0, slippage_rng=rng
        )
        assert result.metrics.avg_slippage_bps > 0.0, (
            f"avg_slippage_bps must be > 0; got {result.metrics.avg_slippage_bps}. "
            "Ensure log-normal slippage is injected (not mid-price fills)."
        )

    def test_all_metrics_are_floats(self, queried_candles: list[OHLCVCandle]) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        m = result.metrics
        assert isinstance(m, BacktestMetrics)
        float_fields = [
            m.sharpe_ratio,
            m.sortino_ratio,
            m.max_drawdown_pct,
            m.win_rate_pct,
            m.expectancy_per_trade,
            m.profit_factor,
            m.calmar_ratio,
            m.avg_slippage_bps,
            m.total_return_pct,
            m.annualized_return_pct,
        ]
        for val in float_fields:
            assert isinstance(val, float), f"Expected float, got {type(val)}: {val}"

    def test_reports_generated(
        self, queried_candles: list[OHLCVCandle], tmp_path: pytest.TempPathFactory
    ) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        report_dir = str(tmp_path)
        result_with_reports = generate_reports(result, report_dir)
        assert result_with_reports.report_html_path is not None
        assert result_with_reports.report_csv_path is not None
        import os

        assert os.path.isfile(result_with_reports.report_html_path)
        assert os.path.isfile(result_with_reports.report_csv_path)

    def test_html_report_contains_strategy_and_symbol(
        self, queried_candles: list[OHLCVCandle], tmp_path: pytest.TempPathFactory
    ) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        result_with_reports = generate_reports(result, str(tmp_path))
        assert result_with_reports.report_html_path is not None
        html_content = open(result_with_reports.report_html_path).read()
        assert _SYMBOL in html_content
        assert _EXCHANGE in html_content

    def test_promotion_gate_evaluated(self, queried_candles: list[OHLCVCandle]) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        assert isinstance(result.passed_promotion_gate, bool)
        assert isinstance(result.promotion_failures, list)
        # Failures list must be consistent with pass/fail flag
        if result.passed_promotion_gate:
            assert result.promotion_failures == []
        else:
            assert len(result.promotion_failures) > 0

    def test_postgresql_round_trip(
        self,
        pg_connection: PGConnection,
        queried_candles: list[OHLCVCandle],
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        result = generate_reports(result, str(tmp_path))

        save_result(result, pg_connection)

        loaded = load_result(result.run_id, pg_connection)
        assert loaded is not None
        assert loaded["run_id"] == result.run_id
        assert loaded["symbol"] == _SYMBOL
        assert loaded["exchange"] == _EXCHANGE
        assert loaded["total_trades"] == result.metrics.total_trades
        assert isinstance(loaded["sharpe_ratio"], float)
        assert isinstance(loaded["passed_promotion_gate"], bool)

    def test_markout_curves_present(self, queried_candles: list[OHLCVCandle]) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        # markout_curves list may be empty if no trades, but must be a list
        assert isinstance(result.markout_curves, list)
        if result.metrics.total_trades > 0:
            assert len(result.markout_curves) >= 1
            first = result.markout_curves[0]
            assert isinstance(first.avg_return_pct, float)
            assert isinstance(first.sample_count, int)

    def test_equity_curve_starts_at_initial_capital(
        self, queried_candles: list[OHLCVCandle]
    ) -> None:
        config = default_config(symbol=_SYMBOL, exchange=_EXCHANGE)
        entries, exits = ema_crossover_signals(queried_candles)
        rng = np.random.default_rng(42)
        result = run_backtest(config, queried_candles, entries, exits, slippage_rng=rng)
        assert len(result.equity_curve) > 0
        _, first_val = result.equity_curve[0]
        assert first_val == pytest.approx(config.initial_capital, rel=0.01)
