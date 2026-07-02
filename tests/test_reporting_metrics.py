"""Tests for M21 performance metrics computation."""

from __future__ import annotations

import math
from datetime import date

from shared.reporting.metrics import (
    compute_daily_report,
    compute_max_drawdown,
    compute_monthly_report,
    compute_sharpe,
    compute_sortino,
)
from shared.reporting.models import TradeRecord


def _trade(
    pnl: float = 500.0,
    pnl_pct: float = 0.5,
    slippage_pct: float | None = 0.02,
    markout_1m: float | None = None,
    markout_5m: float | None = None,
    tid: str = "T1",
) -> TradeRecord:
    return TradeRecord(
        trade_id=tid,
        symbol="RELIANCE",
        exchange="NSE",
        direction="LONG",
        entry_time_ms=1_700_000_000_000,
        exit_time_ms=1_700_003_600_000,
        entry_price=2900.0,
        exit_price=2914.5,
        quantity=100,
        pnl=pnl,
        pnl_pct=pnl_pct,
        strategy_tag="STRAT001",
        slippage_pct=slippage_pct,
        markout_1m_pct=markout_1m,
        markout_5m_pct=markout_5m,
    )


class TestComputeSharpe:
    def test_none_for_empty(self) -> None:
        assert compute_sharpe([]) is None

    def test_none_for_single(self) -> None:
        assert compute_sharpe([0.01]) is None

    def test_none_for_zero_variance(self) -> None:
        assert compute_sharpe([0.01, 0.01, 0.01]) is None

    def test_finite_for_two_points(self) -> None:
        s = compute_sharpe([0.01, -0.005])
        assert s is not None
        assert math.isfinite(s)

    def test_positive_for_mostly_positive_returns(self) -> None:
        s = compute_sharpe([0.02, 0.01, 0.015, -0.001])
        assert s is not None and s > 0

    def test_negative_for_mostly_negative_returns(self) -> None:
        s = compute_sharpe([-0.02, -0.01, 0.001])
        assert s is not None and s < 0

    def test_annualize_false_omits_factor(self) -> None:
        s_ann = compute_sharpe([0.01, -0.005], annualize=True)
        s_raw = compute_sharpe([0.01, -0.005], annualize=False)
        assert s_ann is not None and s_raw is not None
        assert abs(s_ann / s_raw - math.sqrt(252)) < 0.001

    def test_large_series(self) -> None:
        returns = [0.005 * (1 if i % 3 else -1) for i in range(100)]
        s = compute_sharpe(returns)
        assert s is not None and math.isfinite(s)


class TestComputeSortino:
    def test_none_for_empty(self) -> None:
        assert compute_sortino([]) is None

    def test_none_for_single(self) -> None:
        assert compute_sortino([0.01]) is None

    def test_none_when_no_negative_returns(self) -> None:
        assert compute_sortino([0.01, 0.02, 0.03]) is None

    def test_finite_with_mixed_returns(self) -> None:
        s = compute_sortino([0.01, -0.005, 0.008, -0.003])
        assert s is not None and math.isfinite(s)

    def test_higher_than_sharpe_with_mostly_positive(self) -> None:
        # Need multiple negative returns so downside std > 0
        returns = [0.02, 0.01, 0.015, -0.002, 0.012, -0.001, 0.018]
        sh = compute_sharpe(returns)
        so = compute_sortino(returns)
        assert sh is not None and so is not None
        assert so > sh  # Sortino ignores upside vol → ratio is higher

    def test_annualize_false(self) -> None:
        # Need multiple negative returns so downside std > 0
        returns = [0.01, -0.005, 0.008, -0.003, 0.006]
        s_ann = compute_sortino(returns, annualize=True)
        s_raw = compute_sortino(returns, annualize=False)
        assert s_ann is not None and s_raw is not None
        assert abs(s_ann / s_raw - math.sqrt(252)) < 0.001


class TestComputeMaxDrawdown:
    def test_zero_for_empty(self) -> None:
        assert compute_max_drawdown([]) == 0.0

    def test_zero_for_all_positive(self) -> None:
        assert compute_max_drawdown([0.01, 0.02, 0.01]) == 0.0

    def test_zero_for_flat(self) -> None:
        assert compute_max_drawdown([0.0, 0.0, 0.0]) == 0.0

    def test_detects_peak_to_trough(self) -> None:
        # Wealth: 1 → 1.1 → 0.99  drawdown = (1.1 - 0.99)/1.1 ≈ 0.10
        dd = compute_max_drawdown([0.1, -0.1])
        assert 0.09 < dd < 0.11

    def test_maximum_over_multiple_drawdowns(self) -> None:
        # Two troughs: 5% and 10%; max should be 10%
        dd = compute_max_drawdown([0.05, -0.05, 0.1, -0.1])
        assert dd > 0.09

    def test_returns_fraction_not_percent(self) -> None:
        dd = compute_max_drawdown([0.1, -0.05])
        assert dd < 1.0  # fraction, not percentage


class TestComputeDailyReport:
    def test_empty_trades_all_zeros(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [], 1_000_000.0)
        assert r.total_pnl == 0.0
        assert r.total_trades == 0
        assert r.win_rate_pct == 0.0
        assert r.sharpe is None
        assert r.sortino is None

    def test_pnl_summed_correctly(self) -> None:
        trades = [_trade(pnl=300.0, tid="T1"), _trade(pnl=-100.0, tid="T2")]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        assert abs(r.total_pnl - 200.0) < 1e-9

    def test_pnl_pct_relative_to_capital(self) -> None:
        trades = [_trade(pnl=1000.0, tid="T1")]
        r = compute_daily_report(date(2026, 7, 1), trades, 100_000.0)
        assert abs(r.total_pnl_pct - 1.0) < 1e-9

    def test_zero_capital_pnl_pct_zero(self) -> None:
        trades = [_trade(pnl=100.0, tid="T1")]
        r = compute_daily_report(date(2026, 7, 1), trades, 0.0)
        assert r.total_pnl_pct == 0.0

    def test_win_lose_counts(self) -> None:
        trades = [
            _trade(pnl=100.0, tid="T1"),
            _trade(pnl=-50.0, tid="T2"),
            _trade(pnl=200.0, tid="T3"),
        ]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        assert r.winning_trades == 2
        assert r.losing_trades == 1
        assert abs(r.win_rate_pct - 200 / 3) < 0.01

    def test_avg_slippage_computed(self) -> None:
        trades = [
            _trade(slippage_pct=0.02, tid="T1"),
            _trade(slippage_pct=0.04, tid="T2"),
        ]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        assert r.avg_slippage_pct is not None
        assert abs(r.avg_slippage_pct - 0.03) < 1e-9

    def test_avg_slippage_none_when_all_none(self) -> None:
        trades = [_trade(slippage_pct=None, tid="T1")]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        assert r.avg_slippage_pct is None

    def test_markout_curve_populated(self) -> None:
        trades = [_trade(markout_1m=0.3, markout_5m=0.5, tid="T1")]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        labels = {pt.offset_label for pt in r.markout_curve}
        assert "T+1m" in labels and "T+5m" in labels

    def test_markout_curve_empty_when_none(self) -> None:
        trades = [_trade(markout_1m=None, markout_5m=None, tid="T1")]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        assert r.markout_curve == []


class TestComputeMonthlyReport:
    def _daily(self, d: date, pnl: float = 300.0) -> object:
        trades = [_trade(pnl=pnl, pnl_pct=pnl / 10000, tid="T1")]
        return compute_daily_report(d, trades, 1_000_000.0)

    def test_empty_daily_reports(self) -> None:
        m = compute_monthly_report(2026, 7, [])
        assert m.total_pnl == 0.0
        assert m.total_trades == 0
        assert m.starting_capital == 0.0

    def test_total_pnl_aggregated(self) -> None:
        d1 = compute_daily_report(
            date(2026, 7, 1), [_trade(pnl=300.0, tid="T1")], 1_000_000.0
        )
        d2 = compute_daily_report(
            date(2026, 7, 2), [_trade(pnl=-100.0, tid="T2")], 1_000_000.0
        )
        m = compute_monthly_report(2026, 7, [d1, d2])
        assert abs(m.total_pnl - 200.0) < 1e-9

    def test_total_trades_aggregated(self) -> None:
        d1 = compute_daily_report(
            date(2026, 7, 1),
            [_trade(tid="A"), _trade(tid="B")],
            1_000_000.0,
        )
        m = compute_monthly_report(2026, 7, [d1])
        assert m.total_trades == 2

    def test_win_rate_based_on_days(self) -> None:
        d_win = compute_daily_report(
            date(2026, 7, 1), [_trade(pnl=100.0, tid="W")], 1_000_000.0
        )
        d_loss = compute_daily_report(
            date(2026, 7, 2), [_trade(pnl=-50.0, tid="L")], 1_000_000.0
        )
        m = compute_monthly_report(2026, 7, [d_win, d_loss])
        assert abs(m.win_rate_pct - 50.0) < 1e-9

    def test_sharpe_none_for_single_day(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade(tid="T")], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert m.sharpe is None

    def test_year_and_month_stored(self) -> None:
        m = compute_monthly_report(2026, 7, [])
        assert m.year == 2026
        assert m.month == 7
