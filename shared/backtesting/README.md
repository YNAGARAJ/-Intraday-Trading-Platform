# M07 — Backtesting Engine

vectorbt-based backtester with log-normal slippage model parameterised by time-of-day bucket and bid-ask spread width. Includes markout analyser, walk-forward optimisation, and the RULE 6 model-promotion gate.

## Standalone usage

```bash
# Backtest EMA crossover on RELIANCE over the last year
APP_ID=india python -m shared.backtesting \
    --symbol RELIANCE --exchange NSE \
    --strategy ema_crossover \
    --start-date 2023-01-01 --end-date 2023-12-31 \
    --report-dir /tmp/bt_reports

# Skip DB save (dry run)
APP_ID=india python -m shared.backtesting --symbol RELIANCE --exchange NSE --no-db
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | required | `india` or `australia` |
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB |

## Key APIs

- `sample_slippage_bps(signal_time, spread_bps, rng)` — log-normal slip draw
- `fit_from_fills(fills)` — refit params from real M16 broker fills
- `ema_crossover_signals(candles)` → `(entries, exits)`
- `run_backtest(config, candles, entries, exits)` → `BacktestResult`
- `run_walk_forward(config, candles, signal_fn, param_grid)` → `list[BacktestResult]`
- `check_promotion_gate(metrics)` → `list[str]` — empty = RULE 6 passed
- `compute_metrics(trades, equity_values, ...)` → `BacktestMetrics`

## RULE 6 promotion gate

20 trading days minimum · Sharpe > 1.5 · win rate > 50% · max drawdown < 5%

## Slippage buckets (NSE)

| Bucket | Window | μ (log) | σ (log) | Median bps |
|---|---|---|---|---|
| OPEN | 09:15–10:00 | 2.0 | 0.5 | ~7.4 |
| MID_SESSION | 10:00–14:30 | 1.4 | 0.4 | ~4.1 |
| CLOSE | 14:30–15:10 | 1.8 | 0.5 | ~6.0 |

## Example output

```
{"run_id": "bt-20230101-abc123", "trades": 48, "sharpe": 1.87,
 "max_dd_pct": 3.2, "win_rate_pct": 54.2, "passed_gate": true,
 "event": "backtest_done", "level": "info"}
```
