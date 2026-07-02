# M22 — Streamlit Dashboard

Operational UI that polls the M22 FastAPI server for live trading system state. No direct Redis access — all data flows through the API layer.

## Running

```bash
# Requires the FastAPI server to be running first
python -m api --serve &

# Launch dashboard
python -m dashboard
# or equivalently:
streamlit run dashboard/app.py
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_DASHBOARD_BASE_URL` | `http://localhost:8080` | Base URL of the FastAPI server |
| `API_KEY` | `""` | API key for control endpoints |

## Features

- **Status banner** — trading mode, halted/paused/degraded indicators, kill switch / circuit breaker state
- **KPI row** — today's P&L, P&L%, open positions, signals today, regime
- **Sidebar controls** — Kill switch, Pause, Resume buttons (require API key)
- **Open positions table** — live from orchestrator state
- **Signal feed** — latest 20 signals from Redis stream
- **Watchlist** — current NSE/ASX watchlist with composite scores
- **Auto-refresh** — configurable interval (5–60 s)

## Architecture

```
dashboard/app.py        ← Streamlit UI
dashboard/fetcher.py    ← Pure data-fetching functions (httpx)
api/                    ← FastAPI server (M22)
Redis                   ← Source of truth
```

`fetcher.py` is fully testable without Streamlit — all API calls are plain `httpx` functions returning dicts.
