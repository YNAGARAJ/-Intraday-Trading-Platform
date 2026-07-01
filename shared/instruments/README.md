# M05 — Instrument Master & Corporate Actions

Canonical instrument list for NSE and ASX with split/bonus/dividend-adjusted price series. Feeds all downstream modules that need adjusted OHLCV data.

## Standalone usage

```bash
# Refresh instrument master + corporate actions, then look up RELIANCE on NSE
APP_ID=india python -m shared.instruments \
    --symbol RELIANCE --exchange NSE

# Requires TimescaleDB running. Live NSE fetch uses cookie bootstrap (confirmed working).
# ASX corporate actions fall back to shared/instruments/manual_overrides.yaml (ADR-010).
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | required | `india` or `australia` |
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB |

## Key APIs

- `adjusted_candles(candles, actions)` → `list[OHLCVCandle]` — apply split/bonus adjustments
- `InstrumentRepository(conn)` — `get(symbol, exchange)`, `upsert(instrument)`
- `CorporateActionRepository(conn)` — `list_for_symbol(symbol, exchange)`, `upsert(action)`
- `refresh_instrument_master(repo, exchange)` — live fetch from NSE/ASX
- `refresh_corporate_actions(repo)` — live fetch from NSE API + manual overrides

## Adjustment scope

SPLIT and BONUS adjust prices and volumes. DIVIDEND is recorded but not price-adjusted (requires prior-day close; ADR-010). SYMBOL_CHANGE is recorded but not stitched.

## Example output

```
{"symbol": "RELIANCE", "exchange": "NSE", "name": "RELIANCE INDUSTRIES LTD",
 "event": "instrument_found", "level": "info"}
{"symbol": "RELIANCE", "action_count": 3, "event": "corporate_action_history", "level": "info"}
```
