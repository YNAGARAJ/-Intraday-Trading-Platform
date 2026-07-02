# M22 — Dashboard & API

FastAPI REST + WebSocket server that exposes live trading system state from Redis. The Streamlit dashboard (`dashboard/`) reads exclusively through this API.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Liveness probe — `{"status": "ok"}` |
| GET | `/api/v1/status` | Optional¹ | Full system status snapshot |
| GET | `/api/v1/positions` | Optional¹ | Open positions from orchestrator state |
| GET | `/api/v1/signals` | Optional¹ | Recent signals from Redis stream |
| GET | `/api/v1/pnl` | Optional¹ | Today's P&L summary |
| GET | `/api/v1/watchlist` | Optional¹ | Current watchlist (`?exchange=NSE\|ASX`) |
| POST | `/api/v1/controls/kill` | Required | Trigger Tier 2 kill switch |
| POST | `/api/v1/controls/pause` | Required | Pause new entry signals |
| POST | `/api/v1/controls/resume` | Required | Resume new entry signals |
| WS | `/ws/live` | Optional¹ | Real-time signal stream + heartbeat pings |

¹ Optional auth: enforced only when `API_KEY` is set in env. Required on controls: always enforced.

## Security

All control endpoints require `X-API-Key` header matching `settings.api_key`. When no key is configured (empty string), controls return 403 — operators must set a key before using them.

**RULE 8:** `is_priority` is never set by the API layer. `/kill` delegates to `KillSwitchManager.trigger_tier2()` which sets it internally.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `""` | X-API-Key for control endpoints; empty disables auth on reads |
| `API_PORT` | `8080` | Server port (separate from Prometheus metrics on 8000) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `TRADING_MODE` | `PAPER` | `PAPER` or `LIVE` |

## Running

```bash
# Start the FastAPI server
python -m api --serve

# Run 20 VERIFY scenarios (no server needed)
python -m api
```

## WebSocket protocol

Connect to `ws://host:8080/ws/live` (add `?api_key=<key>` when auth is configured).

Messages from server:

```json
{"type": "ping", "ts": 1700000000000}
{"type": "signal", "id": "...", "data": {...}, "ts": 1700000000000}
```

Heartbeat pings are sent on connect and every 30 seconds. Signals are forwarded from the `signals:generated` Redis stream as they arrive.

## Example

```bash
curl http://localhost:8080/health
# {"status":"ok"}

curl -H "X-API-Key: $API_KEY" -X POST http://localhost:8080/api/v1/controls/pause
# {"success":true,"action":"pause","reason":"New entries paused"}
```
