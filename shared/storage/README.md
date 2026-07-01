# M03 — High-Throughput Buffering & Storage

TimescaleDB hypertables, continuous aggregates, SQLite failover buffer, yfinance backfill, and the repository pattern for OHLCV data.

## Standalone usage

```bash
# Apply schema and backfill 30 days of RELIANCE.NS 1-minute candles
APP_ID=india python -m shared.storage \
    --symbol RELIANCE.NS --exchange NSE --days 30

# Requires TimescaleDB running at TIMESCALE_DSN (default: localhost:5433)
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB connection string |
| `APP_ID` | required | `india` or `australia` |

## Key APIs

- `get_connection(settings)` → `PGConnection` — connect to TimescaleDB
- `apply_schema(conn)` — idempotent schema apply (hypertables + continuous aggregates)
- `OHLCVRepository(conn)` — `upsert_1m(candles)`, `query_candles(symbol, exchange, timeframe, start, end)`
- `SQLiteFailoverBuffer(path)` — RULE 5 write buffer when TimescaleDB is unreachable

## Continuous aggregates

`ohlcv_5m`, `ohlcv_15m`, `ohlcv_1h` — computed from `ohlcv_1m` with `materialized_only=false` (real-time aggregation, ADR-008).

## Example output

```
{"event": "schema_applied", "level": "info"}
{"rows_inserted": 252, "symbol": "RELIANCE.NS", "event": "backfill_complete", "level": "info"}
```
