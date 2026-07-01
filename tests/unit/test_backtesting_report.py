"""Unit tests for shared.backtesting.report — HTML + CSV generation."""

import csv
import os
import tempfile
from datetime import date, datetime, timezone

from shared.backtesting.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    MarkoutPoint,
    Trade,
)
from shared.backtesting.report import generate_reports

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
_T1 = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)


def _metrics(passed: bool = True) -> BacktestMetrics:
    return BacktestMetrics(
        sharpe_ratio=2.1,
        sortino_ratio=2.8,
        max_drawdown_pct=2.5,
        win_rate_pct=60.0,
        expectancy_per_trade=0.8,
        profit_factor=2.1,
        calmar_ratio=3.0,
        avg_slippage_bps=9.0,
        total_trades=15,
        trading_days=22,
        total_return_pct=18.5,
        annualized_return_pct=22.0,
    )


def _trade(idx: int = 0, pnl_pct: float = 1.5) -> Trade:
    return Trade(
        trade_id=str(idx),
        symbol="RELIANCE",
        exchange="NSE",
        strategy_id="EMA9X21",
        direction=1,
        entry_time=_T0,
        exit_time=_T1,
        entry_price=2500.0,
        exit_price=2537.5,
        entry_slippage_bps=7.2,
        exit_slippage_bps=5.8,
        quantity=10.0,
        pnl=375.0,
        pnl_pct=pnl_pct,
    )


def _result(trades: list[Trade] | None = None, passed: bool = True) -> BacktestResult:
    return BacktestResult(
        run_id="abc12345",
        config=BacktestConfig(
            strategy_id="EMA9X21",
            symbol="RELIANCE",
            exchange="NSE",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
        ),
        trades=[_trade()] if trades is None else trades,
        metrics=_metrics(passed),
        markout_curves=[
            MarkoutPoint("T+1m", 0.12, 0.08, 0.65, 15),
            MarkoutPoint("T+5m", 0.25, 0.18, 0.67, 15),
        ],
        equity_curve=[(_T0, 100_000.0), (_T1, 101_500.0)],
        passed_promotion_gate=passed,
        promotion_failures=[] if passed else ["sharpe_ratio > 1.5"],
        report_html_path=None,
        report_csv_path=None,
        completed_at=_T0,
    )


class TestGenerateReports:
    def test_creates_html_and_csv_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(), d)
            assert result.report_html_path is not None
            assert result.report_csv_path is not None
            assert os.path.isfile(result.report_html_path)
            assert os.path.isfile(result.report_csv_path)

    def test_html_contains_strategy_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(), d)
            assert result.report_html_path is not None
            content = open(result.report_html_path).read()
            assert "EMA9X21" in content

    def test_html_contains_passed_gate_label(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(passed=True), d)
            assert result.report_html_path is not None
            content = open(result.report_html_path).read()
            assert "PASSED" in content

    def test_html_contains_failed_gate_label(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(passed=False), d)
            assert result.report_html_path is not None
            content = open(result.report_html_path).read()
            assert "FAILED" in content

    def test_csv_has_header_and_trade_rows(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(trades=[_trade(0), _trade(1)]), d)
            assert result.report_csv_path is not None
            with open(result.report_csv_path, newline="") as f:
                rows = list(csv.reader(f))
            assert len(rows) == 3  # header + 2 trades
            assert rows[0][0] == "trade_id"

    def test_csv_empty_trades(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(trades=[]), d)
            assert result.report_csv_path is not None
            with open(result.report_csv_path, newline="") as f:
                rows = list(csv.reader(f))
            assert len(rows) == 1  # header only

    def test_report_dir_created_if_absent(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            new_dir = os.path.join(base, "sub", "reports")
            result = generate_reports(_result(), new_dir)
            assert result.report_html_path is not None
            assert os.path.isfile(result.report_html_path)

    def test_filename_contains_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = generate_reports(_result(), d)
            assert result.report_html_path is not None
            assert "abc12345" in result.report_html_path
            assert result.report_csv_path is not None
            assert "abc12345" in result.report_csv_path
