# M15 — Authentication & Token Manager

Manages broker authentication for both Zerodha Kite (App 1 / NSE/BSE) and Interactive Brokers
TWS (App 2 / ASX). Provides TOTP auto-login, Redis-backed token storage with in-memory fallback,
a thread-safe IBKR connection pool, and a daily token refresh scheduler.

## Modules

| File | Purpose |
|---|---|
| `models.py` | `AuthMode`, `TokenRecord`, `IBKRClientSlot` data classes |
| `token_store.py` | `TokenStore` — save/load/delete tokens in Redis with in-memory fallback |
| `kite_auth.py` | `KiteAuthManager` — TOTP auto-login via pyotp + requests |
| `ibkr_auth.py` | `IBKRConnectionPool` — fixed-size clientId pool with heartbeat |
| `scheduler.py` | `DailyRefreshScheduler` — fires callback at 08:30 IST using threading.Timer |
| `cli.py` | 20 VERIFY scenarios (run with `python -m shared.auth verify`) |

## Usage

```python
from shared.auth import AuthMode, KiteAuthManager, TokenStore, IBKRConnectionPool

# Kite paper-mode login (no real credentials required)
store = TokenStore()
mgr = KiteAuthManager(
    user_id="ZYUSER",
    password="...",
    totp_secret="BASE32SECRET",
    api_key="...",
    api_secret="...",
    token_store=store,
    mode=AuthMode.PAPER,  # default
)
record = mgr.get_token()  # returns cached or logs in fresh
mgr.invalidate()           # force re-login on next get_token()

# IBKR connection pool
pool = IBKRConnectionPool(mode=AuthMode.PAPER, pool_size=4, enable_heartbeat=True)
slot = pool.acquire()
connected = pool.connect(slot)  # False if ibapi not installed
pool.release(slot)
pool.shutdown()
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `KITE_USER_ID` | — | Zerodha user ID (LIVE mode) |
| `KITE_PASSWORD` | — | Zerodha password (LIVE mode, never logged) |
| `KITE_TOTP_SECRET` | — | TOTP base32 seed (never logged) |
| `KITE_API_KEY` | — | Kite Connect API key |
| `KITE_API_SECRET` | — | Kite Connect API secret (never logged) |
| `IBKR_HOST` | `127.0.0.1` | TWS host address |
| `TRADING_MODE` | `PAPER` | `PAPER` or `LIVE` — controls port and credential requirement |

## Key Constants

| Constant | Value | Description |
|---|---|---|
| `KITE_SESSION_TTL_SECONDS` | 30600 | Token TTL: 8.5 hours (Kite session lifetime) |
| `KITE_DAILY_REFRESH_IST_HOUR` | 8 | Daily re-login hour (IST) |
| `KITE_DAILY_REFRESH_IST_MINUTE` | 30 | Daily re-login minute (IST) |
| `IBKR_PAPER_PORT` | 7497 | TWS paper-trading port |
| `IBKR_LIVE_PORT` | 7496 | TWS live-trading port |
| `IBKR_CLIENT_ID_POOL_MAX` | 8 | Maximum pool size |
| `IBKR_HEARTBEAT_INTERVAL_SECONDS` | 30 | Heartbeat ping interval |

## Security

- Credentials (`password`, `totp_secret`, `api_secret`, `access_token`) are **never logged**.
- `TokenRecord.__repr__` omits `access_token`.
- TLS required on all Redis connections in production (Redis client configured by caller).
- `TRADING_MODE=PAPER` is the default; live requires explicit env override.

## Standalone Run

```bash
python -m shared.auth verify
```

Expected output: 20 VERIFY scenarios all PASS.
