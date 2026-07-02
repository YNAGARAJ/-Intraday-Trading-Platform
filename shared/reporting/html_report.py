"""M21 Reporting Module — HTML report generation (f-string templates, no Jinja2)."""

from __future__ import annotations

import calendar
import html

from shared.reporting.models import DailyReport, MonthlyReport

_CSS = """
body{font-family:Arial,sans-serif;font-size:13px;color:#222;margin:20px}
h1{color:#1a5276}h2{color:#2471a3;margin-top:24px;margin-bottom:4px}
table{border-collapse:collapse;width:100%;margin-bottom:16px}
th{background:#2980b9;color:#fff;padding:6px 8px;text-align:left}
td{padding:5px 8px;border-bottom:1px solid #d6eaf8}
tr:nth-child(even){background:#eaf4fb}
.pos{color:#1e8449}.neg{color:#c0392b}.metric-val{font-weight:bold}
"""


def _e(v: object) -> str:
    """HTML-escape a value."""
    return html.escape(str(v))


def _fmt(v: float | None, decimals: int = 2, suffix: str = "") -> str:
    return f"{v:.{decimals}f}{suffix}" if v is not None else "N/A"


def _pnl_class(pnl: float) -> str:
    return "pos" if pnl >= 0 else "neg"


def _summary_table(rows: list[tuple[str, str]]) -> str:
    trs = "".join(
        f"<tr><td>{_e(k)}</td><td class='metric-val'>{_e(v)}</td></tr>"
        for k, v in rows
    )
    return f"<table><tr><th>Metric</th><th>Value</th></tr>{trs}</table>"


def build_daily_html(report: DailyReport) -> str:
    """Generate a daily trade report as an HTML document.

    Args:
        report: Fully-populated DailyReport from ``compute_daily_report``.

    Returns:
        UTF-8 HTML string ready for browser display or email embedding.
    """
    date_str = report.date.strftime("%Y-%m-%d")
    pnl_cls = _pnl_class(report.total_pnl)

    # Performance summary
    summary_rows: list[tuple[str, str]] = [
        ("Starting Capital", f"${report.starting_capital:,.2f}"),
        ("Total P&L", f"${report.total_pnl:+,.2f}"),
        ("P&L %", f"{report.total_pnl_pct:+.2f}%"),
        ("Total Trades", str(report.total_trades)),
        ("Win Rate", f"{report.win_rate_pct:.1f}%"),
        ("Winning / Losing", f"{report.winning_trades} / {report.losing_trades}"),
        ("Sharpe (intraday)", _fmt(report.sharpe)),
        ("Sortino (intraday)", _fmt(report.sortino)),
        ("Max Drawdown", f"{report.max_drawdown_pct:.2f}%"),
        ("Avg Slippage", _fmt(report.avg_slippage_pct) + "%"),
    ]

    # Markout curve section
    markout_html = ""
    if report.markout_curve:
        rows_html = "".join(
            f"<tr><td>{_e(pt.offset_label)}</td>"
            f"<td class='{_pnl_class(pt.avg_pct)}'>{pt.avg_pct:+.3f}%</td>"
            f"<td>{pt.sample_count}</td></tr>"
            for pt in report.markout_curve
        )
        markout_html = (
            "<h2>Markout Curve (Adverse Selection Monitor)</h2>"
            "<table><tr><th>Offset</th><th>Avg P&L %</th><th>Samples</th></tr>"
            f"{rows_html}</table>"
        )

    # Trade table
    trade_rows = "".join(
        f"<tr>"
        f"<td>{_e(t.symbol)}</td>"
        f"<td>{_e(t.direction)}</td>"
        f"<td>{t.quantity}</td>"
        f"<td>{t.entry_price:.2f}</td>"
        f"<td>{'%.2f' % t.exit_price if t.exit_price is not None else '—'}</td>"
        f"<td class='{_pnl_class(t.pnl)}'>{t.pnl:+.2f}</td>"
        f"<td class='{_pnl_class(t.pnl_pct)}'>{t.pnl_pct:+.2f}%</td>"
        f"<td>{_fmt(t.slippage_pct, 3)}%</td>"
        f"<td>{_e(t.strategy_tag)}</td>"
        f"</tr>"
        for t in report.trades
    )
    trades_html = (
        "<h2>Trade Detail</h2>"
        "<table>"
        "<tr><th>Symbol</th><th>Dir</th><th>Qty</th>"
        "<th>Entry</th><th>Exit</th><th>P&L</th><th>P&L %</th>"
        "<th>Slip %</th><th>Strategy</th></tr>"
        f"{trade_rows}"
        "</table>"
    )

    return (
        "<!DOCTYPE html><html><head>"
        f"<title>Daily Report {_e(date_str)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>Daily Trading Report &mdash; {_e(date_str)}</h1>"
        f"<p class='{pnl_cls}'>P&amp;L: <strong>{report.total_pnl:+,.2f}</strong>"
        f" ({report.total_pnl_pct:+.2f}%)</p>"
        "<h2>Performance Summary</h2>"
        f"{_summary_table(summary_rows)}"
        f"{markout_html}"
        f"{trades_html}"
        "</body></html>"
    )


def build_monthly_html(report: MonthlyReport) -> str:
    """Generate a monthly performance report as an HTML document.

    Args:
        report: Fully-populated MonthlyReport from ``compute_monthly_report``.

    Returns:
        UTF-8 HTML string.
    """
    month_name = calendar.month_name[report.month]
    title = f"{month_name} {report.year}"

    summary_rows: list[tuple[str, str]] = [
        ("Starting Capital", f"${report.starting_capital:,.2f}"),
        ("Total P&L", f"${report.total_pnl:+,.2f}"),
        ("Monthly Return", f"{report.total_pnl_pct:+.2f}%"),
        ("Total Trades", str(report.total_trades)),
        ("Win Rate (days)", f"{report.win_rate_pct:.1f}%"),
        ("Sharpe (monthly)", _fmt(report.sharpe)),
        ("Sortino (monthly)", _fmt(report.sortino)),
        ("Max Drawdown", f"{report.max_drawdown_pct:.2f}%"),
        ("Trading Days", str(len(report.daily_reports))),
    ]

    daily_rows = "".join(
        f"<tr>"
        f"<td>{_e(day.date.strftime('%Y-%m-%d'))}</td>"
        f"<td>{day.total_trades}</td>"
        f"<td class='{_pnl_class(day.total_pnl)}'>{day.total_pnl:+,.2f}</td>"
        f"<td class='{_pnl_class(day.total_pnl_pct)}'>{day.total_pnl_pct:+.2f}%</td>"
        f"<td>{day.win_rate_pct:.0f}%</td>"
        f"<td>{_fmt(day.sharpe)}</td>"
        f"<td>{day.max_drawdown_pct:.2f}%</td>"
        f"</tr>"
        for day in report.daily_reports
    )
    daily_table = (
        "<h2>Daily Breakdown</h2>"
        "<table>"
        "<tr><th>Date</th><th>Trades</th><th>P&L</th><th>P&L %</th>"
        "<th>Win Rate</th><th>Sharpe</th><th>Drawdown</th></tr>"
        f"{daily_rows}</table>"
    )

    return (
        "<!DOCTYPE html><html><head>"
        f"<title>Monthly Report {_e(title)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>Monthly Trading Report &mdash; {_e(title)}</h1>"
        "<h2>Monthly Performance Summary</h2>"
        f"{_summary_table(summary_rows)}"
        f"{daily_table}"
        "</body></html>"
    )
