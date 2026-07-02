# M11 — Signal Generation Agent

Pure-Python 9-gate signal evaluation system. No LLM on the hot path (RULE 4). All gates complete in < 100 ms; LLM explanation fires asynchronously after the signal is published.

## Architecture

```
SignalContext → SignalEngine.evaluate() → SignalResult
                    │
                    ├── gate_1_regime        (terminating)
                    ├── gate_2_indicators    (terminating, min 3/8 agree)
                    ├── gate_3_order_flow    (terminating)
                    ├── gate_4_candlestick   (terminating)
                    ├── gate_5_multi_timeframe (terminating)
                    ├── gate_6_sr_proximity  (terminating)
                    ├── gate_7_session_timing (terminating)
                    ├── gate_8_divergence    (non-terminating, confidence only)
                    └── gate_9_confidence    (terminating, threshold 0.70/0.80)
```

Signal published atomically via `signal_dedup.lua` to Redis Streams key `signals:generated`.
`explain_signal()` called async after publish — never blocks order flow.

## Gate summary

| Gate | Rule | Fail behaviour |
|------|------|----------------|
| 1 | Regime: HIGH_VOL_CHAOS blocked; BULL/BEAR direction mismatch blocked | Hard fail |
| 2 | ≥ 3 of 8 indicators agree (EMA, VWAP, RSI, MACD, STOCH, BBANDS, ORB, VOL) | Hard fail |
| 3 | No institutional absorption; footprint delta confirms direction | Hard fail |
| 4 | ≥ 1 candlestick pattern or ORB breakout confirms direction in last 3 bars | Hard fail |
| 5 | ≥ 2 timeframes confirm (MultiTimeframePatterns.confirmed_bullish/bearish) | Hard fail |
| 6 | Price within 0.5% of matching S/R level | Hard fail |
| 7 | Not in opening 15-min noise window or closing 30-min window | Hard fail |
| 8 | RSI/MACD divergence check; sentiment bonus | Confidence ±0.05–0.10 only |
| 9 | Composite confidence ≥ 0.70 (0.80 in SEBI snapshot window) | Hard fail |

Base confidence = 0.40 + gate bonuses from gates 2–6, clamped [0, 1] after gate 8.

## Key APIs

```python
from shared.signals import SignalEngine, SignalContext, SignalResult, SignalPublisher

engine = SignalEngine()
result: SignalResult = engine.evaluate(ctx)          # < 100 ms, pure Python

publisher = SignalPublisher(redis_client)
entry_id = publisher.publish(result)                 # atomic Lua dedup + stream publish

# async, fire-and-forget after publish:
await explain_signal(result, model="groq/llama-3.1-70b-versatile")
```

## Environment variables

None beyond what M01 defines (`REDIS_URL`). The LLM explain call uses the API key from the environment matching the litellm model string (e.g. `GROQ_API_KEY`).

## Standalone usage

```bash
# Replay both directions for a symbol (synthetic data):
python -m shared.signals replay RELIANCE.NS --exchange NSE

# Test only that HIGH_VOL_CHAOS blocks all signals:
python -m shared.signals replay RELIANCE.NS --chaos-only
```

Example output:
```
=== M11 Signal Generation Agent — VERIFY replay for RELIANCE.NS ===

Direction: LONG
  Generated:  True
  Confidence: 0.930
  Regime:     BULL_TREND
  Entry:      2450.00   Stop: 2412.50
  Target1:    2506.25   Target2: 2562.50
  Indicators: EMA, VWAP, RSI, MACD, STOCHASTIC, BBANDS, ORB
  Timeframes: 5m, 1h
  Pattern:    CDLHAMMER

Chaos regime test: PASS — blocked at Gate 1
```

## Test results

123 unit tests, 94% coverage (non-CLI: gates 91%, engine 93%, models/explainer 100%, publisher 95%).
