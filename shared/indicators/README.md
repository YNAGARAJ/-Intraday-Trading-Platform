# M04 — Core Technical Indicator Engine

Extensible indicator registry built on TA-Lib 0.6.8 + NumPy/pandas. Computes 16 indicators across multiple timeframes with Redis caching. Compute latency target: < 50 ms for 240 candles.

## Standalone usage

```bash
# Compute all indicators for RELIANCE.NS on the 5m timeframe
APP_ID=india python -m shared.indicators \
    --symbol RELIANCE.NS --exchange NSE --timeframe 5m

# Requires TimescaleDB + Redis running
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | required | `india` or `australia` |
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for indicator cache |

## Key APIs

- `all_indicators()` → `dict[str, IndicatorSpec]` — full registry
- `compute_snapshot(symbol, exchange, timeframe, candles)` → `IndicatorSnapshot`
- `store_snapshot(redis_client, snapshot)` — cache snapshot in Redis
- `@register_indicator(name, min_candles)` — decorator to add a new indicator

## Registered indicators (16)

ADX, ATR, Bollinger Bands, CCI, EMA, MACD, MFI, OBV, Pivot Points, ROC, RSI, Stochastic, Volume Delta, VWAP, VWAP Bands, Williams %R

## Example output

```
{"symbol": "RELIANCE.NS", "timeframe": "5m", "candle_count": 240,
 "indicator_count": 16, "latency_ms": 3.2, "within_budget": true,
 "event": "indicators_computed", "level": "info"}
```
