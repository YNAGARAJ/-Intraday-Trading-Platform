# M21 — Reporting Module

Daily/monthly PDF and HTML reports, markout curves, and trade-by-trade CSV/Excel exports.

## Modules

| File | Purpose |
|---|---|
| `models.py` | `TradeRecord`, `MarkoutPoint`, `DailyReport`, `MonthlyReport` dataclasses |
| `metrics.py` | `compute_sharpe`, `compute_sortino`, `compute_max_drawdown`, `compute_daily_report`, `compute_monthly_report` |
| `pdf_report.py` | `build_daily_pdf(report) → bytes`, `build_monthly_pdf(report) → bytes` via fpdf2 |
| `html_report.py` | `build_daily_html(report) → str`, `build_monthly_html(report) → str` with inline CSS |
| `csv_export.py` | `trades_to_csv(trades) → bytes`, `trades_to_excel(trades, daily_report=None) → bytes` |
| `cli.py` | 20 VERIFY scenarios |

## Quick start

```bash
python -m shared.reporting
```

Expected output: 20/20 `verify_pass` events.

## API

```python
from shared.reporting.models import TradeRecord
from shared.reporting.metrics import compute_daily_report, compute_monthly_report
from shared.reporting.pdf_report import build_daily_pdf, build_monthly_pdf
from shared.reporting.html_report import build_daily_html, build_monthly_html
from shared.reporting.csv_export import trades_to_csv, trades_to_excel

trade = TradeRecord(
    trade_id="T001", symbol="RELIANCE", exchange="NSE", direction="LONG",
    entry_time_ms=1_700_000_000_000, exit_time_ms=1_700_003_600_000,
    entry_price=2900.0, exit_price=2914.5, quantity=100,
    pnl=1450.0, pnl_pct=0.5, strategy_tag="STRAT001",
    slippage_pct=0.02, markout_1m_pct=0.3, markout_5m_pct=0.5,
)

daily = compute_daily_report(date(2026, 7, 1), [trade], starting_capital=1_000_000.0)

pdf_bytes   = build_daily_pdf(daily)   # %PDF-...
html_str    = build_daily_html(daily)  # <!DOCTYPE html>...
csv_bytes   = trades_to_csv(daily.trades)
excel_bytes = trades_to_excel(daily.trades, daily_report=daily)

monthly = compute_monthly_report(2026, 7, [daily])
monthly_pdf  = build_monthly_pdf(monthly)
monthly_html = build_monthly_html(monthly)
```

## Metrics formulas

- **Sharpe**: `mean(r) / std(r, ddof=1) * sqrt(252)` — `None` if < 2 points or zero variance
- **Sortino**: `mean(r) / std(downside_r, ddof=0) * sqrt(252)` — `None` if no negative returns or zero downside std
- **Max drawdown**: `max((peak - trough) / peak)` over cumulative wealth path — returns fraction
- **Win rate**: `winning_trades / total_trades * 100`
- **Markout curve**: averages `markout_1m_pct` and `markout_5m_pct` across all trades with non-None values

## Excel output

- Sheet **Trades**: one row per trade, all `TradeRecord` fields as columns
- Sheet **Summary**: key metrics (total PnL, Sharpe, Sortino, max drawdown, win rate, avg slippage) — only present when `daily_report` is supplied

## Dependencies

- `fpdf2==2.7.8` — PDF generation (Latin-1 Helvetica font; em-dashes replaced with ASCII hyphens)
- `openpyxl>=3.1.5` — Excel `.xlsx` generation
- `numpy` — metrics computation (already in stack)

## Environment variables

None — this module is stateless. It receives data from callers and returns bytes/strings.
