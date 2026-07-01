# M06 — Pattern Recognition Engine

Candlestick pattern detection (61 TA-Lib CDL functions), Opening Range Breakout (ORB), and Support/Resistance level identification. Multi-timeframe cross-confirmation supported.

## Standalone usage

```bash
# Single timeframe
APP_ID=india python -m shared.patterns \
    --symbol RELIANCE --exchange NSE --timeframe 5m

# Multi-timeframe cross-confirmation
APP_ID=india python -m shared.patterns \
    --symbol RELIANCE --exchange NSE --timeframes 1m,5m,15m

# Requires TimescaleDB running with candle data present
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | required | `india` or `australia` |
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB |

## Key APIs

- `compute_snapshot(symbol, exchange, timeframe, candles)` → `PatternSnapshot`
- `compute_multi_timeframe(symbol, exchange, tf_candles)` → `MultiTimeframeSnapshot`
- `detect_all(arrays)` → `list[CandlestickSignal]` — all CDL patterns
- `detect_recent(candles, lookback_bars)` → `list[CandlestickSignal]` — M11 Gate 4 call
- `detect_orb(candles, session_open)` → `ORBState`
- `detect_sr_levels(candles)` → `list[SRLevel]`

## Design notes

CDL functions discovered dynamically via `dir(talib)` — TA-Lib upgrades auto-included (ADR-011). S/R clustering applied before touch-counting to avoid double-counting within a zone.

## Example output

```
{"symbol": "RELIANCE", "timeframe": "5m", "total_cdl_signals": 3,
 "sr_level_count": 4, "orb_formed": true, "orb_high": 2850.5, "orb_low": 2831.0,
 "event": "pattern_snapshot", "level": "info"}
```
