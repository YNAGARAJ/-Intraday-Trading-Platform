# App 2 — ASX Australia (Interactive Brokers TWS)

Heartbeat scaffold for the Australia trading app. Full agent wiring is owned by M18 (Agent Orchestrator). This app currently emits a heartbeat log every 10 seconds and confirms `TRADING_MODE=PAPER`.

## Standalone usage

```bash
APP_ID=australia python -m apps.australia.main
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | `australia` | Must be `australia` for this app |
| `TRADING_MODE` | `PAPER` | PAPER always default; `LIVE` requires `LIVE_TRADING_CONFIRMED=true` |
| `LIVE_TRADING_CONFIRMED` | `false` | Safety gate — both flags required for live orders |

## Example output

```
{"app_id": "australia", "exchange": "ASX", "trading_mode": "PAPER",
 "live_trading_enabled": false, "event": "system_starting", "level": "info"}
{"event": "paper_trading_mode_active", "level": "info"}
{"app_id": "australia", "event": "heartbeat", "level": "info"}
```
