# M01 — Project Scaffold & Config (shared/core)

Monorepo foundation: Pydantic Settings v2 config, structlog JSON logging, custom exception hierarchy, type aliases, constants, and Protobuf message definitions. Every other module depends on this package.

## Key APIs

- `load_settings(app_id)` → `Settings` — Pydantic v2 settings from env + YAML
- `settings.is_live_trading_enabled` — `True` only when BOTH `TRADING_MODE=LIVE` AND `LIVE_TRADING_CONFIRMED=true`
- `configure_logging(level)` — structlog JSON renderer, secrets never logged
- `get_logger(name)` → bound structlog logger
- `TradingMode`, `AppId` — type-safe enums for mode and app identity

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | required | `india` or `australia` |
| `TRADING_MODE` | `PAPER` | `PAPER` or `LIVE` — PAPER is always the default (ADR-003) |
| `LIVE_TRADING_CONFIRMED` | `false` | Must ALSO be `true` for live orders to be permitted |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB |
| `POSTGRES_DSN` | `postgresql://trading:trading@localhost:5432/trading` | pgvector PostgreSQL |
| `LOG_LEVEL` | `INFO` | structlog log level |

## Exception hierarchy

`TradingSystemError` → `NoStopLossError` · `KillSwitchActiveError` · `ComplianceViolationError` · `InsufficientMarginError` · `RateLimitExceededError` · `ReconciliationMismatchError` (and others)

## Proto messages

`shared/proto/messages_pb2.py` — `SignalGenerated`, `OrderIntent`, `OrderFilled`, `RegimeChanged`, `AgentHeartbeat`, `KillSwitchActivated`, `ReconciliationMismatch`
