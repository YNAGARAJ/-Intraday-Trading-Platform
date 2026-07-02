"""Tests for M21 PDF report generation."""

from __future__ import annotations

from datetime import date

from shared.reporting.metrics import compute_daily_report, compute_monthly_report
from shared.reporting.models import TradeRecord
from shared.reporting.pdf_report import build_daily_pdf, build_monthly_pdf


def _trade(pnl: float = 500.0, tid: str = "T1") -> TradeRecord:
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
        pnl_pct=pnl / 290_000 * 100,
        strategy_tag="STRAT001",
        slippage_pct=0.02,
        markout_1m_pct=0.3,
        markout_5m_pct=0.5,
    )


class TestBuildDailyPdf:
    def test_returns_bytes(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert isinstance(build_daily_pdf(r), bytes)

    def test_pdf_header_signature(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert build_daily_pdf(r)[:5] == b"%PDF-"

    def test_non_empty_output(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert len(build_daily_pdf(r)) > 500

    def test_zero_trades_no_crash(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [], 1_000_000.0)
        data = build_daily_pdf(r)
        assert data[:5] == b"%PDF-"

    def test_multiple_trades(self) -> None:
        trades = [_trade(pnl=100.0 * i, tid=f"T{i}") for i in range(1, 6)]
        r = compute_daily_report(date(2026, 7, 1), trades, 1_000_000.0)
        assert build_daily_pdf(r)[:5] == b"%PDF-"

    def test_markout_curve_included(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        assert len(r.markout_curve) > 0
        data = build_daily_pdf(r)
        assert len(data) > 0

    def test_negative_pnl_no_crash(self) -> None:
        r = compute_daily_report(date(2026, 7, 1), [_trade(pnl=-500.0)], 1_000_000.0)
        assert build_daily_pdf(r)[:5] == b"%PDF-"


class TestBuildMonthlyPdf:
    def test_returns_bytes(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert isinstance(build_monthly_pdf(m), bytes)

    def test_pdf_header_signature(self) -> None:
        d = compute_daily_report(date(2026, 7, 1), [_trade()], 1_000_000.0)
        m = compute_monthly_report(2026, 7, [d])
        assert build_monthly_pdf(m)[:5] == b"%PDF-"

    def test_empty_daily_reports(self) -> None:
        m = compute_monthly_report(2026, 7, [])
        data = build_monthly_pdf(m)
        assert data[:5] == b"%PDF-"

    def test_multiple_days(self) -> None:
        days = [
            compute_daily_report(
                date(2026, 7, i), [_trade(pnl=100.0 * i, tid=f"T{i}")], 1_000_000.0
            )
            for i in range(1, 6)
        ]
        m = compute_monthly_report(2026, 7, days)
        assert build_monthly_pdf(m)[:5] == b"%PDF-"
