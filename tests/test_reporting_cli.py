"""Tests for M21 reporting CLI (20 VERIFY scenarios)."""

from __future__ import annotations

from shared.reporting.cli import (
    _s01_trade_record_fields,
    _s02_daily_report_empty_trades,
    _s03_daily_report_pnl_sum,
    _s04_win_rate_calculation,
    _s05_sharpe_two_data_points,
    _s06_sharpe_none_for_single_return,
    _s07_sharpe_none_for_zero_variance,
    _s08_sortino_none_for_no_losses,
    _s09_sortino_finite_with_losses,
    _s10_max_drawdown_zero_on_all_gains,
    _s11_max_drawdown_computed_correctly,
    _s12_monthly_report_aggregation,
    _s13_pdf_daily_returns_bytes,
    _s14_pdf_monthly_returns_bytes,
    _s15_html_daily_contains_metrics,
    _s16_html_daily_valid_document,
    _s17_html_monthly_contains_daily_breakdown,
    _s18_csv_export_header_and_rows,
    _s19_excel_export_sheets,
    _s20_markout_curve_in_daily_report,
    run_verify,
)


class TestVerifyScenarios:
    def test_s01_trade_record_fields(self) -> None:
        assert _s01_trade_record_fields()

    def test_s02_daily_report_empty_trades(self) -> None:
        assert _s02_daily_report_empty_trades()

    def test_s03_daily_report_pnl_sum(self) -> None:
        assert _s03_daily_report_pnl_sum()

    def test_s04_win_rate_calculation(self) -> None:
        assert _s04_win_rate_calculation()

    def test_s05_sharpe_two_data_points(self) -> None:
        assert _s05_sharpe_two_data_points()

    def test_s06_sharpe_none_for_single_return(self) -> None:
        assert _s06_sharpe_none_for_single_return()

    def test_s07_sharpe_none_for_zero_variance(self) -> None:
        assert _s07_sharpe_none_for_zero_variance()

    def test_s08_sortino_none_for_no_losses(self) -> None:
        assert _s08_sortino_none_for_no_losses()

    def test_s09_sortino_finite_with_losses(self) -> None:
        assert _s09_sortino_finite_with_losses()

    def test_s10_max_drawdown_zero_on_all_gains(self) -> None:
        assert _s10_max_drawdown_zero_on_all_gains()

    def test_s11_max_drawdown_computed_correctly(self) -> None:
        assert _s11_max_drawdown_computed_correctly()

    def test_s12_monthly_report_aggregation(self) -> None:
        assert _s12_monthly_report_aggregation()

    def test_s13_pdf_daily_returns_bytes(self) -> None:
        assert _s13_pdf_daily_returns_bytes()

    def test_s14_pdf_monthly_returns_bytes(self) -> None:
        assert _s14_pdf_monthly_returns_bytes()

    def test_s15_html_daily_contains_metrics(self) -> None:
        assert _s15_html_daily_contains_metrics()

    def test_s16_html_daily_valid_document(self) -> None:
        assert _s16_html_daily_valid_document()

    def test_s17_html_monthly_contains_daily_breakdown(self) -> None:
        assert _s17_html_monthly_contains_daily_breakdown()

    def test_s18_csv_export_header_and_rows(self) -> None:
        assert _s18_csv_export_header_and_rows()

    def test_s19_excel_export_sheets(self) -> None:
        assert _s19_excel_export_sheets()

    def test_s20_markout_curve_in_daily_report(self) -> None:
        assert _s20_markout_curve_in_daily_report()

    def test_run_verify_all_pass(self) -> None:
        assert run_verify() is True
