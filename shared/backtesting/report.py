"""HTML and CSV report generation for backtest results.

Produces two artefacts per run:
  <report_dir>/<run_id>_backtest.html  — self-contained HTML with metrics table,
                                          equity curve, markout summary, trade list.
  <report_dir>/<run_id>_trades.csv     — trade-by-trade breakdown.

No Jinja2 dependency — the HTML is built with f-strings so there are no extra
template-file dependencies to manage. The resulting file is fully self-contained
(no external CDN links, all styling inline) so it can be viewed offline.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from shared.backtesting.models import BacktestResult, Trade
from shared.core.logging import get_logger

logger = get_logger(__name__)

_PASS_COLOUR = "#2e7d32"
_FAIL_COLOUR = "#c62828"
_TABLE_HEADER_BG = "#1565c0"


def _fmt_pct(v: float) -> str:
    return f"{v:+.2f}%"


def _fmt_float(v: float) -> str:
    return f"{v:.4f}"


def _gate_badge(passed: bool) -> str:
    colour = _PASS_COLOUR if passed else _FAIL_COLOUR
    label = "PASSED" if passed else "FAILED"
    return f'<span style="color:{colour};font-weight:bold">{label}</span>'


def _metrics_rows(result: BacktestResult) -> str:
    m = result.metrics
    rows = [
        ("Strategy ID", result.config.strategy_id),
        ("Symbol", f"{result.config.symbol} / {result.config.exchange}"),
        ("Period", f"{result.config.start_date} → {result.config.end_date}"),
        ("Trading days", str(m.trading_days)),
        ("Total trades", str(m.total_trades)),
        ("Total return", _fmt_pct(m.total_return_pct)),
        ("Annualised return", _fmt_pct(m.annualized_return_pct)),
        ("Sharpe ratio", _fmt_float(m.sharpe_ratio)),
        ("Sortino ratio", _fmt_float(m.sortino_ratio)),
        ("Max drawdown", _fmt_pct(m.max_drawdown_pct)),
        ("Win rate", _fmt_pct(m.win_rate_pct)),
        ("Expectancy / trade", _fmt_pct(m.expectancy_per_trade)),
        ("Profit factor", _fmt_float(m.profit_factor)),
        ("Calmar ratio", _fmt_float(m.calmar_ratio)),
        ("Avg slippage", f"{m.avg_slippage_bps:.2f} bps"),
        ("RULE 6 gate", _gate_badge(result.passed_promotion_gate)),
    ]
    if result.promotion_failures:
        rows.append(("Gate failures", "; ".join(result.promotion_failures)))
    return "\n".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows)


def _markout_rows(result: BacktestResult) -> str:
    if not result.markout_curves:
        return "<tr><td colspan='4'>No markout data</td></tr>"
    return "\n".join(
        f"<tr>"
        f"<td>{mp.offset_label}</td>"
        f"<td>{_fmt_pct(mp.avg_return_pct)}</td>"
        f"<td>{_fmt_pct(mp.median_return_pct)}</td>"
        f"<td>{_fmt_pct(mp.win_rate_at_offset * 100)}</td>"
        f"</tr>"
        for mp in result.markout_curves
    )


def _trade_rows(trades: list[Trade]) -> str:
    if not trades:
        return "<tr><td colspan='7'>No trades</td></tr>"
    rows = []
    for t in trades:
        pnl_colour = _PASS_COLOUR if t.pnl_pct > 0 else _FAIL_COLOUR
        rows.append(
            f"<tr>"
            f"<td>{t.trade_id}</td>"
            f"<td>{t.entry_time.strftime('%Y-%m-%d %H:%M')}</td>"
            f"<td>{t.exit_time.strftime('%Y-%m-%d %H:%M')}</td>"
            f"<td>{t.entry_price:.2f}</td>"
            f"<td>{t.exit_price:.2f}</td>"
            f"<td style='color:{pnl_colour}'>{_fmt_pct(t.pnl_pct)}</td>"
            f"<td>{t.entry_slippage_bps:.1f} / {t.exit_slippage_bps:.1f}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _equity_sparkline(result: BacktestResult) -> str:
    """Inline SVG equity curve sparkline (no JS or external lib needed)."""
    if len(result.equity_curve) < 2:
        return "<p>Insufficient data for equity curve.</p>"
    values = [v for _, v in result.equity_curve]
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        return "<p>Flat equity curve (no trades executed).</p>"
    w, h = 800, 120
    pts = []
    n = len(values)
    for i, v in enumerate(values):
        x = int(i / (n - 1) * w)
        y = int(h - (v - min_v) / (max_v - min_v) * h)
        pts.append(f"{x},{y}")
    poly = " ".join(pts)
    return (
        f'<svg width="{w}" height="{h}" style="border:1px solid #ccc">'
        f'<polyline points="{poly}" fill="none" stroke="#1565c0" stroke-width="1.5"/>'
        f"</svg>"
    )


def _build_html(result: BacktestResult) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Backtest Report — {result.config.strategy_id} {result.config.symbol}</title>
<style>
  body{{font-family:sans-serif;margin:24px;background:#fafafa;color:#222}}
  h1{{color:#1565c0}}h2{{color:#333;margin-top:32px}}
  table{{border-collapse:collapse;width:100%;max-width:900px}}
  th{{background:{_TABLE_HEADER_BG};color:#fff;padding:6px 12px;text-align:left}}
  td{{padding:5px 12px;border-bottom:1px solid #ddd}}
  tr:nth-child(even){{background:#f0f4ff}}
</style>
</head>
<body>
<h1>Backtest Report</h1>
<p>Run ID: <code>{result.run_id}</code> &nbsp;|&nbsp;
   Generated: {result.completed_at.strftime('%Y-%m-%d %H:%M UTC')}</p>

<h2>Performance Summary</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
{_metrics_rows(result)}
</table>

<h2>Equity Curve</h2>
{_equity_sparkline(result)}

<h2>Markout Curves (adverse selection)</h2>
<table>
<tr><th>Offset</th><th>Avg return</th><th>Median return</th><th>Win rate</th></tr>
{_markout_rows(result)}
</table>

<h2>Trade Log ({result.metrics.total_trades} trades)</h2>
<table>
<tr><th>#</th><th>Entry</th><th>Exit</th>
    <th>Entry price</th><th>Exit price</th>
    <th>P&amp;L %</th><th>Slip (in/out bps)</th></tr>
{_trade_rows(result.trades)}
</table>
</body>
</html>"""


def generate_reports(result: BacktestResult, report_dir: str) -> BacktestResult:
    """Write HTML and CSV reports and return an updated BacktestResult with paths set.

    Args:
        result: Completed BacktestResult (report paths must be None on entry).
        report_dir: Directory where reports are written. Created if absent.

    Returns:
        New BacktestResult instance with report_html_path and report_csv_path filled in.
    """
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    html_path = os.path.join(report_dir, f"{result.run_id}_backtest.html")
    csv_path = os.path.join(report_dir, f"{result.run_id}_trades.csv")

    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(_build_html(result))

    with open(csv_path, "w", newline="", encoding="utf-8") as fc:
        writer = csv.writer(fc)
        writer.writerow(
            [
                "trade_id",
                "symbol",
                "exchange",
                "strategy_id",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "entry_slippage_bps",
                "exit_slippage_bps",
                "quantity",
                "pnl",
                "pnl_pct",
            ]
        )
        for t in result.trades:
            writer.writerow(
                [
                    t.trade_id,
                    t.symbol,
                    t.exchange,
                    t.strategy_id,
                    t.entry_time.isoformat(),
                    t.exit_time.isoformat(),
                    t.entry_price,
                    t.exit_price,
                    t.entry_slippage_bps,
                    t.exit_slippage_bps,
                    t.quantity,
                    t.pnl,
                    t.pnl_pct,
                ]
            )

    logger.info(
        "backtest_reports_written",
        run_id=result.run_id,
        html=html_path,
        csv=csv_path,
    )

    # Return a new frozen-ish result with paths filled in — BacktestResult uses
    # dataclass(frozen=True) so we rebuild via __class__ constructor.
    from dataclasses import replace

    return replace(result, report_html_path=html_path, report_csv_path=csv_path)
