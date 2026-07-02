"""Tests for M21 reporting data models."""

from __future__ import annotations

from datetime import date

import pytest

from shared.reporting.models import (
    DailyReport,
    MarkoutPoint,
    MonthlyReport,
    TradeRecord,
)


def _trade(**kw: object) -> TradeRecord:
    defaults: dict[str, object] = dict(
        trade_id="T1",
        symbol="RELIANCE",
        exchange="NSE",
        direction="LONG",
        entry_time_ms=1_700_000_000_000,
        exit_time_ms=1_700_003_600_000,
        entry_price=2900.0,
        exit_price=2914.5,
        quantity=100,
        pnl=500.0,
        pnl_pct=0.5,
        strategy_tag="STRAT001",
    )
    defaults.update(kw)
    return TradeRecord(**defaults)  # type: ignore[arg-type]


class TestTradeRecord:
    def test_required_fields_stored(self) -> None:
        t = _trade()
        assert t.symbol == "RELIANCE"
        assert t.direction == "LONG"
        assert t.pnl == 500.0

    def test_optional_fields_default_none(self) -> None:
        t = _trade()
        assert t.slippage_pct is None
        assert t.markout_1m_pct is None
        assert t.markout_5m_pct is None

    def test_optional_fields_set(self) -> None:
        t = _trade(slippage_pct=0.05, markout_1m_pct=0.3, markout_5m_pct=0.5)
        assert t.slippage_pct == 0.05
        assert t.markout_1m_pct == 0.3
        assert t.markout_5m_pct == 0.5

    def test_open_trade_no_exit(self) -> None:
        t = _trade(exit_time_ms=None, exit_price=None)
        assert t.exit_time_ms is None
        assert t.exit_price is None

    @pytest.mark.parametrize("direction", ["LONG", "SHORT"])
    def test_directions(self, direction: str) -> None:
        t = _trade(direction=direction)
        assert t.direction == direction


class TestMarkoutPoint:
    def test_fields_stored(self) -> None:
        pt = MarkoutPoint(offset_label="T+1m", avg_pct=0.25, sample_count=5)
        assert pt.offset_label == "T+1m"
        assert pt.avg_pct == 0.25
        assert pt.sample_count == 5


class TestDailyReport:
    def test_default_optional_fields(self) -> None:
        r = DailyReport(
            date=date(2026, 7, 1),
            trades=[],
            total_pnl=0.0,
            total_pnl_pct=0.0,
            starting_capital=1_000_000.0,
        )
        assert r.sharpe is None
        assert r.sortino is None
        assert r.max_drawdown_pct == 0.0
        assert r.win_rate_pct == 0.0
        assert r.total_trades == 0
        assert r.markout_curve == []

    def test_date_stored(self) -> None:
        r = DailyReport(
            date=date(2026, 7, 15),
            trades=[],
            total_pnl=500.0,
            total_pnl_pct=0.05,
            starting_capital=1_000_000.0,
        )
        assert r.date == date(2026, 7, 15)

    def test_trades_list_stored(self) -> None:
        t = _trade()
        r = DailyReport(
            date=date(2026, 7, 1),
            trades=[t],
            total_pnl=500.0,
            total_pnl_pct=0.05,
            starting_capital=1_000_000.0,
            total_trades=1,
        )
        assert len(r.trades) == 1
        assert r.trades[0].symbol == "RELIANCE"

    def test_markout_curve_list(self) -> None:
        pt = MarkoutPoint("T+1m", 0.3, 2)
        r = DailyReport(
            date=date(2026, 7, 1),
            trades=[],
            total_pnl=0.0,
            total_pnl_pct=0.0,
            starting_capital=1_000_000.0,
            markout_curve=[pt],
        )
        assert len(r.markout_curve) == 1


class TestMonthlyReport:
    def test_default_optional_fields(self) -> None:
        m = MonthlyReport(
            year=2026,
            month=7,
            daily_reports=[],
            total_pnl=0.0,
            total_pnl_pct=0.0,
            starting_capital=1_000_000.0,
        )
        assert m.sharpe is None
        assert m.sortino is None
        assert m.max_drawdown_pct == 0.0
        assert m.total_trades == 0

    def test_year_month_stored(self) -> None:
        m = MonthlyReport(
            year=2026,
            month=7,
            daily_reports=[],
            total_pnl=0.0,
            total_pnl_pct=0.0,
            starting_capital=1_000_000.0,
        )
        assert m.year == 2026
        assert m.month == 7
