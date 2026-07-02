# CLAUDE.md

> **Before doing anything in a new session: read this file, then PROGRESS.md, then
> ARCHITECTURE_DECISIONS.md, then check `git log --oneline -20`, before touching any code.**

The single source of truth for every requirement, rule, and module spec is
[`MASTER_BUILD_PROMPT_FINAL.MD`](MASTER_BUILD_PROMPT_FINAL.MD) at the repo root. This file is a
**navigation aid and convention summary**, not a replacement — when in doubt, re-read the spec
directly rather than trusting a paraphrase below, since paraphrases can drift out of sync. Do not
rename or edit `MASTER_BUILD_PROMPT_FINAL.MD`.

## Project

An institutional-grade Agentic AI intraday trading system built as two independently deployable
apps in one monorepo: App 1 trades NSE/BSE India via Zerodha Kite Connect, and App 2 trades ASX
Australia via Interactive Brokers TWS. Both share a common core (config, indicators, risk engine,
execution, compliance, orchestration) and are built strictly module by module (M01–M23), with
every module standalone-runnable, tested, linted, and committed before the next one starts.

## The Ten Golden Rules

(Copied verbatim from `MASTER_BUILD_PROMPT_FINAL.MD` — see that file for full detail under each.)

### RULE 1: COMPLIANCE FIRST
- No live order without a SEBI-compliant Strategy-ID tag or authorized Generic Algo ID (India, mandatory from April 1, 2026).
- No system deployment without a tiered Kill Switch (Australia — required under current ASIC automated-trading obligations today; CP 386 would extend this to algorithm-level controls, proposed commencement April 2027 — build the stricter tiered version regardless).
- Paper trading is ALWAYS default — live requires `TRADING_MODE=LIVE` AND `LIVE_TRADING_CONFIRMED=true`.

### RULE 2: DISCIPLINED INACTION
- System MUST REFUSE all trades if market regime = `HIGH_VOL_CHAOS`.
- System MUST REFUSE trades if order flow shows institutional absorption at target level.
- Refusing to trade is a high-value decision. Protection of capital overrides volume.

### RULE 3: PERFORMANCE ATOMICITY
- ALL state-changing operations use Redis Lua scripts (atomic, no race conditions).
- Position entry + SL linkage + margin deduction = single Lua transaction (`sl_linkage.lua`).
- Race conditions in a trading system = real financial loss. Atomicity is non-negotiable.

### RULE 4: HOT PATH IS ZERO LLM
- Signal decision: pure Python < 100ms, never waits for LLM.
- LLM explains AFTER decision, asynchronously, never blocks order flow.
- 90% of system operations use zero LLM calls.
- LLM cost target: < $1/day total.

### RULE 5: SRE RESILIENCE & DEGRADED STATE POLICY
- WebSocket drop → Fallback to REST polling within 2 seconds.
- DEGRADED STATE RULE: during REST fallback, system enters `DEGRADED_EXIT_ONLY` — new entries
  blocked, exits/trailing stops still managed, until primary WebSocket recovers.
- Redis failure → in-memory state, cease new entries, manage exits only.
- DB failure → append to local SQLite buffer (`shared/data/buffer.db`), sync on recovery.
- Total instance/AZ loss — out of scope for in-process buffering. Accepted DR posture must be
  recorded explicitly in `ARCHITECTURE_DECISIONS.md` (see open item tracked there).

### RULE 6: REALIZABLE ALPHA ONLY
- Backtester uses slippage distribution model (log-normal fit to actual fill data), NOT mid-price fills.
- Slippage parameterized by time-of-day bucket AND bid-ask spread width at signal time.
- Track markout curves in production (T+1s, T+1m, T+5m post-fill).
- Paper trading validation minimum: 20 trading days, Sharpe > 1.5, win rate > 50%, max drawdown < 5%.
- A retrained model (weekly MLflow pipeline) must independently clear this same 20-day gate
  before replacing the live model. No silent auto-promotion.

### RULE 7: NO TRADE WITHOUT STOP-LOSS
- Rejected at execution engine layer — hard block, not a warning, not a log.
- `NoStopLossError` raised before any broker API call is made.
- SL order linked atomically in Redis at entry time (`sl_linkage.lua`).

### RULE 8: DAILY LOSS CIRCUIT BREAKER & PRIORITY LANE
- Cannot be disabled in `TRADING_MODE=LIVE` — ever.
- Triggers autonomous Kill Switch at -2% daily P&L.
- Sequence: cancel ALL open orders → execute emergency exit → set `SYSTEM_HALTED` in Redis → Telegram alert.
- Priority Lane: emergency liquidations, manual `/kill`, and SL orders bypass the 10 OPS rate limiter.
- `is_priority=true` is settable **only** by kill-switch and SL-exit code paths — never exposed
  to signal/entry code, the API layer, or any user-facing control.

### RULE 9: BUILD ONE MODULE AT A TIME
- Fully complete, tested, linted before starting next.
- Every module: standalone runnable (`python -m module`), pytest green, ruff clean, mypy clean.
- Every key decision: recorded in `ARCHITECTURE_DECISIONS.md`.
- Module IDs unique and sequential M01–M23. No two modules ever share an ID.

### RULE 10: ASK, NEVER ASSUME (on compliance or risk)
- If ambiguous on compliance or risk: ask ONE specific question.
- Apply professional best-practice defaults elsewhere and state reasoning explicitly.
- Treat regulatory citations as provisional until cross-checked against live circular/rule text.

## Module list (M01–M23, fixed build order)

| ID | Module | One-line description |
|---|---|---|
| M01 | Project Scaffold & Config | Monorepo topology, Pydantic Settings, structlog, pyproject.toml, Docker Compose stack, Protobuf compile, Lua scripts, ADR template |
| M02 | Market Calendar & Session Manager | NSE/ASX holiday calendars, session state machine, snapshot window flag, staggered ASX open registry |
| M03 | High-Throughput Buffering & Storage | TimescaleDB hypertables, continuous aggregates, SQLite failover buffer, yfinance backfill, repository pattern |
| M04 | Core Technical Indicator Engine | Extensible indicator registry, TA-Lib/pandas-ta/NumPy, multi-timeframe, Redis-cached |
| M05 | Instrument Master & Corporate Actions | Canonical instrument list + split/bonus/dividend adjusted price series feeding all downstream modules |
| M06 | Pattern Recognition Engine | Candlestick patterns, ORB detection, S/R levels, multi-timeframe validation |
| M07 | Backtesting Engine | vectorbt + log-normal slippage model, markout analyzer, model-promotion gate (RULE 6) |
| M08 | Market Regime Classifier | Random Forest + HMM, 4 regimes, MLflow versioning, promotion gated by M07 |
| M09 | Stock Universe Filter | Alpha scoring Σ, compliance exclusion list, regime-aware β weights, watchlist output |
| M10 | Sentiment & News Agent | RSS scraping, batched Groq sentiment calls, GPTCache semantic dedup, FII/DII/VIX feeds |
| M11 | Signal Generation Agent | 9-gate signal system, pure Python < 100ms, async LLM explain only |
| M12 | Risk & Position Sizing Engine | ATR-based SL, 3-5-7 rule, regime/snapshot sizing, correlation guard, circuit breaker |
| M13 | Compliance & Regulatory Engine | SEBI Strategy-ID/MPP/Generic Algo ID, ASIC tiered kill-switch wiring — built before M14 |
| M14 | Order Execution Engine | Broker adapters (Paper/Kite/IBKR), idempotency via client_order_id, partial-fill recompute |
| M15 | Authentication & Token Manager | Kite TOTP auto-login, Redis token store, IBKR TWS connection pool, TLS everywhere |
| M16 | Data Ingestion Agent | WebSocket tick subscription, NumPy aggregator, ASX staggered open handler, yfinance fallback |
| M17 | Reconciliation Agent | Periodic broker-vs-internal-state diff, ReconciliationMismatch events, blocks entries until cleared |
| M18 | Agent Orchestrator (LangGraph) | State graph wiring, ACT-R memory tiers, HITL interrupt, kill-switch preemption |
| M19 | Real-Time Monitor Agent | P&L tracker, heartbeat checker (Tier 3 kill switch), Prometheus/Grafana |
| M20 | Alerting & Notification | Telegram bot, daily PDF email, LLM cost alert |
| M21 | Reporting Module | Daily/monthly PDF+HTML reports, markout curves, trade-by-trade CSV/Excel |
| M22 | Dashboard & API | FastAPI REST + WebSocket, Streamlit operational UI |
| M23 | Docker & Cloud Deployment | Multi-stage Dockerfiles, AWS deploy scripts, CI/CD, Locust load tests, DR posture documented |

## Current build state (updated 2026-07-02)

**Last completed module:** M13 — Compliance & Regulatory Engine
**Next module to build:** M14 — Order Execution Engine

Verified clean as of this date: 1140 unit tests passing (68 skipped: integration tests requiring
live TimescaleDB/Redis), ruff clean, mypy --strict clean. 163 new M13 unit tests all pass.

**M01–M08 independent audit completed 2026-07-01** (commit 1c55be6). All findings resolved:
- `promote_classifier(backtest_metrics: BacktestMetrics)` — `Any` removed (was S2)
- `list_model_versions()` logs `mlflow_list_versions_failed` warning on exception (was S1)
- 5 DB CLIs catch `psycopg2.OperationalError` and log `db_connection_failed` (was Q1)
- ASX open-time function renamed to `get_ticker_open_time` (was G5; old name was wrong)
- ADR-013 (M08 design) and ADR-014 (scheduling deferred to M18) added
- README.md created for all M01–M08 modules

**M09 notes:**
- `structlog.PrintLoggerFactory(file=sys.stdout)` → `PrintLoggerFactory()` in
  `shared/core/logging.py` — fixes capsys/stdout closed-file crash (ADR-015).
- Compliance source fails-open (empty exclusion set) if NSE API unreachable.

**M10 notes:**
- SentScore now live — `MarketSentiment.aggregate_score` feeds M11 Gate 8.
- GPTCache: embedding-only path (gptcache.Onnx + NumPy cosine + Redis list) — ADR-016.
- litellm at module level; mypy `follow_imports = "skip"` for litellm — ADR-017.
- India VIX + FII/DII scrapers fail-open (return None on network failure).
- `*.md` excluded from ruff E501 (pre-existing across M01-M09, not M10-specific).

**Known API names (use these exactly, not summary paraphrases):**
- Config live-trading check: `settings.is_live_trading_enabled` (not `is_live_trading_active`)
- SQLite failover buffer: `SQLiteFailoverBuffer` (not `SQLiteBuffer`)
- Tick validation: `TickSequenceValidator` (not `validate_tick`)
- Indicator registry: `all_indicators()` (not `get_registry()`)
- Continuous aggregates: named `ohlcv_5m`, `ohlcv_15m`, `ohlcv_1h` (not `cagg_ohlcv_*`)
- Backtest storage: `apply_backtest_schema()`, `save_result()`, `load_result()`
- Slippage model: `sample_slippage_bps(signal_time, spread_bps, rng)` — `shared/backtesting/slippage.py`
- Promotion gate: `check_promotion_gate(metrics)` → list of failure strings (empty = pass)
- EMA strategy: `ema_crossover_signals(candles)`, `run_backtest(config, candles, entries, exits)`
- Walk-forward: `run_walk_forward(config, candles, signal_fn, param_grid)`
- Regime classifier: `RegimeClassifier.fit(x_train, y)`, `.classify(features)` → `RegimeClassification`
- Feature extraction: `extract_features(candles, vix)` → `RegimeFeatures` — `shared/regime/features.py`
- Regime publisher: `publish_regime_change(classification, redis_client)` → entry_id str
- MLflow registry: `save_classifier(clf, metrics)`, `load_classifier(run_id)`, `promote_classifier(run_id, metrics)`
- Regime enum: `MarketRegime` — BULL_TREND, BEAR_TREND, MEAN_REVERTING, HIGH_VOL_CHAOS
- Redis stream key: `REGIME_REDIS_STREAM = "regime:changes"` — `RegimeChanged` proto payload
- ASX staggered open: `get_ticker_open_time(symbol, market_date, tz)` — `shared/session_manager.py`
- Universe filter: `run_universe_filter(instruments, candles_by_symbol, regime, exclusion_list)`
- Alpha scoring: `score_stock(close, high, low, volume, regime)` → `AlphaComponents`
- Composite score: `compute_composite(components, weights)` — `shared/universe/scoring.py`
- Regime β-weights: `BETA_WEIGHTS` dict — `MarketRegime` → `AlphaWeights`
- Universe store: `store_watchlist(entries, conn, redis_client)` — TimescaleDB + Redis
- Universe load: `load_watchlist(exchange, conn, redis_client, top_n)` → `list[WatchlistEntry]`
- Universe schema: `apply_universe_schema(conn)` — `watchlist_history` hypertable
- Compliance: `NSEComplianceSource().fetch()` → `ComplianceExclusionList`
- Redis watchlist key: `universe:watchlist:<EXCHANGE>` — 8-hour TTL
- Sentiment agent: `SentimentAgent(model, api_key, redis_client, embedding_model).run(exchange, custom_headlines)` → `MarketSentiment`
- Sentiment models: `Headline`, `SentimentScore`, `FIIDIIData`, `VIXData`, `MarketSentiment` — `shared/sentiment/models.py`
- Sentiment scorer: `score_headlines_batch(headlines, model, api_key)` → `(list[SentimentScore], int)` — `shared/sentiment/scorer.py`
- Sentiment cache: `SentimentCache(redis_client, model_version, embedding_model)` — `.get(text)`, `.put(text, score)` — `shared/sentiment/cache.py`
- Sentiment feeds: `fetch_all_feeds(exchange, max_age_hours)` → `list[Headline]` — `shared/sentiment/feeds.py`
- Market indicators: `fetch_india_vix()` → `VIXData | None`, `fetch_fii_dii()` → `FIIDIIData | None` — `shared/sentiment/market_indicators.py`
- Sentiment cost: `CostTracker(redis_client).record(model, input_tokens, output_tokens)` — `shared/sentiment/cost_tracker.py`
- Sentiment cache key: `sentiment:cache:<model_version>` — 24-hour TTL
- Sentiment cost key: `sentiment:cost:daily:<YYYYMMDD>`
- Default sentiment model: `SENTIMENT_DEFAULT_MODEL = "groq/llama-3.1-8b-instant"` — `shared/core/constants.py`

**M11 notes:**
- 9-gate pure Python evaluation < 100ms. Gates 1-7, 9 terminate on fail; Gate 8 modulates confidence only.
- Gate 1: HIGH_VOL_CHAOS → hard fail (RULE 2). BULL_TREND blocks SHORT; BEAR_TREND blocks LONG.
- Gate 9: threshold 0.70 normal, 0.80 in SEBI snapshot window (14:45-15:30 IST).
- Atomic Lua dedup: checks `system:status:halted` + dedup key before publishing to stream.
- LLM explain: Groq 70B, async after publish, max 200 tokens, silent fail.

**M11 API names:**
- Signal engine: `SignalEngine().evaluate(ctx)` → `SignalResult` — `shared/signals/engine.py`
- Signal models: `SignalContext`, `SignalResult`, `GateResult`, `SignalDirection` — `shared/signals/models.py`
- Signal publisher: `SignalPublisher(redis_client).publish(result)` → `str | None` — `shared/signals/publisher.py`
- Signal explainer: `explain_signal(result, model, api_key)` (async) → `str` — `shared/signals/explainer.py`
- Signal stream key: `SIGNAL_REDIS_STREAM = "signals:generated"` — `shared/core/constants.py`
- Signal expiry: `SIGNAL_EXPIRY_MINUTES = 5` — dedup window: `SIGNAL_DEDUP_WINDOW_SECONDS = 60`
- Signal explain model: `SIGNAL_EXPLAIN_MODEL = "groq/llama-3.1-70b-versatile"`
- Dedup Lua: `shared/lua/signal_dedup.lua` — returns `{1, "PUBLISHED", entry_id}` / `{0, "HALTED"}` / `{0, "DUPLICATE"}`

**M12 API names:**
- Risk engine: `RiskEngine().evaluate(entry_price, stop_loss, params)` → `RiskDecision`
- Risk models: `RiskParameters`, `RiskDecision`, `RiskCheck`, `OpenPosition`, `PositionSize` — `shared/risk/models.py`
- Sizing: `compute_atr_position_size(capital, entry, sl, base_pct, regime_mult, snapshot)` → `PositionSize`
- Kelly sizing: `compute_kelly_position_size(capital, entry, sl, win_rate, ratio, regime_mult, snapshot)` → `PositionSize`
- Correlation guard: `check_correlation_guard(proposed_returns, open_positions)` → `RiskCheck`
- Circuit breaker: `check_circuit_breaker(daily_pnl, capital, halted)` → `RiskCheck`
- Redis halted key: `RISK_HALTED_REDIS_KEY = "system:status:halted"` — caller reads, M18 writes
- Kelly off by default; `use_kelly=True` requires paper-trading validation (RULE 6)
- 3-5-7 Rule: 3% per-trade, 5% per-sector, 7% portfolio heat — all enforced as hard blocks

**M13 API names:**
- Compliance engine: `ComplianceEngine().check(order, now_ist, now_aest, ...)` → `ComplianceDecision`
- Order model: `OrderIntent` — `shared/compliance/models.py` (imported by M14)
- Output models: `ComplianceDecision`, `TaggedOrder`, `ComplianceViolation` — `shared/compliance/models.py`
- Strategy registry: `StrategyRegistry(use_generic)` — `.resolve(strategy_name)` → `str | None`
- Strategy tags: `STRAT001`–`STRAT005` for the 5 registered strategies; `GENALG01` for generic
- Kill switch: `KillSwitchManager(redis_client).trigger_tier1/2/3(...)` → `KillSwitchEvent`
- `KillSwitchEvent.is_priority` is always `True` and only set by `KillSwitchManager` — RULE 8
- Kill switch Redis keys: `KILL_SWITCH_HALTED_KEY`, `KILL_SWITCH_TIER_KEY`, `KILL_SWITCH_REASON_KEY`
- India checks: `run_india_checks(order, strategy_tag, now_ist)` → `(violations, eff_type, mpp_price)`
- Australia checks: `run_australia_checks(order, recent, pending, short_list, now_ms, ...)` → violations
- MPP price: `compute_mpp_price(order)` — buy: LTP×1.0025, sell: LTP×0.9975
- Audit log: `log_compliance_pass(...)`, `log_compliance_rejection(...)`, `log_kill_switch(event)`
- PAPER exchange always passes compliance (simulation mode)
- M14 reads `KILL_SWITCH_HALTED_KEY` before every broker submission

## Tech stack summary

Python 3.12 (Docker images use `python:3.12-slim` — see ADR-004; spec says 3.11+ and 3.12
satisfies that). FastAPI, Pydantic Settings v2, structlog (JSON). TimescaleDB + PostgreSQL
(pgvector) + Redis (Lua scripts, Streams) + SQLite failover buffer. Protobuf for all inter-agent
messages. kiteconnect (App1) / ibapi (App2) broker SDKs; yfinance for dev backfill only, never
live signals. TA-Lib (prebuilt wheel 0.6.8, ADR-009) + NumPy/pandas for indicators — **pandas-ta
is DROPPED** (numpy/pandas version conflict, ADR-009; all required indicators are covered by
TA-Lib or hand-implemented NumPy). scikit-learn + HMM + XGBoost + TensorFlow + Prophet for ML,
versioned via MLflow. vectorbt for backtesting. LangGraph + LangChain for agent orchestration;
LiteLLM for tiered model routing (Groq 8B/70B + Claude Sonnet 4.6 / Haiku 4.5); GPTCache for
semantic dedup. Docker Compose for local/staging, GitHub Actions CI/CD, Prometheus + Grafana for
observability, Telegram for alerting. Full version pins and rationale: see the `pyproject.toml`
block in `MASTER_BUILD_PROMPT_FINAL.MD`.

## Durable coding conventions

- Strict MyPy (no `Any`) and Ruff (line length 88) clean on every module before it's marked complete.
- structlog everywhere — never `print()`. JSON structured, secrets never logged.
- Zero magic numbers outside `constants.py` — every constant has an explanation comment.
- Google-style docstrings on every class and public method.
- `client_order_id` is mandatory on every `OrderIntent` from M14 onward; on timeout/ambiguous
  broker response, query the broker order book by that ID before any retry — never blind-retry.
- `is_priority=true` on the rate limiter is settable **only** by kill-switch and SL-exit code
  paths. When building M11–M14 and M18, name the exact functions allowed to set it and treat any
  other caller as a bug.
- TLS required on all Redis, Postgres, and broker API connections.
- `TRADING_MODE=PAPER` is the default everywhere; `TRADING_MODE=LIVE` only on explicit instruction.
- Every module: standalone runnable (`python -m module_name`), own README.md with usage/env
  vars/example output.
- One module at a time, full stop after each — never start the next module in the same turn.
- If the same build/test error recurs more than twice, stop and explain the root cause before a
  third attempt.
