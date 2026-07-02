"""Tests for M21 HTML report generation."""

from __future__ import annotations

from datetime import date

import pytest

from shared.reporting.html_report import build_daily_html, build_monthly_html
from shared.reporting.metrics import compute_daily_report, compute_monthly_report
from shared.reporting.models import TradeRecord


def _trade(
    pnl: float = 500.0,
    pnl_pct: float = 0.5,
    tid: str = "T1",
    symbol: str = "RELIANCE",
    markout_1m: float | None = 0.3,
    markout_5m: float | None = 0.5,
) -> TradeRecord:
    return TradeRecord(
        trade_id=tid,
        symbol=symbol,
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
        slippage_pct=0.02,
        markout_1m_pct=markout_1m,
        markout_5m_pct=markout_5m,
    )


class TestBuildDailyHtml:
    def test_returns_string(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert isinstance(build_daily_html(r), str)

    def test_valid_html_document(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        h = build_daily_html(r)
        assert h.startswith("<!DOCTYPE html>")
        assert "</html>" in h

    def test_contains_date(self) -> None:
        r = compute_daily_report(date(2026, 7, 15), [_trade()], 1_000_000.0)
        assert "2026-07-15" in build_daily_html(r)

    def test_contains_symbol(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade(symbol="INFY")], 1_000_000.0)
        assert "INFY" in build_daily_html(r)

    def test_contains_sharpe_label(self) -> None:
        r = compute_daily_report(
            date(2026, 7, 1),
            [_trade(tid="A"), _trade(pnl=-100.0, tid="B")],
            1_000_000.0,
        )
        assert "Sharpe" in build_daily_html(r)

    def test_contains_sortino_label(self) -> None:
        r = compute_daily_report(
            date(2026, 7, 1),
            [_trade(tid="A"), _trade(pnl=-100.0, tid="B")],
            1_000_000.0,
        )
        assert "Sortino" in build_daily_html(r)

    def test_contains_performance_summary(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert "Performance Summary" in build_daily_html(r)

    def test_contains_trade_detail_table(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert "Trade Detail" in build_daily_html(r)

    def test_contains_markout_section(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        h = build_daily_html(r)
        assert "Markout" in h

    def test_empty_trades_no_crash(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [], 1_000_000.0)
        h = build_daily_html(r)
        assert "<!DOCTYPE html>" in h

    def test_negative_pnl_class(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade(pnl=-500.0)], 1_000_000.0)
        h = build_daily_html(r)
        assert "neg" in h

    def test_strategy_tag_present(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert "STRAT001" in build_daily_html(r)

    @pytest.mark.parametrize("symbol", ["RELIANCE", "INFY", "TCS"])
    def test_various_symbols(self, symbol: str) -> None:
        r = compute_daily_report(
            date(2026, 7, 1), [_trade(symbol=symbol)], 1_000_000.0
        )
        assert symbol in build_daily_html(r)


class TestBuildMonthlyHtml:
    def test_returns_string(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert isinstance(build_monthly_html(m), str)

    def test_valid_html_document(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        h = build_monthly_html(m)
        assert h.startswith("<!DOCTYPE html>")
        assert "</html>" in h

    def test_contains_month_name(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert "July" in build_monthly_html(m)

    def test_contains_year(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert "2026" in build_monthly_html(m)

    def test_contains_daily_breakdown(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert "Daily Breakdown" in build_monthly_html(m)

    def test_daily_date_in_table(self) -> None:
        d = compute_daily_report(date(2026, 7, 5), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert "2026-07-05" in build_monthly_html(m)

    def test_empty_reports_no_crash(self) -> None:
        m = compute_monthly_report(2026, 7, [])
        h = build_monthly_html(m)
        assert "<!DOCTYPE html>" in h

    def test_monthly_summary_present(self) -> None:
        m = compute_monthly_report(2026, 7, [])
        assert "Monthly Performance Summary" in build_monthly_html(m)
