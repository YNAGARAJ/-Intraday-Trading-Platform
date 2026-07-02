# M16 — Data Ingestion Agent

Real-time market data ingestion pipeline for both NSE/BSE (via Kite WebSocket) and ASX
(via IBKR TWS streaming).  Converts raw tick feeds into validated OHLCV candles and
buffers raw ticks for async TimescaleDB writes.

## Architecture

```
[WebSocket / REST fallback]
         │
         ▼
[TickSequenceValidator]  ← rejects corrupt / out-of-sequence ticks
         │
    ┌────┴─────┐
    ▼          ▼
[CandleAgg 1m]  [CandleAgg 5m]  ← NumPy in-memory OHLCV aggregation
         │
         ▼
[TickBuffer → Redis ticker:buffer:queue]  ← async batch writer
         │
         ▼
[TimescaleDB (batch flush every 1000 ticks or 5s)]
```

On WebSocket drop, the watchdog thread triggers **DEGRADED_EXIT_ONLY** mode within 2
seconds (RULE 5) and switches to yfinance REST fallback.

## Modules

| File | Purpose |
|---|---|
| `models.py` | `RawTick`, `OHLCVCandle`, `IngestionStatus`, `TickValidationError` |
| `validator.py` | `TickSequenceValidator` — rejects zero-price, seq-reversal, future ticks |
| `aggregator.py` | `CandleAggregator` — NumPy-backed 1m/5m OHLCV bar assembly |
| `buffer.py` | `TickBuffer` — Redis list queue with in-memory fallback |
| `yfinance_fallback.py` | `YFinanceFallback` — REST fallback (dev/degraded mode only) |
| `kite_ws.py` | `KiteWebSocketAdapter` — Kite Connect WS feed (App 1 / NSE/BSE) |
| `ibkr_ws.py` | `IBKRStreamAdapter` — IBKR TWS market data (App 2 / ASX) |
| `agent.py` | `DataIngestionAgent` — orchestrator wiring all components |
| `cli.py` | 20 VERIFY scenarios (`python -m shared.ingestion verify`) |

## Usage

```python
from shared.ingestion import (
    DataIngestionAgent, CandleAggregator, TickBuffer,
    IngestionStatus, RawTick,
)

# Paper mode: inject synthetic ticks
agent = DataIngestionAgent(
    symbols=["RELIANCE", "INFY"],
    exchange="NSE",
    mode=IngestionStatus.PAPER,
)

# Inject a tick (validate → aggregate → buffer)
from shared.ingestion.models import RawTick
import time
tick = RawTick(symbol="RELIANCE", exchange="NSE", ltp=2500.0,
               volume=100, timestamp_ms=int(time.time() * 1000) - 5000)
candles = agent.inject_tick(tick)  # returns list of completed candles

# Retrieve the latest completed 1m candle
candle = agent.get_latest_candle("RELIANCE", interval=60)
if candle:
    print(f"O={candle.open} H={candle.high} L={candle.low} C={candle.close}")

# Force-close all open bars (end of session)
open_bars = agent.flush_open_bars()
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TRADING_MODE` | `PAPER` | Controls whether real WS credentials are used |

## Key Constants

| Constant | Value | Description |
|---|---|---|
| `TICK_BUFFER_REDIS_KEY` | `"ticker:buffer:queue"` | Redis List key for the async tick queue |
| `TICK_BUFFER_FLUSH_COUNT` | 1000 | Batch flush to DB when N ticks accumulate |
| `TICK_BUFFER_FLUSH_INTERVAL_SECONDS` | 5 | Max seconds between flushes |
| `WS_FALLBACK_TIMEOUT_SECONDS` | 2 | WS drop → DEGRADED_EXIT_ONLY within this window |
| `INGESTION_DEGRADED_REDIS_KEY` | `"system:status:degraded"` | Flag read by M18 orchestrator |
| `TICK_MAX_BACKWARD_MS` | 500 | Reject ticks >500ms before last accepted (same symbol) |
| `TICK_MAX_FUTURE_MS` | 2000 | Reject ticks >2s ahead of wall-clock |
| `CANDLE_INTERVAL_1M` | 60 | 1-minute bar interval in seconds |
| `CANDLE_INTERVAL_5M` | 300 | 5-minute bar interval in seconds |

## DEGRADED_EXIT_ONLY Behaviour

When the WebSocket heartbeat times out (no tick in 2s):
1. Watchdog thread sets `INGESTION_DEGRADED_REDIS_KEY = "true"` in Redis.
2. `agent.mode` switches to `IngestionStatus.DEGRADED`.
3. yfinance REST fallback fires for all subscribed symbols.
4. M18 orchestrator reads the key and blocks new entry signals.
5. On WebSocket reconnect, the flag is cleared and mode returns to LIVE.

## Standalone Run

```bash
python -m shared.ingestion verify
```

Expected: 20 VERIFY scenarios all PASS, 1000-tick latency < 200ms.
