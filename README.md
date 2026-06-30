# Institutional Agentic AI Intraday Trading System

Two production-grade intraday trading apps in one monorepo: App 1 trades NSE/BSE India
via Zerodha Kite Connect, App 2 trades ASX Australia via Interactive Brokers. Built
strictly module by module (M01-M23) against [`MASTER_BUILD_PROMPT_FINAL.MD`](MASTER_BUILD_PROMPT_FINAL.MD),
the single source of truth for every requirement. See [`CLAUDE.md`](CLAUDE.md) for
conventions and the full module index, and [`PROGRESS.md`](PROGRESS.md) for current
build status.

`TRADING_MODE=PAPER` is the default everywhere. `TRADING_MODE=LIVE` is never a default
and must be set explicitly alongside `LIVE_TRADING_CONFIRMED=true`.

## Current state: M02 -- Market Calendar & Session Manager

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
  "pytest==8.1.1" "pytest-asyncio==0.23.5" "pytest-cov==4.1.0" \
  "ruff==0.3.2" "mypy==1.9.0" \
  "grpcio-tools==1.62.1" "types-protobuf==4.25.0.20240417" "types-PyYAML" "types-requests"

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

# 5. Lua script atomicity + holiday-source live-network tests (some skip without
#    Redis / network access -- see output for which)
docker run --rm -d --name trading-test-redis -p 6379:6379 redis:7.2.4-alpine
pytest tests/integration/ -v
docker stop trading-test-redis

# 6. Session state machine CLI (M02 VERIFY command)
python -m shared.session_manager

# 7. Full stack
docker build -f infra/docker/Dockerfile.base -t trading-system-base:dev .
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps     # all should be Up/healthy
curl http://localhost:9090/-/healthy              # Prometheus
curl http://localhost:3000/api/health              # Grafana
docker compose -f infra/docker-compose.yml down
```

Expected: 144 tests passing (143 without Redis/network, with 1-2 skipping depending on
what's reachable), 98% coverage on `shared/` + `apps/`, ruff and mypy both clean, all 7
compose services reach Up/healthy.

## Environment variables

See [`.env.example`](.env.example) at the repo root for the full list, grouped by the
module that owns each variable. Only the M01 section
(`APP_ID`/`ENVIRONMENT`/`LOG_LEVEL`/`TRADING_MODE`/`LIVE_TRADING_CONFIRMED`/`REDIS_URL`/
`POSTGRES_DSN`/`TIMESCALE_DSN`) is actually read by code today; the rest documents
future modules' variables for discoverability. M02 introduced no new env vars -- its
config (`pre_market_local`, `snapshot_window_start_local`, etc.) lives in each app's
`config.yaml`, not `.env`, since it's static and non-secret.

## Known follow-ups (tracked in PROGRESS.md / ARCHITECTURE_DECISIONS.md)

- `poetry.lock` not yet generated -- `infra/docker/Dockerfile.base` currently installs
  a minimal pinned subset via direct `pip install`, not the full `pyproject.toml`
  manifest, after three pin-drift/toolchain build failures during M01 (see ADR-004).
- TA-Lib C library compilation needs a real fix when M04 (indicator engine) is built --
  the spec's suggested 0.4.0 source build fails to link against modern GCC.
- ASX's real holiday-calendar API endpoint is unconfirmed (current implementation
  404s) -- `SessionStateMachine` for Australia will raise `CalendarUnavailableError`
  on every weekday until this is fixed. This is a known, visible, fail-closed
  limitation (see ADR-006), not a silent gap. NSE's live fetch is confirmed working.
