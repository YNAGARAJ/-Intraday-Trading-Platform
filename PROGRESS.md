# Build Progress Log

> Source of truth for build state across sessions. At the start of any new session, read this
> file (after `CLAUDE.md`) to identify the last "complete" module and the next "not started"
> module, then cross-check against `git log --oneline -20` before resuming work.

| Module ID | Module Name | Status | Date completed | Test results summary | Known issues / follow-ups |
|---|---|---|---|---|---|
| M01 | Project Scaffold & Config | complete | 2026-06-30 | 64 tests passing (11 Redis-integration + 53 unit), 99% coverage on shared/+apps/, ruff clean, mypy --strict clean, docker-compose up: all 7 services Up/healthy | poetry.lock not yet generated -- Dockerfile.base installs a minimal pip subset, not full pyproject.toml (ADR-004); pandas-ta repinned 0.3.14b0->0.4.71b0 (original pin missing from PyPI); TA-Lib C source build fails against modern GCC, deferred to M04; env vars introduced: APP_ID, ENVIRONMENT, LOG_LEVEL, TRADING_MODE, LIVE_TRADING_CONFIRMED, REDIS_URL, POSTGRES_DSN, TIMESCALE_DSN |
| M02 | Market Calendar & Session Manager | complete | 2026-06-30 | 144 tests passing (1-2 skipped depending on network/Redis availability), 98% coverage on shared/session_manager.py, ruff clean, mypy --strict clean, docker-compose up: all 7 services Up/healthy, both per-app containers verified post-change | ASX holiday endpoint unconfirmed (404) -- Australia raises CalendarUnavailableError on weekdays until fixed (ADR-006), fails closed by design, not silent; NSE live fetch confirmed working; fixed a structlog cache_logger_on_first_use bug found via this module's own tests (logging.py); RegionConfig gained pre_market_local + snapshot_window_start_local fields; no new env vars |
| M03 | High-Throughput Buffering & Storage | complete | 2026-06-30 | 189 tests passing (2 skipped: ASX holiday endpoint, yfinance rate-limited), 99% coverage on shared/+apps/, 100% on shared/storage/, ruff clean, mypy --strict clean, docker-compose up: all 7 services Up/healthy, schema verified idempotent against both standalone and compose-managed TimescaleDB | ohlcv_1m stores finest-available granularity not strictly 1-min bars (ADR-007); continuous aggregates need materialized_only=false for real-time aggregation -- found via live testing, not assumed (ADR-008); yfinance/Yahoo Finance rate-limited (HTTP 429) from this sandbox for any ticker, same pattern as M02's NSE/ASX -- backfill CLI verified to fail gracefully (rows=0, no crash); SQLite failover buffer at shared/data/buffer.db (gitignored); new env var: none (TIMESCALE_DSN already existed from M01) |
| M04 | Core Technical Indicator Engine | not started | | | |
| M05 | Instrument Master & Corporate Actions | not started | | | |
| M06 | Pattern Recognition Engine | not started | | | |
| M07 | Backtesting Engine | not started | | | |
| M08 | Market Regime Classifier | not started | | | |
| M09 | Stock Universe Filter | not started | | | |
| M10 | Sentiment & News Agent | not started | | | |
| M11 | Signal Generation Agent | not started | | | |
| M12 | Risk & Position Sizing Engine | not started | | | |
| M13 | Compliance & Regulatory Engine | not started | | | |
| M14 | Order Execution Engine | not started | | | |
| M15 | Authentication & Token Manager | not started | | | |
| M16 | Data Ingestion Agent | not started | | | |
| M17 | Reconciliation Agent | not started | | | |
| M18 | Agent Orchestrator (LangGraph) | not started | | | |
| M19 | Real-Time Monitor Agent | not started | | | |
| M20 | Alerting & Notification | not started | | | |
| M21 | Reporting Module | not started | | | |
| M22 | Dashboard & API | not started | | | |
| M23 | Docker & Cloud Deployment | not started | | | |
