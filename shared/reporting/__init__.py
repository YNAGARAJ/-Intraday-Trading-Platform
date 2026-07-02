"""M21 Reporting Module — public API.

Report generation:
- ``build_daily_pdf(report)`` / ``build_monthly_pdf(report)`` → bytes (fpdf2)
- ``build_daily_html(report)`` / ``build_monthly_html(report)`` → str

Data export:
- ``trades_to_csv(trades)`` → bytes (UTF-8 CSV)
- ``trades_to_excel(trades, daily_report)`` → bytes (xlsx via openpyxl)

Metrics:
- ``compute_daily_report(date, trades, capital)`` → DailyReport
- ``compute_monthly_report(year, month, daily_reports)`` → MonthlyReport
- ``compute_sharpe(returns)``, ``compute_sortino(returns)``,
  ``compute_max_drawdown(returns)``

Models:
- ``TradeRecord``, ``DailyReport``, ``MonthlyReport``, ``MarkoutPoint``
"""

from shared.reporting.csv_export import trades_to_csv, trades_to_excel
from shared.reporting.html_report import build_daily_html, build_monthly_html
from shared.reporting.metrics import (
    compute_daily_report,
    compute_max_drawdown,
    compute_monthly_report,
    compute_sharpe,
    compute_sortino,
)
from shared.reporting.models import (
    DailyReport,
    MarkoutPoint,
    MonthlyReport,
    TradeRecord,
)
from shared.reporting.pdf_report import build_daily_pdf, build_monthly_pdf

__all__ = [
    "DailyReport",
    "MarkoutPoint",
    "MonthlyReport",
    "TradeRecord",
    "build_daily_html",
    "build_daily_pdf",
    "build_monthly_html",
    "build_monthly_pdf",
    "compute_daily_report",
    "compute_max_drawdown",
    "compute_monthly_report",
    "compute_sharpe",
    "compute_sortino",
    "trades_to_csv",
    "trades_to_excel",
]
