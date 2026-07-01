# App 1 — NSE/BSE India (Zerodha Kite Connect)

Heartbeat scaffold for the India trading app. Full agent wiring is owned by M18 (Agent Orchestrator). This app currently emits a heartbeat log every 10 seconds and confirms `TRADING_MODE=PAPER`.

## Standalone usage

```bash
APP_ID=india python -m apps.india.main
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | `india` | Must be `india` for this app |
| `TRADING_MODE` | `PAPER` | PAPER always default; `LIVE` requires `LIVE_TRADING_CONFIRMED=true` |
| `LIVE_TRADING_CONFIRMED` | `false` | Safety gate — both flags required for live orders |

## Example output

```
{"app_id": "india", "exchange": "NSE", "trading_mode": "PAPER",
 "live_trading_enabled": false, "event": "system_starting", "level": "info"}
{"event": "paper_trading_mode_active", "level": "info"}
{"app_id": "india", "event": "heartbeat", "level": "info"}
```
