# Institutional Agentic AI Intraday Trading System

Two production-grade intraday trading apps in one monorepo: App 1 trades NSE/BSE India
via Zerodha Kite Connect, App 2 trades ASX Australia via Interactive Brokers. Built
strictly module by module (M01-M23) against [`MASTER_BUILD_PROMPT_FINAL.MD`](MASTER_BUILD_PROMPT_FINAL.MD),
the single source of truth for every requirement. See [`CLAUDE.md`](CLAUDE.md) for
conventions and the full module index, and [`PROGRESS.md`](PROGRESS.md) for current
build status.

`TRADING_MODE=PAPER` is the default everywhere. `TRADING_MODE=LIVE` is never a default
and must be set explicitly alongside `LIVE_TRADING_CONFIRMED=true`.

## Current state: M06 -- Pattern Recognition Engine

What exists so far:

- **M01:** monorepo topology, Pydantic Settings v2 config (`.env` + `config.yaml`),
  structlog JSON logging, system-wide constants/exceptions/enums, the compiled Protobuf
  inter-agent message schema, the 5 Redis Lua atomic scripts, Docker Compose stack
  (Redis, TimescaleDB, Postgres+pgvector, Prometheus, Grafana, both apps), and minimal
  app entrypoints that boot config/logging and run a heartbeat loop.
- **M02:** holiday calendars with live NSE/ASX fetch + local caching + fail-closed
  fallback (`shared/session_manager.py`), the session state machine (CLOSED ->
  PRE_MARKET -> OPEN -> SNAPSHOT_WINDOW -> APPROACHING_CLOSE -> CLOSED) and SEBI
  snapshot-window flag, the ASX staggered-open ticker-group registry, the T-20min
  auto square-off scheduler, and the `@market_hours_only` decorator.
- **M03:** TimescaleDB hypertables (`ticks`, `ohlcv_1m`) with 5m/15m/1h continuous
  aggregates (real-time aggregation -- see ADR-008), the repository pattern
  (`shared/storage/repositories.py` -- all DB access goes through it), tick validation
  (out-of-sequence/corrupt/zero-price rejection), a SQLite failover buffer for RULE 5
  DB-outage handling, and a yfinance dev-only historical backfill CLI.
- **M04:** the indicator engine (`shared/indicators/`) -- an extensible registry
  (`@register_indicator`, one file per indicator under `definitions/`, zero other
  changes to add a new one) covering EMA(9,21,50,200), ADX(14), RSI(14), MACD(12,26,9),
  Stochastic(14,3), CCI(20), MFI(14), ROC(10), Williams %R(14), ATR(14), BB(20,2), OBV,
  VWAP, VWAP bands, Volume Delta, and Pivot points (Standard/Fibonacci/Camarilla) --
  pure TA-Lib + NumPy/pandas, zero LLM (RULE 4). Results cache in Redis (30s TTL).
  TA-Lib's build issue from ADR-004 is resolved (prebuilt wheel); pandas-ta is dropped
  -- see ADR-009.
- **M05:** the instrument master & corporate actions module (`shared/instruments/`) --
  canonical instrument list (symbol, exchange, lot size, tick size, ISIN) from live
  NSE/ASX feeds, corporate-action history (split/bonus/dividend/symbol-change) from a
  live NSE feed plus a checked-in manual override table for edge cases (and for ASX,
  which has no confirmed bulk corporate-actions endpoint -- see ADR-010), and a
  back-adjustment function (`shared.instruments.adjustment.adjusted_candles`) that
  downstream modules (M04/M06/M07/M08) call instead of reading raw OHLCV directly, so
  indicators/patterns/backtests/regime classification don't silently corrupt around
  ex-dates.
- **M06:** the pattern recognition engine (`shared/patterns/`) -- full TA-Lib candlestick
  pattern scan (~61 CDL* functions discovered dynamically via `dir(talib)` so future
  TA-Lib upgrades are auto-included), Opening Range Breakout (ORB) detection (first 15-minute
  range → bullish/bearish breakout), and S/R level detection via swing-pivot analysis and
  volume-at-price profiling. Multi-timeframe cross-validation (`compute_multi_timeframe`)
  identifies CDL patterns confirmed on ≥ 2 distinct timeframes (Gate 5 of the 9-gate signal
  system). All three detectors are pure Python/NumPy/TA-Lib -- zero LLM (RULE 4).

No trading/signal logic exists yet -- that starts at M11.

## Prerequisites

- Python 3.12+ (the Docker images use `python:3.12-slim`; see ADR-004 for why this
  diverges from the spec's literal "3.11-slim" suggestion)
- Docker + Docker Compose v2
- No system-level Redis/Postgres needed for local dev -- docker-compose provides them

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# Actual runtime + dev-tool subset built so far (NOT the full pyproject.toml -- see ADR-004).
# This will be superseded by `poetry install` once a working poetry.lock exists.
pip install \
  "pydantic==2.6.4" "pydantic-settings==2.2.1" "pyyaml==6.0.1" "structlog==24.1.0" \
  "redis==5.0.3" "protobuf==4.25.3" "psycopg2-binary==2.9.9" "requests==2.31.0" \
  "pandas==2.2.1" "numpy==1.26.4" "yfinance==0.2.37" "TA-Lib==0.6.8" \
  "pytest==8.1.1" "pytest-asyncio==0.23.5" "pytest-cov==4.1.0" \
  "ruff==0.3.2" "mypy==1.9.0" \
  "grpcio-tools==1.62.1" "types-protobuf==4.25.0.20240417" "types-PyYAML" \
  "types-requests" "types-psycopg2" "pandas-stubs"

cp .env.example .env   # fill in values as needed; .env is gitignored
```

## Running the apps directly (no Docker)

```bash
source .venv/bin/activate
python -m apps.india.main       # Ctrl+C to stop
python -m apps.australia.main   # Ctrl+C to stop
```

Each prints structured JSON logs: a `system_starting` event confirming
`trading_mode=PAPER`, then a `heartbeat` event every 10 seconds.

## Running the calendar/session CLI

```bash
source .venv/bin/activate
python -m shared.session_manager
```

Prints the current `SessionState` for both India and Australia (live NSE/ASX holiday
fetch, falling back to cache, failing closed with a logged error if neither is
available -- see ADR-006), plus an example ASX staggered-open ticker group lookup.
This is a cross-app diagnostic tool meant to run from the repo root with both apps'
`config.yaml` present -- it is not a per-app service entrypoint and isn't meant to run
inside a single-app Docker container (`apps/india/main.py` / `apps/australia/main.py`
are the actual per-app service entrypoints).

## Running the storage backfill CLI

```bash
source .venv/bin/activate
docker run --rm -d --name trading-test-timescale -p 5433:5432 \
    -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=trading \
    -e POSTGRES_DB=trading_ts timescale/timescaledb:2.14.0-pg16
python -m shared.storage.backfill --symbol RELIANCE.NS --days 30
```

Applies `shared/storage/schema.sql` (idempotent) then fetches and writes history via
yfinance. CAVEAT: Yahoo Finance's API was rate-limited (HTTP 429) for every ticker
tried from this build's sandboxed network -- the CLI fails gracefully (`rows=0`, no
crash) when this happens; re-verify reachability in your actual environment. See
ADR-007 for why the 30-day case requests 5-minute (not 1-minute) granularity, and
`tests/integration/timescale/test_repositories.py`'s
`test_backfill_30_days_then_query_5m_count_correct` for a synthetic-data proof of the
storage layer's own round-trip correctness, independent of yfinance's availability.

## Running the indicator engine CLI

```bash
source .venv/bin/activate
docker run --rm -d --name trading-test-timescale -p 5433:5432 \
    -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=trading \
    -e POSTGRES_DB=trading_ts timescale/timescaledb:2.14.0-pg16
docker run --rm -d --name trading-test-redis -p 6379:6379 redis:7.2.4-alpine
python -m shared.indicators --symbol RELIANCE.NS --exchange NSE --timeframe 5m
```

Queries the last `INDICATOR_LOOKBACK_CANDLES` (250) candles for the given
symbol/exchange/timeframe, computes all 16 registered indicators, caches the result in
Redis (30s TTL), and logs each indicator's values plus the compute+cache latency. If
nothing has been backfilled for that symbol yet, it reports `no_candles_found` and
exits cleanly rather than crashing -- same graceful-degradation pattern as M03's
backfill CLI. See `tests/integration/indicators/test_indicators_live.py` for the
literal M04 VERIFY command proof (synthetic data, since yfinance is rate-limited here
-- same caveat as M03).

## Running the pattern recognition CLI

```bash
source .venv/bin/activate
docker run --rm -d --name trading-test-timescale -p 5433:5432 \
    -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=trading \
    -e POSTGRES_DB=trading_ts timescale/timescaledb:2.14.0-pg16
python -m shared.patterns --symbol RELIANCE --exchange NSE --timeframe 5m
# Multi-timeframe cross-confirmation:
python -m shared.patterns --symbol RELIANCE --exchange NSE --timeframes 1m,5m,15m
```

Queries the last `SR_LOOKBACK_CANDLES` (100) candles per timeframe from TimescaleDB, runs
all three detectors (CDL scan, ORB, S/R), and logs the pattern snapshot. If no candles
have been backfilled yet it reports `no_candles_found` and exits cleanly. The multi-TF mode
additionally reports `confirmed_bullish_patterns` / `confirmed_bearish_patterns` -- CDL names
detected on ≥ 2 of the requested timeframes. See
`tests/integration/patterns/test_patterns_live.py` for the literal M06 VERIFY proof:
deterministic ORB, S/R, and CDLENGULFING assertions against real TimescaleDB with synthetic
candles whose outcomes are precisely known.

## Running the instrument master CLI

```bash
source .venv/bin/activate
docker run --rm -d --name trading-test-timescale -p 5433:5432 \
    -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=trading \
    -e POSTGRES_DB=trading_ts timescale/timescaledb:2.14.0-pg16
python -m shared.instruments --symbol RELIANCE --exchange NSE
```

Refreshes both exchanges' live instrument master and NSE's live corporate actions
(plus manual overrides), then prints the given symbol's instrument record and full
corporate-action history. A live-fetch failure for one source is logged and skipped,
not fatal -- the other refreshes and the lookup still proceed. See
`tests/integration/instruments/test_instruments_live.py` for the literal M05 VERIFY
command proof (a synthetic but realistic split, since asserting against a moving
real-world split's exact ratio would make the test non-deterministic over time) and
`tests/integration/test_instruments_live_sources.py` for live NSE/ASX reachability
checks.

## Verifying the build (exact commands)

```bash
# 1. Protobuf schema imports and round-trips correctly
python -c "from shared.proto import messages_pb2; print('OK')"

# 2. Lint -- must be clean
ruff check .
ruff format --check .

# 3. Types -- strict mode, must be clean
mypy .

# 4. Unit tests (no Docker required)
pytest

# 5. Integration tests (skip individually if their service/network isn't available)
docker run --rm -d --name trading-test-redis -p 6379:6379 redis:7.2.4-alpine
docker run --rm -d --name trading-test-timescale -p 5433:5432 \
    -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=trading \
    -e POSTGRES_DB=trading_ts timescale/timescaledb:2.14.0-pg16
pytest tests/integration/ -v
docker stop trading-test-redis trading-test-timescale

# 6. Session state machine CLI (M02 VERIFY command)
python -m shared.session_manager

# 7. Storage backfill CLI (M03 VERIFY command -- requires TimescaleDB from step 5)
python -m shared.storage.backfill --symbol RELIANCE.NS --days 30

# 8. Indicator engine CLI (M04 VERIFY command -- requires TimescaleDB+Redis from step 5)
python -m shared.indicators --symbol RELIANCE.NS --exchange NSE --timeframe 5m

# 9. Instrument master CLI (M05 VERIFY command -- requires TimescaleDB from step 5)
python -m shared.instruments --symbol RELIANCE --exchange NSE

# 10. Pattern recognition CLI (M06 VERIFY command -- requires TimescaleDB from step 5)
python -m shared.patterns --symbol RELIANCE --exchange NSE --timeframe 5m

# 11. Full stack
docker build -f infra/docker/Dockerfile.base -t trading-system-base:dev .
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps     # all should be Up/healthy
curl http://localhost:9090/-/healthy              # Prometheus
curl http://localhost:3000/api/health              # Grafana
docker compose -f infra/docker-compose.yml down
```

Expected: 363 tests total -- 361 passing + 2 skipped (ASX holiday endpoint, yfinance
rate-limited) when Redis/TimescaleDB are both reachable; 318 passing + 2 skipped when
only unit tests run (no services needed). 97% coverage on `shared/` + `apps/`, ruff and
mypy both clean (133 files), all 7 compose services reach Up/healthy.

Last verified: 2026-07-01 against commit 227f76c (full M01–M06 validation pass).

## Environment variables

See [`.env.example`](.env.example) at the repo root for the full list, grouped by the
module that owns each variable. Only the M01 section
(`APP_ID`/`ENVIRONMENT`/`LOG_LEVEL`/`TRADING_MODE`/`LIVE_TRADING_CONFIRMED`/`REDIS_URL`/
`POSTGRES_DSN`/`TIMESCALE_DSN`) is actually read by code today; the rest documents
future modules' variables for discoverability. M02-M06 introduced no new env vars.

## Known follow-ups (tracked in PROGRESS.md / ARCHITECTURE_DECISIONS.md)

- `poetry.lock` not yet generated -- `infra/docker/Dockerfile.base` currently installs
  a minimal pinned subset via direct `pip install`, not the full `pyproject.toml`
  manifest, after three pin-drift/toolchain build failures during M01 (see ADR-004).
  `Dockerfile.base` does not yet include TA-Lib/numpy/pandas -- the app containers
  don't import `shared.indicators` yet (that starts at M11); add them there when a
  containerized service first needs the indicator engine.
- ASX's real holiday-calendar API endpoint is unconfirmed (current implementation
  404s) -- `SessionStateMachine` for Australia will raise `CalendarUnavailableError`
  on every weekday until this is fixed. This is a known, visible, fail-closed
  limitation (see ADR-006), not a silent gap. NSE's live fetch is confirmed working.
- Yahoo Finance's API is rate-limited (HTTP 429) from this build's sandboxed network
  for every ticker tried, not just NSE symbols -- the backfill CLI degrades gracefully
  (`rows=0`) rather than crashing; re-verify reachability in your actual deployment
  environment before relying on it.
- `pandas-ta` is dropped (was pinned 0.4.71b0 in M01) -- its only PyPI releases force
  numpy>=2.2.6/pandas>=2.3.2, breaking the already-verified M01-M03 stack; every
  required indicator is covered by TA-Lib (now resolved via prebuilt wheel, see
  ADR-009) or hand-implemented NumPy/pandas instead.
- Volume Delta (`shared/indicators/definitions/volume_delta.py`) is a candle-direction
  proxy (signed volume by close-vs-open), not true tick-level aggressor-side volume --
  the `ticks` table has bid/ask but no trade-direction flag yet (would need M16).
- No reliable bulk ASX corporate-actions endpoint was found reachable from this build's
  sandbox after trying several plausible URLs -- ASX split/bonus/dividend data relies
  entirely on the manual override table (`shared/instruments/manual_overrides.yaml`)
  for now. NSE's instrument master and corporate-actions feeds are both confirmed
  live and working (real splits/bonuses/dividends fetched and parsed correctly). See
  ADR-010.
- The adjustment engine (`shared/instruments/adjustment.py`) only price-adjusts
  SPLIT/BONUS actions. DIVIDEND and SYMBOL_CHANGE are recorded but not applied --
  a correct dividend (total-return) adjustment needs point-in-time price data this
  function deliberately doesn't fetch; symbol-change history-stitching has no
  downstream consumer yet. See ADR-010.
- S/R strength is touch-count based (normalised 0–1), not volume-weighted. A future
  enhancement could multiply touch count by accumulated volume at the level for richer
  zone significance, but this requires per-instrument volume normalisation to compare
  across symbols; deferred until M11 (signal engine) proves it's needed for Gate 6.
- `Volume Delta` in M04 and `CDL` scan in M06 both benefit from tick-level aggressor-side
  data (bid/ask and trade direction), which M16 (data ingestion) will provide. Both modules
  degrade gracefully on OHLCV-only data today.
