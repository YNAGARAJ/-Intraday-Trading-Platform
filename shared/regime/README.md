# M08 — Market Regime Classifier

Random Forest + Hidden Markov Model (HMM) ensemble that classifies the current market into one of four regimes: `BULL_TREND`, `BEAR_TREND`, `MEAN_REVERTING`, `HIGH_VOL_CHAOS`. RULE 2 hard override: VIX > 25 or ATR spike always returns `HIGH_VOL_CHAOS` before any model inference. Results published to Redis Streams and versioned in MLflow.

## Standalone usage

```bash
# Rule-based classification (no MLflow needed)
APP_ID=india python -m shared.regime \
    --symbol NIFTY50 --exchange NSE --vix 18.5 --lookback-days 5

# With fitted MLflow model
APP_ID=india python -m shared.regime \
    --symbol NIFTY50 --exchange NSE --vix 18.5 \
    --run-id <mlflow_run_id> --publish

# Dry run (no DB — rule-based only)
python -m shared.regime --no-db
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ID` | required | `india` or `australia` |
| `TIMESCALE_DSN` | `postgresql://trading:trading@localhost:5433/trading_ts` | TimescaleDB |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis (required with `--publish`) |
| `MLFLOW_TRACKING_URI` | `http://localhost:5000` | MLflow server |

## Key APIs

- `RegimeClassifier.fit(x_train, y)` — train RF + HMM ensemble
- `RegimeClassifier.classify(features)` → `RegimeClassification`
- `extract_features(candles, vix)` → `RegimeFeatures` — 8 features
- `publish_regime_change(classification, redis_client)` → `entry_id` — Redis Streams
- `save_classifier(clf, metrics, tags)` → `run_id` — MLflow
- `load_classifier(run_id)` → `RegimeClassifier` — MLflow
- `promote_classifier(run_id, backtest_metrics)` → `list[str]` — RULE 6 gate

## RULE 2 enforcement

`HIGH_VOL_CHAOS` is returned with `confidence=1.0` when `vix > 25.0` (strict) OR `atr_spike is True`. This check runs before the RF/HMM — no model needed (ADR-013).

## Redis stream

Key: `regime:changes` · Payload: `RegimeChanged` protobuf · Read via `read_latest_regime(redis_client)`

## Example output

```
{"symbol": "NIFTY50", "regime": "BULL_TREND", "confidence": 0.82,
 "adx": 31.4, "rsi": 62.1, "vix": 18.5, "atr_spike": false,
 "event": "regime_classification_result", "level": "info"}
```
