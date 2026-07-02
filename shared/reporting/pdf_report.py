"""M21 Reporting Module — PDF report generation using fpdf2."""

from __future__ import annotations

import calendar

from fpdf import FPDF

from shared.reporting.models import DailyReport, MonthlyReport

_HEADER_RGB = (41, 128, 185)
_ROW_ALT_RGB = (235, 245, 251)


def _table_header(pdf: FPDF, cols: list[tuple[str, int]]) -> None:
    """Render a shaded table header row."""
    pdf.set_fill_color(*_HEADER_RGB)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 9)
    for label, width in cols:
        pdf.cell(width, 7, label, border=1, fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("helvetica", size=9)


def _section_title(pdf: FPDF, title: str) -> None:
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)


def _metric_row(pdf: FPDF, label: str, value: str, shade: bool = False) -> None:
    if shade:
        pdf.set_fill_color(*_ROW_ALT_RGB)
    pdf.cell(60, 7, label, border=1, fill=shade)
    pdf.cell(60, 7, value, border=1, fill=shade)
    pdf.ln()
    if shade:
        pdf.set_fill_color(255, 255, 255)


def _fmt_float(v: float | None, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}" if v is not None else "N/A"


def build_daily_pdf(report: DailyReport) -> bytes:
    """Generate a daily trade report as a PDF document.

    Args:
        report: Fully-populated DailyReport from ``compute_daily_report``.

    Returns:
        Raw PDF bytes ready for file storage or email attachment.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Title
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(
        0,
        10,
        f"Daily Trading Report - {report.date.strftime('%Y-%m-%d')}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    # Performance Summary
    _section_title(pdf, "Performance Summary")
    metrics = [
        ("Starting Capital", f"${report.starting_capital:,.2f}"),
        ("Total P&L", f"${report.total_pnl:+,.2f}"),
        ("P&L %", f"{report.total_pnl_pct:+.2f}%"),
        ("Total Trades", str(report.total_trades)),
        ("Win Rate", f"{report.win_rate_pct:.1f}%"),
        ("Winning / Losing", f"{report.winning_trades} / {report.losing_trades}"),
        ("Sharpe (intraday)", _fmt_float(report.sharpe)),
        ("Sortino (intraday)", _fmt_float(report.sortino)),
        ("Max Drawdown", f"{report.max_drawdown_pct:.2f}%"),
        ("Avg Slippage", _fmt_float(report.avg_slippage_pct) + "%"),
    ]
    for i, (label, value) in enumerate(metrics):
        _metric_row(pdf, label, value, shade=(i % 2 == 0))
    pdf.ln(4)

    # Markout curve
    if report.markout_curve:
        _section_title(pdf, "Markout Curve (Adverse Selection Monitor)")
        _table_header(pdf, [("Offset", 40), ("Avg P&L %", 40), ("Samples", 30)])
        for i, pt in enumerate(report.markout_curve):
            shade = i % 2 == 0
            if shade:
                pdf.set_fill_color(*_ROW_ALT_RGB)
            pdf.cell(40, 7, pt.offset_label, border=1, fill=shade)
            pdf.cell(40, 7, f"{pt.avg_pct:+.3f}%", border=1, fill=shade)
            pdf.cell(30, 7, str(pt.sample_count), border=1, fill=shade)
            pdf.ln()
        pdf.ln(4)

    # Trade-by-trade table
    _section_title(pdf, "Trade Detail")
    cols = [
        ("Symbol", 28),
        ("Dir", 14),
        ("Qty", 14),
        ("Entry", 22),
        ("Exit", 22),
        ("P&L", 22),
        ("P&L%", 18),
        ("Slip%", 18),
        ("Strategy", 24),
    ]
    _table_header(pdf, cols)
    for i, t in enumerate(report.trades):
        shade = i % 2 == 0
        if shade:
            pdf.set_fill_color(*_ROW_ALT_RGB)
        pdf.cell(28, 7, t.symbol[:12], border=1, fill=shade)
        pdf.cell(14, 7, t.direction[:1], border=1, fill=shade)
        pdf.cell(14, 7, str(t.quantity), border=1, fill=shade)
        pdf.cell(22, 7, f"{t.entry_price:.2f}", border=1, fill=shade)
        ep = f"{t.exit_price:.2f}" if t.exit_price is not None else "-"
        pdf.cell(22, 7, ep, border=1, fill=shade)
        pdf.cell(22, 7, f"{t.pnl:+.1f}", border=1, fill=shade)
        pdf.cell(18, 7, f"{t.pnl_pct:+.2f}%", border=1, fill=shade)
        slip = _fmt_float(t.slippage_pct, 3) + "%"
        pdf.cell(18, 7, slip, border=1, fill=shade)
        pdf.cell(24, 7, t.strategy_tag[:10], border=1, fill=shade)
        pdf.ln()

    return bytes(pdf.output())


def build_monthly_pdf(report: MonthlyReport) -> bytes:
    """Generate a monthly performance report as a PDF document.

    Args:
        report: Fully-populated MonthlyReport from ``compute_monthly_report``.

    Returns:
        Raw PDF bytes.
    """
    month_name = calendar.month_name[report.month]
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Title
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(
        0,
        10,
        f"Monthly Trading Report - {month_name} {report.year}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    # Monthly Summary
    _section_title(pdf, "Monthly Performance Summary")
    metrics = [
        ("Starting Capital", f"${report.starting_capital:,.2f}"),
        ("Total P&L", f"${report.total_pnl:+,.2f}"),
        ("Monthly Return", f"{report.total_pnl_pct:+.2f}%"),
        ("Total Trades", str(report.total_trades)),
        ("Win Rate (days)", f"{report.win_rate_pct:.1f}%"),
        ("Sharpe (monthly)", _fmt_float(report.sharpe)),
        ("Sortino (monthly)", _fmt_float(report.sortino)),
        ("Max Drawdown", f"{report.max_drawdown_pct:.2f}%"),
        ("Trading Days", str(len(report.daily_reports))),
    ]
    for i, (label, value) in enumerate(metrics):
        _metric_row(pdf, label, value, shade=(i % 2 == 0))
    pdf.ln(4)

    # Daily breakdown
    _section_title(pdf, "Daily Breakdown")
    cols = [
        ("Date", 30),
        ("Trades", 20),
        ("P&L", 30),
        ("P&L %", 24),
        ("Win Rate", 24),
        ("Sharpe", 24),
        ("Drawdown", 28),
    ]
    _table_header(pdf, cols)
    for i, day in enumerate(report.daily_reports):
        shade = i % 2 == 0
        if shade:
            pdf.set_fill_color(*_ROW_ALT_RGB)
        pdf.cell(30, 7, day.date.strftime("%Y-%m-%d"), border=1, fill=shade)
        pdf.cell(20, 7, str(day.total_trades), border=1, fill=shade)
        pdf.cell(30, 7, f"${day.total_pnl:+,.1f}", border=1, fill=shade)
        pdf.cell(24, 7, f"{day.total_pnl_pct:+.2f}%", border=1, fill=shade)
        pdf.cell(24, 7, f"{day.win_rate_pct:.0f}%", border=1, fill=shade)
        pdf.cell(24, 7, _fmt_float(day.sharpe), border=1, fill=shade)
        pdf.cell(28, 7, f"{day.max_drawdown_pct:.2f}%", border=1, fill=shade)
        pdf.ln()

    return bytes(pdf.output())
