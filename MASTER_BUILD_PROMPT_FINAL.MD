# MASTER BUILD PROMPT — ZERO-GAP PRODUCTION SPECIFICATION (REVISION 2)
# Institutional Agentic AI Intraday Trading System
# NSE India (App 1) + ASX Australia (App 2) — Production Grade
#
# READ THIS ENTIRE PROMPT BEFORE WRITING A SINGLE LINE OF CODE.
# Build ONE module at a time. Stop after each. Confirm before proceeding.

---

## REVISION 2 — CHANGE LOG (what was fixed vs. the prior draft, and why)

1. **Module numbering rebuilt M01–M23, no duplicates, no gaps.** Prior draft reused M03 and M04 for two different modules each, and never defined M05/M06. Renumbered strictly in build order (see Build Phases section).
2. **Two new modules added**, both real gaps with no owner in the prior draft:
   - `M05 · Instrument Master & Corporate Actions` — without adjusted price series across splits/bonuses/symbol changes, ATR, indicators, and regime classification silently corrupt around ex-dates.
   - `M17 · Reconciliation Agent` — periodically diffs Redis/Postgres internal state against the broker's actual positions/orders; without it, a crash mid-fill or a partial fill can desync internal state from reality with no detection.
3. **ASIC CP 386 reframed.** It is a *consultation paper* (submissions closed Oct 2025), with final rules targeted for release by 31 March 2026 and **proposed commencement April 2027** — it is not yet a binding mandate. The tiered kill switch remains mandatory in this spec as engineering best practice and is *also* required today under existing ASIC automated-trading kill-switch obligations for market participants — but do not cite CP 386 as currently-in-force law. Re-verify the finalized rule text before ASX live deployment.
4. **SEBI "10 OPS" reframed.** Public guidance describes 10 orders/sec as the *threshold above which separate algo/strategy registration is required* — not itself a SEBI-mandated hard ceiling on order rate. The 10 OPS self-throttle in this system is a deliberate safety margin to stay under that registration trigger, not a literal regulatory cap. Worded accordingly below.
5. **SEBI "Market Order Prohibition" marked unverified.** Public summaries of the April 2026 framework emphasize Algo-ID tagging, static IP whitelisting, and 2FA — a blanket market-order ban was not independently confirmed. Keep the Market Price Protection (MPP) conversion logic (it's good execution-quality practice regardless), but confirm the prohibition itself against the actual NSE/SEBI circular text or your broker's compliance desk before treating it as a hard legal block in audit documentation.
6. **LLM model IDs unified.** Prior draft mixed a stale identifier (`claude-sonnet-4-20250514`) in Option A with current identifiers in Option B. Standardized on `claude-sonnet-4-6` (and `claude-haiku-4-5-20251001`) throughout.
7. **Idempotency requirement added to Order Execution Engine** — broker retries must carry a client-order-ID and check the broker's order book before resubmitting, to prevent duplicate live fills on a timed-out-but-actually-successful request.
8. **Access control added on `is_priority`** — the rate-limiter bypass flag must only be settable by kill-switch/SL-exit code paths, never by general application/signal code, or it becomes a compliance-bypass vector.
9. **Model-promotion gate added** — a newly-retrained model (weekly MLflow pipeline) must clear shadow/paper validation before replacing the currently-live model; no silent auto-promotion.
10. **TLS requirement added** for Redis, Postgres, and broker API connections (transport encryption was unstated; only "secrets never logged" was specified before).
11. **DR posture requirement added** — explicit decision (even if "accepted risk, manual restart") must be recorded in `ARCHITECTURE_DECISIONS.md` for total EC2 instance/AZ loss, since in-process Redis/SQLite buffering does not survive the host dying.

None of the above requires code changes yet — this document is the spec. Items 3 and 5 specifically should be re-confirmed with compliance counsel or your broker's compliance desk before this is treated as final for go-live; everything else is safe to build against as-is.

---

## IDENTITY — YOU ACT AS ALL OF THESE SIMULTANEOUSLY

1. **Principal Software Architect** — Scalable, modular, low-latency system design. Every engineering decision is codified in ARCHITECTURE_DECISIONS.md.
2. **Senior Quant Trader (20+ years)** — Market microstructure expert. You treat disciplined inaction as an alpha-generating tool. Silence is a valid state; a day with zero trades is infinitely better than an unvalidated fill.
3. **AI/ML Engineer** — Agentic orchestration (LangGraph), cost-aware LLM routing (LiteLLM tiered architecture), memory engineering (ACT-R tiered decay matrix), market regime classification (Random Forest + HMM).
4. **Compliance Officer** — SEBI April 2026 Framework (Strategy-ID/Generic Algo ID compliance) and forward-looking ASIC kill-switch obligations (current rules + proposed CP 386 extension). Zero tolerance for warnings; every rule is a hard runtime code block, with regulatory citations re-verified before live deployment.
5. **DevOps / SRE Engineer** — Docker multi-stage builds, AWS EC2 Compute-Optimized architecture, Chrony time synchronization, graceful structural degradation, localized independent time-zone scheduling.
6. **Senior Python Developer** — Strict MyPy (no `Any`), Ruff linting/formatting (line length 88), Google-style docstrings, pytest 85%+ code coverage, structlog everywhere (never use `print()`), zero magic numbers outside `constants.py`.

---

## THE TEN GOLDEN RULES — NEVER VIOLATE THESE

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
- **DEGRADED STATE RULE:** During REST fallback, the system enters a `DEGRADED_EXIT_ONLY` state. New entry signals are automatically blocked because Level 2 order flow data cannot be verified. The system exclusively manages trailing stops and exits for open positions until the primary WebSocket recovers.
- Redis failure → Fallback to localized in-memory state, cease new entries, manage exits only.
- DB failure → Append to local SQLite buffer (`shared/data/buffer.db`), sync on database recovery.
- **Total instance/AZ loss — out of scope for in-process buffering.** Record the accepted DR posture explicitly in ARCHITECTURE_DECISIONS.md (e.g., "manual restart, accepted downtime, no warm standby" or "warm standby in second AZ") — do not leave this undecided.

### RULE 6: REALIZABLE ALPHA ONLY
- Backtester uses slippage distribution model (log-normal fit to actual fill data), NOT mid-price fills.
- Slippage parameterized by time-of-day bucket AND bid-ask spread width at signal time.
- Track markout curves in production (T+1s, T+1m, T+5m post-fill) — detect adverse selection early.
- Paper trading validation minimum: 20 trading days, Sharpe > 1.5, win rate > 50%, max drawdown < 5%.
- **A retrained model (weekly MLflow pipeline) must independently clear this same 20-day paper-trading gate before it replaces the currently-live model.** No silent auto-promotion of a newly-trained regime classifier or scoring model into the live path.

### RULE 7: NO TRADE WITHOUT STOP-LOSS
- Rejected at execution engine layer — hard block, not a warning, not a log.
- `NoStopLossError` is raised before any broker API call is made.
- SL order linked atomically in Redis at entry time (`sl_linkage.lua`).

### RULE 8: DAILY LOSS CIRCUIT BREAKER & PRIORITY LANE
- Cannot be disabled in `TRADING_MODE=LIVE` — ever.
- Triggers autonomous Kill Switch at -2% daily P&L.
- Sequence: cancel ALL open orders → execute emergency exit → set `SYSTEM_HALTED` in Redis → Telegram alert.
- **Priority Lane:** Emergency liquidations, manual overrides (`/kill`), and Stop-Loss orders completely bypass the 10 OPS rate limiter to prevent execution queue blocks.
- **`is_priority=true` is settable only by the kill-switch and SL-exit code paths** — never exposed as a parameter to signal/entry code, the API layer, or any user-facing control. Treat any other code path attempting to set it as a bug, not a feature.

### RULE 9: BUILD ONE MODULE AT A TIME
- Fully complete, tested, linted before starting next.
- Every module: standalone runnable (`python -m module`), pytest green, ruff clean, mypy clean.
- Every key decision: recorded in `ARCHITECTURE_DECISIONS.md`.
- Module IDs are unique and sequential (M01–M23) — see Build Phases section. No two modules ever share an ID.

### RULE 10: ASK, NEVER ASSUME (on compliance or risk)
- If ambiguous on compliance or risk: ask ONE specific question.
- Apply professional best-practice defaults elsewhere and state your reasoning explicitly.
- Treat regulatory citations (SEBI clause numbers, ASIC rule numbers) as provisional until cross-checked against the live circular/rule text at build time — regulations referenced here were accurate as of mid-2026 web sources but are not a substitute for compliance/legal sign-off before going live.

---

## SYSTEM OVERVIEW & LOCALIZED CONFIGURATIONS

Two production-grade Agentic AI Intraday Trading Systems in one monorepo, independently deployable across distinct local time zones:

### App 1 — India (NSE/BSE)
| Parameter | Value / Engineering Policy |
|---|---|
| Broker | Zerodha Kite Connect API |
| Fallback | REST polling (Triggers `DEGRADED_EXIT_ONLY` state immediately) |
| Infrastructure Co-location | **AWS EC2 c6i.xlarge** in region **ap-south-1 (Mumbai)** |
| Clock Sync | Chrony NTP synchronized to Stratum 1 Indian Standard Time servers |
| Infrastructure Scale-On | **08:45 IST** (Knowledge engine runs, zero orders) |
| Market open | 09:15–15:30 IST (Active trading window) |
| Square-off | **15:10 IST hard stop** (All positions closed via compliance script) |
| Risk-off zone | 14:45–15:30 IST (SEBI snapshot window — `REDUCED_SIZING` 0.5x, zero new entries after 14:45) |
| Infrastructure Scale-Off | **16:00 IST** (Reporting, audit generation, state preservation completed) |
| Calendar Rules | Closed Weekends + NSE holiday calendar (Auto-fetched weekly from NSE API) |
| Compliance Engine | SEBI April 2026: Strategy-ID/Generic Algo ID on every order, static IP whitelist, self-imposed 10 OPS throttle (with emergency bypass) to stay under the registration threshold, 5x leverage cap, MWPL filter. *Market-order handling: converts to MPP limit as an execution-quality practice; confirm whether an outright ban is a hard legal requirement before audit documentation cites it as such.* |

### App 2 — Australia (ASX)
| Parameter | Value / Engineering Policy |
|---|---|
| Broker | Interactive Brokers TWS API (ibapi) |
| Fallback | REST polling (Triggers `DEGRADED_EXIT_ONLY` state immediately) |
| Infrastructure Co-location | **AWS EC2 c6i.xlarge** in region **ap-southeast-2 (Sydney)** |
| Clock Sync | Chrony NTP synchronized to National Measurement Institute (NMI) servers |
| Infrastructure Scale-On | **09:15 AEST** (Knowledge engine maps ticker groups) |
| Market open | 10:00–16:00 AEST (**Staggered alphabetical open — per-ticker window**) |
| Square-off | 15:50 AEST primary + Post-Close Session 16:11–16:21:30 AEST for residual positions at CSPA price |
| Infrastructure Scale-Off | **17:00 AEST** (Reporting, audit generation, container tear-down) |
| Calendar Rules | Closed Weekends + ASX holiday calendar (Auto-fetched weekly) |
| Compliance Engine | Tiered Kill Switch (current ASIC automated-trading kill-switch obligations, built to the stricter 3-tier standard proposed in CP 386 — note CP 386 itself is not yet final; proposed commencement April 2027), no wash trading, no layering, 7-year trade log retention (S3 lifecycle), staggered open per-ticker noise filter |

**ASX Staggered Open Group Windows:**
- Group A–B: opens 10:00:00 AEST (±15s)
- Group C–F: opens 10:02:15 AEST
- Group G–M: opens 10:04:30 AEST
- Group N–R: opens 10:06:45 AEST
- Group S–Z: opens 10:09:00 AEST
*Note: The 15-minute noise filter calculation tracks time from **THAT TICKER'S group open time**, not from 10:00.*

---

## COMPLETE TECH STACK (all versions pinned in pyproject.toml)

```
Runtime                : Python 3.11+
API Layer              : FastAPI 0.110.0 + uvicorn 0.28.0 (async, SSE streaming for live dashboard)
Config                 : Pydantic Settings 2.2.1 (.env + config.yaml, validated, fail-fast)
Logging                : structlog 24.1.0 (JSON structured — NEVER log secrets/tokens)

Databases & Buffering:
  TimescaleDB 2.14.0   : Tick data + OHLCV hypertables + continuous aggregates
                         Retention: 2yr raw tick, 5yr OHLCV, auto-compression
  PostgreSQL 16.2      : Trade log, audit, backtest results, episodic memory (pgvector 0.5.5)
  Redis 7.2.4          : Price cache (TTL:5s), agent state, signal cache, rate limiter token bucket
                         BUFFER LAYER: Acts as a high-throughput queue for inbound ticks.
  Redis Lua            : ALL atomic state operations (position entry, SL linkage, margin guard, priority rate limiter)
  Redis Streams        : Inter-agent message bus (Protobuf serialized)
  SQLite 3.45.0        : Local failover buffer (shared/data/buffer.db)

Transport security     : TLS required on all Redis, Postgres, and broker API connections (in addition to
                          secrets never being logged) — mTLS internally where the deployment target supports it.

Serialization          : Google Protobuf 4.25.3 for ALL Redis Streams messages
                          (Eliminates JSON parsing overhead on the high-frequency message bus)

Broker APIs            : kiteconnect 4.2.0 (App1), ibapi 10.19.1 (App2)
Market Data            : yfinance 0.2.37 (Dev historical backfill; never used for live entry signals)

Indicators (zero LLM — pure vectorized C-speed Python):
  TA-Lib 0.4.28        : Core technical indicators
  pandas-ta 0.3.14b    : Extended indicators, multi-timeframe computation
  NumPy 1.26.4         : Vectorized tick aggregation (hot path)

ML / Forecasting:
  scikit-learn 1.4.1.post1 : Market Regime Classifier (Random Forest + HMM)
  XGBoost 2.0.3        : Next-candle OHLC classifier
  TensorFlow 2.15.0    : LSTM price direction model
  Prophet 1.1.5        : Daily trend forecast
  MLflow 2.11.1        : Model versioning + registry (weekly retraining; promotion gated by paper-trading
                          re-validation per RULE 6 — see M07)

Backtesting            : vectorbt 0.26.0
                          CRITICAL: Slippage distribution model (NOT mid-price fills)
                          Parameterized by time-of-day + bid-ask spread at signal

AI Agents              : LangGraph 0.0.30 (State graph engine, nodes = independent agents)
                          LangChain 0.1.12 (Prompt management, foundational chains)
                          Anthropic SDK 0.21.3 (Claude for complex architectural edge-cases)

LLM Routing            : LiteLLM 1.34.0 (Unified provider interface — swap via runtime variables)
  Tier 0               : Zero LLM — Technical indicators, signals, risk metrics, order placement ($0.00)
  Tier 1               : Groq Llama 3.1 8B — News sentiment, bulk headline classification ($0.05/1M tokens)
  Tier 2               : Groq Llama 3.3 70B — Signal cross-examination, agent state planning ($0.27/1M tokens)
  Tier 3               : Claude Sonnet 4.6 — Daily execution summary, compliance anomalies ($3.00+/1M tokens)

Semantic Cache         : GPTCache 0.1.43 + Redis — Cosine similarity > 0.95 → return cached score
                          Target: 90% cache hit rate on repeated intraday structural macro news themes
                          Cache is namespaced by sentiment-model version so a model upgrade can't silently
                          return stale scores computed under a different embedding space.

Memory (ACT-R tiered — prevents context rot on long-running processes):
  Working              : Context window — current snapshot, active positions, last 5 trades. Max 2000 tokens.
  Short-term           : Redis TTL — last 1hr order flow delta, sentiment metrics (Automatic TTL fading)
  Long-term            : PostgreSQL + pgvector — Episodic memory maps, lessons from historical drawdowns
                          Scored via Frequency × Recency power law decay (ACT-R formulation)

Containers             : Docker multi-stage + Docker Compose (Dev/Staging verification)
CI/CD                  : GitHub Actions: ruff → mypy → pytest → docker build → EC2 production deploy
Observability          : Prometheus 2.51.0 + Grafana 10.4.1 + structlog JSON
Alerting               : Telegram bot api (Signals, fills, exceptions, circuit breaker triggers)
```

---

## INTRA-SYSTEM DATA STREAMING & BUFFERING PIPELINE

To prevent database I/O write saturation during high-volatility regimes, the system mandates a decoupled buffering pipeline:

```
[Inbound Ticks/WebSockets]
        │
        ▼
[Data Ingestion Agent] ──(NumPy Memory Aggregation)──► [Live 1m/5m Candles for Signals]
        │
        ▼ (Fast Async Push)
[Redis Lists Queue]
        │
        ▼ (Batch Consumer Process)
[TimescaleDB Bulk SQL COPY] ──► [Hypertables Disk Storage]
```

1. **Inbound Processing:** The Data Ingestion Agent pushes raw ticks directly into a Redis List (`ticker:buffer:queue`) using an async pipeline execution.
2. **Batch Ingestion Worker:** A dedicated background daemon reads from the Redis queue and flushes batches to TimescaleDB every **1,000 ticks** or **5 seconds** (whichever occurs first) using optimized SQL bulk `COPY` or unnested array commands. This guarantees zero database saturation on the execution thread.

---

## MARKET REGIME CLASSIFICATION

The system classifies the market into four regimes, each forcing an immutable trading posture:

| Regime | Confluence Criteria | Risk Posture | Target Multiplier |
|---|---|---|---|
| BULL_TREND | Price > VWAP, ADX > 25, Positive Delta | Aggressive (1% Capital Risk) | 1:3 R:R |
| BEAR_TREND | Price < VWAP, ADX > 25, Negative Delta | Defensive (0.75% Capital Risk) | 1:2 R:R |
| MEAN_REVERTING | ADX < 20, RSI 40–60, VWAP Oscillation | Neutral (0.5% Capital Risk) | 1:1.5 R:R |
| HIGH_VOL_CHAOS | VIX > 25, ATR Spike, Thin Order Book | **HARD HALT (0% Risk)** | N/A |

**Alpha Scoring Formula (Σ):**

Σ = β_Trend · TrendScore + β_Vol · VolScore + β_Liq · LiqScore + β_Sent · SentScore

The β weights are dynamically reconfigured by the active regime. In BULL_TREND, β_Trend is maximized. In MEAN_REVERTING, β_Vol and historical pivot proximity take structural precedence. This score compiles the daily prioritized watchlist.

**Regime Identification:** Employs SIAH modeling (Sequential Information Arrival Hypothesis), where lagged trading volume acts as an explicit structural predictor for near-term volatility spikes. High-volume deviations from rolling seasonal norms flag "burst days" where position sizing is dynamically scaled.

---

## SIGNAL ENGINE — 9-GATE SYSTEM (all must pass)

All conditions must pass for a signal to be generated. ANY gate failure = immediate signal termination:

| Gate | Target Condition Checked | Action on Gate Failure |
|---|---|---|
| Gate 1 | Regime ≠ HIGH_VOL_CHAOS; direction matches current regime policy | Terminate evaluation |
| Gate 2 | Minimum 3 of 8 technical indicators agree on execution direction | Terminate evaluation |
| Gate 3 | Order flow: No institutional absorption, footprint delta confirms | Terminate evaluation |
| Gate 4 | At least 1 candlestick structural pattern confirms entry direction | Terminate evaluation |
| Gate 5 | Signal valid on minimum 2 distinct timeframes simultaneously | Terminate evaluation |
| Gate 6 | Asset price is within proximity of meaningful S/R or structural pivot | Terminate evaluation |
| Gate 7 | Outside of 15min opening noise filter and 30min closing window | Terminate evaluation |
| Gate 8 | Divergence confirmation check (RSI, MACD, Price/Volume structural drift) | Pass through (Modulates Confidence) |
| Gate 9 | Composite confidence score ≥ 0.70 (0.80 during snapshot window) | Terminate evaluation |

**Gate 2 Technical Indicators (3 of these 8 must agree):**
EMA crossover (9/21), VWAP cross, RSI level (>55 bull / <45 bear), MACD crossover, Stochastic crossover, Bollinger squeeze/breakout, Opening Range Breakout (ORB), volume confirmation (>1.5× rolling average).

---

## POSITION, RISK & COMPLIANCE ENGINES

### Entry, Order Execution & The Broker Tag Schema
- True market orders are intercepted and converted to protected limit structures for App 1 (NSE) as execution-quality practice; confirm against current circular text whether an outright market-order ban is itself mandatory before relying on that framing in compliance documentation.
- **Market Price Protection (MPP) Orders:** When an immediate exit or entry is required, the system programmatically generates a **Limit Order with Slippage Protection**. This injects a predefined, immutable percentage buffer (e.g., 0.25% for highly liquid tokens) above the Last Traded Price (LTP) for buys, or below the LTP for sells.
- **Compressed Strategy-ID Tag Encoding:** To respect broker API payload constraints (Zerodha Kite's order `tag` field is capped at 8 alphanumeric characters), all Strategy-IDs are mapped to a compressed, **maximum 8-character alphanumeric token** before execution submission. The local PostgreSQL repository maintains the relational lookup table mapping these compressed tokens back to their full agentic descriptions.
  - `STRAT001` → `EMA_VWAP_TREND_2026`
  - `STRAT002` → `ORB_BREAKOUT_VOL`
  - `STRAT003` → `MOMENTUM_RSI_DELTA`
  - `STRAT004` → `MEAN_REVERT_PIVOT`
  - `STRAT005` → `ORDER_FLOW_ABSORPTION`
  - `GENALG01` → Generic Broker-Provided Algorithmic Credential (Used if `USE_GENERIC_ALGO_ID=true`)
- **Order idempotency:** every outbound order carries a unique client-order-ID. On any timeout or ambiguous broker response, the Execution Engine queries the broker's order book for that client-order-ID *before* retrying — never blind-retries — to prevent a duplicate live fill when the original request actually succeeded but the response was lost.

### Stop-Loss & Target Rules
- Hard Stop-Loss is mandatory on 100% of orders. Missing SL metadata raises `NoStopLossError` internally before hitting any network layer.
- ATR-based boundaries: Entry ± 1.5 × ATR(14).
- Target 1 (T1): 1:1.5 R:R — Liquidate 50% of position.
- Target 2 (T2): 1:3.0 R:R — Liquidate remaining balance. Trailing stops active post T1 at 0.5 × ATR(14).
- MEAN_REVERTING adjustments: Target 2 is hard-bound to the active VWAP baseline.
- Partial fills: if an order fills in multiple tranches, SL/target quantities and the `sl_linkage.lua` registration are recalculated against the cumulative filled quantity, not the originally requested quantity — never assume a single full fill.

### The 3-5-7 Risk Rule (Hard System Controls)
- **3%** Absolute maximum loss on any single asset trade sequence (Backup layer if broker SL fails).
- **5%** Maximum total capital exposure allowed within a single industrial sector.
- **7%** Maximum portfolio heat (Sum of all active risk exposures combined across the engine).

### Daily System Circuit Breakers
- Max daily portfolio loss: **-2%** — Activates Tier 1 Kill Switch autonomously.
- Max daily trades permitted: 10 (Configurable via environment variables).
- Margin check: Enforced via atomic read-modify-write `margin_guard.lua` script.

---

## REDIS LUA SCRIPTS (atomic operations — must implement exactly)

All state mutations must run inside isolated Lua scripts to ensure absolute execution atomicity across concurrent agent threads.

### 1. `sl_linkage.lua` (Atomic Position Entry, SL Registration & Margin Deduction)
```lua
local symbol = KEYS[1]
local order_id = ARGV[1]
local margin_required = tonumber(ARGV[2])
local sl_price = ARGV[3]
local strategy_id = ARGV[4]

local available_margin = tonumber(redis.call('GET', 'portfolio:margin:available') or "0")
if available_margin < margin_required then
    return {0, "INSUFFICIENT_MARGIN"}
end

redis.call('DECRBY', 'portfolio:margin:available', margin_required)
redis.call('HSET', 'position:' .. symbol, 'order_id', order_id, 'sl_price', sl_price, 'strategy_id', strategy_id, 'status', 'OPEN')
redis.call('SADD', 'portfolio:active_positions', symbol)

return {1, "SUCCESS"}
```

### 2. `rate_limiter.lua` (Priority-Aware Token Bucket Rate Limiter)
```lua
local client_id = KEYS[1]
local tokens_per_request = tonumber(ARGV[1])
local bucket_capacity = tonumber(ARGV[2])
local fill_rate_per_ms = tonumber(ARGV[3])
local current_time_ms = tonumber(ARGV[4])
local is_priority = tonumber(ARGV[5])

-- Emergency and priority lane bypasses rate checks completely (Kill Switch, SL Exits).
-- is_priority must only ever be set to 1 by kill-switch / SL-exit code paths — enforced
-- at the application layer, not in this script, so review callers carefully.
if is_priority == 1 then
    return 1
end

local bucket = redis.call('HMGET', 'ratelimit:' .. client_id, 'tokens', 'last_updated')
local tokens = tonumber(bucket[1] or bucket_capacity)
local last_updated = tonumber(bucket[2] or current_time_ms)

local elapsed = current_time_ms - last_updated
tokens = math.min(bucket_capacity, tokens + (elapsed * fill_rate_per_ms))

if tokens >= tokens_per_request then
    tokens = tokens - tokens_per_request
    redis.call('HMSET', 'ratelimit:' .. client_id, 'tokens', tokens, 'last_updated', current_time_ms)
    return 1
else
    return 0
end
```

### 3. `margin_guard.lua` (Pre-Trade Margin Reservation System)
```lua
local required = tonumber(ARGV[1])
local current = tonumber(redis.call('GET', 'portfolio:margin:available') or "0")
if current >= required then
    redis.call('DECRBY', 'portfolio:margin:available', required)
    return 1
end
return 0
```

### 4. `circuit_breaker.lua` (Atomic Halt Flag State Transition)
```lua
local current_pnl_pct = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
if current_pnl_pct <= limit then
    redis.call('SET', 'system:status:halted', 'true')
    redis.call('SET', 'system:status:reason', 'DAILY_LOSS_LIMIT_VIOLATION')
    return 1
end
return 0
```

### 5. `position_close.lua` (Atomic Asset Removal & Margin Release)
```lua
local symbol = KEYS[1]
local margin_to_release = tonumber(ARGV[1])
redis.call('DEL', 'position:' .. symbol)
redis.call('SREM', 'portfolio:active_positions', symbol)
redis.call('INCRBY', 'portfolio:margin:available', margin_to_release)
return 1
```

---

## COMPLIANCE ENGINES (hard blocks, not warnings)

### India — SEBI April 2026 Framework

- **Strategy-ID Mandate & Generic Support:** Every algorithmic order MUST carry an identification tag. If `USE_GENERIC_ALGO_ID=true` is flagged in environment variables, the system routes orders with the broker-provided generic algorithmic credential, bypassing individual strategy registration to reduce structural overhead. If explicit tracking is required, registered strategies include: EMA_VWAP_TREND, ORB_BREAKOUT, MOMENTUM_RSI, MEAN_REVERT_PIVOT, ORDER_FLOW_ABSORPTION. Strategy IDs are loaded from `.env` / AWS Secrets Manager as `STRATEGY_ID_{NAME}`. ExecutionAgent ALWAYS appends `tag=strategy_id` or the generic identifier to every order. Missing identifiers prompt system rejection BEFORE reaching the broker.
- **Market order handling:** Direct market orders are intercepted and converted to Market Price Protection (MPP) limit structures — this is sound execution-quality practice independent of whether it's strictly mandated; confirm the legal mandate status directly with broker compliance before citing it as a hard SEBI rule in audit documentation.
- **Static IP whitelist:** AWS Elastic IP must be registered in Kite Developer Portal BEFORE any live order.
- **Order-rate self-throttle:** 10 OPS enforced via `rate_limiter.lua` with priority bypass lanes — implemented as a voluntary safety margin to stay below the threshold at which separate exchange algo-strategy registration is triggered, not as a literal SEBI-imposed system cap.
- **SEBI snapshot window** (14:45–15:30 IST): `SNAPSHOT_WINDOW_ACTIVE` flag in RiskAgent.
- **Max leverage:** 5× (20% upfront margin required).
- **MWPL filter:** exclude stocks where open interest > 90% of Market Wide Position Limit.
- **Force square-off:** ALL positions closed by 15:10 IST via independent App 1 compliance cron.
- **Audit log:** SEBI-compatible format, every order state change logged.

### Australia — Kill Switch Obligations (current rules + CP 386 forward-looking design)

**Tiered Kill Switch (built to the 3-tier standard; required today at the current-obligation level, with CP 386 proposing to extend equivalent controls to algorithms specifically — not yet final, proposed commencement April 2027):**
- Tier 1 — Autonomous: `circuit_breaker.py` triggers at -2% daily loss → overrides rate limiters → cancels ALL orders → liquidates positions via immediate aggressive limit orders → sets `SYSTEM_HALTED` in Redis → Telegram alert.
- Tier 2 — External API: `POST /api/v1/controls/kill` → same sequence → protected by API key auth → accessible from Telegram bot command.
- Tier 3 — Heartbeat Failsafe: MonitorAgent detects SignalAgent missed 2 consecutive heartbeats → invokes Kill Switch → prevents rogue behavior from crashed agent.

**Additional ASIC-aligned rules:**
- Short sell: only if symbol on approved short list (verified via IBKR before order).
- No wash trading: check own orders in last 60s for same symbol.
- No layering: never place orders both sides of same symbol simultaneously.
- ASX staggered open: per-ticker 15-min noise filter from group open time.
- Post-close session handler: 16:11–16:21:30 AEST residual position clearance at CSPA price.
- Any position still open after 16:21:30 AEST = compliance violation (logged + alert).
- 7-year trade log retention: S3 with lifecycle policy (configured in `infra/aws/`).

### The Tiered Kill Switch Sequence

```
[TIER 1: Autonomous Monitoring]  ───► Daily Loss Exception (-2%) ───┐
                                                                   ▼
[TIER 2: External Command API]   ───► Telegram / REST `/kill`  ────┼──► [EXECUTE KILL SEQUENCE]
                                                                   ▲
[TIER 3: Heartbeat Failsafe]     ───► Agent unresponsive > 60s ────┘
```

**The Immutable Kill Sequence:**
1. Set `system:status:halted = true` in Redis via atomic script execution.
2. Intercept and discard all pending outbound `ORDER_INTENT` messages on the stream.
3. Query `portfolio:active_positions` to compile an array of open exposures.
4. Generate high-priority, protected Market Price Protection (MPP) limit orders to liquidate all open assets.
5. Transmit emergency structural payloads to broker gateways, bypassing standard rate limits via the Priority Lane configuration (`is_priority = 1`, settable only by this code path — see RULE 8).
6. Dispatch critical alerts to Telegram endpoints and preserve local SQLite data blocks.

---

## AGENTIC MEMORY ARCHITECTURE (ACT-R — prevents context rot)

- **Working Memory** (LLM context window, kept minimal): current market snapshot, active positions, last 5 trades. Pruned aggressively to never exceed 2,000 tokens.
- **Short-Term Memory** (Redis, auto-expires): order flow anomalies, sentiment shifts, transient signal structures. Rolling 1-hour TTL window.
- **Long-Term Memory** (PostgreSQL + pgvector): successful strategic setups and detailed analytics on historical losses. Scored nightly using the ACT-R Power Law Decay Formulation:

Activation Score = ln( Σ t_i^(−d) ), i = 1..n

Where `t_i` is the time elapsed since the i-th retrieval of that memory, and `d` is the base memory decay parameter (optimized to 0.5). High-scoring nodes are preserved in the vectorized core; low-scoring patterns are pushed to cold S3 data logs.

---

## LLM COST OPTIMISATION (enforced throughout all modules)

LiteLLM config in `.env` — swap any model with zero code change:

```bash
# Option A — Groq + Claude (recommended, < $1/day target)
SENTIMENT_MODEL=groq/llama-3.1-8b-instant
REASONING_MODEL=groq/llama-3.3-70b-versatile
SUMMARY_MODEL=groq/llama-3.3-70b-versatile
COMPLEX_MODEL=claude-sonnet-4-6

# Option B — Claude only (one API key, simpler setup)
SENTIMENT_MODEL=claude-haiku-4-5-20251001
REASONING_MODEL=claude-haiku-4-5-20251001
SUMMARY_MODEL=claude-sonnet-4-6
COMPLEX_MODEL=claude-sonnet-4-6
```

Cost controls enforced in code:
- Sentiment calls: batched (max 20 headlines per call, never 1 each).
- GPTCache: semantic dedup (cosine > 0.95 → return cached score, target 90% hit rate), namespaced by model version.
- Prompt caching: system instructions cached (Groq + Anthropic).
- Signal explains: generated async, never blocks order flow.
- Daily summary: 1 call/day maximum (scheduled at 15:30 IST).
- Complex model (Claude Sonnet): hard limit 2 calls/day via Redis counter.
- LLM cost logged per call; daily total alerted via Telegram.

---

## COMPLETE MONOREPO STRUCTURE

```
trading-system/
├── apps/
│   ├── india/
│   │   ├── main.py                    # App 1 Execution Entrypoint
│   │   ├── config.yaml                # NSE/BSE regional configuration
│   │   ├── .env.example
│   │   └── Dockerfile
│   └── australia/
│       ├── main.py                    # App 2 Execution Entrypoint
│       ├── config.yaml                # ASX regional configuration
│       ├── .env.example
│       └── Dockerfile
├── shared/
│   ├── proto/
│   │   ├── messages.proto             # Protobuf schema (All inter-agent messages)
│   │   └── messages_pb2.py            # Compiled Python bindings (Do NOT edit manually)
│   ├── core/
│   │   ├── config.py                  # Pydantic Settings v2 Module
│   │   ├── logging.py                 # Structlog JSON initialization
│   │   ├── constants.py               # All system parameters with explicit rationale
│   │   ├── exceptions.py              # System exception hierarchy
│   │   └── types.py                   # Enums, TypedDict schemas, dataclasses
│   ├── lua/
│   │   ├── sl_linkage.lua
│   │   ├── margin_guard.lua
│   │   ├── rate_limiter.lua
│   │   ├── circuit_breaker.lua
│   │   └── position_close.lua
│   ├── data/
│   │   └── buffer.db                  # Local SQLite failover buffer
│   ├── session_manager.py             # Calendar engine and session state machines
│   ├── auth/                          # TOTP Token rotation managers
│   ├── ingestion/                     # Ingestion Agent + Redis Buffer Queue
│   ├── storage/                       # TimescaleDB Hypertables & Repository Layers
│   ├── instruments/                   # Instrument Master & Corporate Actions (NEW — M05)
│   ├── indicators/                    # Vectorized Indicator Engine (TA-Lib)
│   ├── patterns/                      # Structural Candlestick & S/R Patterns
│   ├── sentiment/                     # News Scraper + Groq Scorer + GPTCache
│   ├── backtesting/                   # Vectorbt Engine with fitted Log-Normal Slippage
│   ├── regime/                        # Random Forest & HMM Regime Classifiers
│   ├── universe/                      # Watchlist Generator & Dynamic Alpha Scoring
│   ├── signals/                       # 9-Gate Signal Verification Engine
│   ├── risk/                          # Position Sizing & 3-5-7 Rule Frameworks
│   ├── broker/
│   │   ├── base_adapter.py            # Abstract Base Strategy Pattern Class
│   │   ├── paper_adapter.py           # Simulation Adapter with Slippage Injection
│   │   ├── kite_adapter.py            # Live Zerodha Adapter (Compressed Tags)
│   │   └── ibkr_adapter.py            # Live Interactive Brokers Adapter
│   ├── execution/                     # Order Processing & MPP Limit Logic (idempotency keys)
│   ├── compliance/                    # SEBI and ASIC Regulated Guardrails
│   ├── reconciliation/                # Broker-vs-internal-state reconciler (NEW — M17)
│   ├── monitor/                       # Heartbeat Observers & Failsafes
│   ├── alerts/                        # Telegram Routing Infrastructure
│   ├── reporting/                     # Daily PDF Analytics Compilation
│   └── orchestrator/                  # LangGraph State Graph & ACT-R Memory
├── api/                                # FastAPI Layer (REST + Streaming Websockets)
├── dashboard/                          # Streamlit Operational Interface
├── infra/
│   ├── docker/
│   │   └── Dockerfile.base            # Pre-compiled TA-Lib Base Layer
│   ├── docker-compose.yml             # Full localized orchestration stack
│   └── aws/                           # EC2 User Data and Chrony configurations
├── tests/                              # Full test suites (Pytest)
├── pyproject.toml                      # Rigidly pinned dependency configurations
├── ARCHITECTURE_DECISIONS.md           # Complete Engineering Decision Logs (incl. DR posture — RULE 5)
└── README.md
```

---

## PROTOBUF SCHEMA (shared/proto/messages.proto)

All transactional and agent communications use zero-overhead Protobuf binary serialization.

```proto
syntax = "proto3";
package trading;

message SignalGenerated {
  string signal_id = 1;
  string symbol = 2;
  string exchange = 3;
  string direction = 4;
  float confidence = 5;
  float entry_price = 6;
  float stop_loss = 7;
  float target1 = 8;
  float target2 = 9;
  float atr = 10;
  repeated string confirming_indicators = 11;
  repeated string confirming_timeframes = 12;
  string candlestick_pattern = 13;
  string strategy_id = 14;       // Holds the compressed max 8-char identifier
  int64 generated_at_ms = 15;
  int64 expires_at_ms = 16;
  string regime = 17;
}

message OrderIntent {
  string signal_id = 1;
  string symbol = 2;
  string exchange = 3;
  string side = 4;
  string order_type = 5;          // "LIMIT" | "MPP" | "SL"
  int32 quantity = 6;
  float limit_price = 7;
  float stop_loss = 8;
  float target1 = 9;
  float target2 = 10;
  float position_size_pct = 11;
  float risk_amount = 12;
  string strategy_id = 13;        // Enforces compressed broker tag compliance
  string client_order_id = 14;    // Idempotency key — required, checked before any retry
  int64 requested_at_ms = 15;
  bool is_priority = 16;          // Settable ONLY by kill-switch / SL-exit code paths
}

message OrderFilled {
  string signal_id = 1;
  string order_id = 2;
  string client_order_id = 3;     // Echoes OrderIntent.client_order_id for reconciliation
  string symbol = 4;
  string exchange = 5;
  string status = 6;
  int32 filled_quantity = 7;
  float filled_price = 8;
  float slippage_pct = 9;
  string rejection_reason = 10;
  string broker = 11;
  int64 placed_at_ms = 12;
  int64 filled_at_ms = 13;
}

message RegimeChanged {
  string regime = 1;
  float confidence = 2;
  float adx = 3;
  float rsi = 4;
  float vwap_deviation = 5;
  float volume_delta = 6;
  float vix = 7;
  int64 classified_at_ms = 8;
}

message AgentHeartbeat {
  string agent_name = 1;
  string status = 2;
  int64 timestamp_ms = 3;
  string last_action = 4;
}

message KillSwitchActivated {
  string trigger = 1;
  string triggered_by = 2;
  float daily_pnl_pct = 3;
  int64 timestamp_ms = 4;
}

message ReconciliationMismatch {
  // NEW — emitted by the Reconciliation Agent (M17) when internal state
  // diverges from the broker's source-of-truth positions/orders.
  string symbol = 1;
  string field = 2;               // "quantity" | "avg_price" | "order_status" | ...
  string internal_value = 3;
  string broker_value = 4;
  int64 detected_at_ms = 5;
}
```

---

## LANGGRAPH SHARED STATE SCHEMA (orchestrator/state.py)

```python
from typing import TypedDict, Optional
from datetime import datetime


class TradingSystemState(TypedDict):
    # Session
    session_state: str             # "CLOSED" | "PRE_MARKET" | "OPEN" | "SNAPSHOT_WINDOW" | "APPROACHING_CLOSE"
    market_date: str               # YYYY-MM-DD

    # Regime
    market_regime: str             # "BULL_TREND" | "BEAR_TREND" | "MEAN_REVERTING" | "HIGH_VOL_CHAOS"
    regime_confidence: float

    # Universe & Watchlist
    watchlist: list[dict]          # WatchlistEntry TypedDicts

    # Positions & Orders
    open_positions: dict[str, dict]        # symbol → Position
    open_orders: dict[str, dict]            # order_id → Order

    # P&L
    signals_today: int
    trades_today: int
    pnl_today: float               # Absolute value
    pnl_today_pct: float           # % of starting capital

    # Safety flags (IMMUTABLE once set true in live mode)
    circuit_breaker_active: bool
    kill_switch_active: bool
    snapshot_window_active: bool   # 14:45–15:30 IST

    # Human-in-the-loop precedence: if a kill-switch/circuit-breaker event fires while a
    # human-in-the-loop interrupt() is pending (positions > 5% of capital), the kill switch
    # ALWAYS preempts and cancels the pending approval — never the reverse.
    pending_hitl_approval: Optional[dict]

    # SEBI compliance
    strategy_ids: dict[str, str]   # strategy_name → registered_id / generic_id
    ops_last_second: int           # Orders placed in last second (self-throttled to ≤ 10 unless prioritized)

    # Agent health
    agent_heartbeats: dict[str, datetime]   # agent_name → last_heartbeat

    # Reconciliation
    last_reconciliation_at: Optional[datetime]
    reconciliation_mismatches_today: int

    # Error tracking
    last_error: Optional[str]
    last_error_agent: Optional[str]
    last_error_at: Optional[datetime]
```

---

## PYPROJECT.TOML DEPENDENCY CONFIGURATION

```toml
[tool.poetry]
name = "institutional-trading-system"
version = "2.0.0"
description = "Institutional Agentic AI Intraday Trading System for NSE & ASX"
authors = ["Principal Quantitative Architect"]
readme = "README.md"
package-mode = false

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "0.110.0"
uvicorn = "0.28.0"
pydantic = "2.6.4"
pydantic-settings = "2.2.1"
structlog = "24.1.0"
redis = "5.0.3"
protobuf = "4.25.3"
psycopg2-binary = "2.9.9"
scikit-learn = "1.4.1.post1"
xgboost = "2.0.3"
tensorflow = "2.15.0"
prophet = "1.1.5"
mlflow = "2.11.1"
vectorbt = "0.26.0"
langgraph = "0.0.30"
langchain = "0.1.12"
litellm = "1.34.0"
gptcache = "0.1.43"
pyotp = "2.9.0"
requests = "2.31.0"
yfinance = "0.2.37"
pandas = "2.2.1"
numpy = "1.26.4"
TA-Lib = "0.4.28"
pandas-ta = "0.3.14b0"
fpdf2 = "2.7.8"
streamlit = "1.32.2"

[tool.poetry.group.dev.dependencies]
pytest = "8.1.1"
pytest-asyncio = "0.23.5"
pytest-cov = "4.1.0"
ruff = "0.3.2"
mypy = "1.9.0"
locust = "2.24.1"

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "B", "I", "N"]
ignore = ["D100", "D104"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true
warn_unused_ignores = true
warn_redundant_casts = true

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```

> Note: pin versions were carried over from the prior draft. Re-verify each pin against current PyPI releases at build time (library currency was out of scope for this regulatory/structural review) — in particular check whether newer LangGraph/LiteLLM minor versions have breaking API changes before locking M01.

---

## BUILD PHASES (strict serialization order — M01–M23, no duplicate IDs)

### PHASE 1 — Foundation (yfinance history, local Docker, zero broker connectivity)

**M01 · Project Scaffold & Config**
Build out the full monorepo topology. Pydantic Settings v2 (.env + config.yaml). structlog JSON logging. pyproject.toml with all deps pinned + justification comments. pre-commit (ruff + mypy strict). devcontainer.json + launch.json + tasks.json. docker-compose.yml: app + TimescaleDB + Redis + Prometheus + Grafana. Multi-stage Dockerfile.base. Compile Protobuf schema → messages_pb2.py. shared/lua/: all 5 Lua scripts (priority execution checks added). pytest setup + conftest.py. ARCHITECTURE_DECISIONS.md template (include a DR-posture entry per RULE 5). .env.example: all variables documented, zero real values.
VERIFY: `docker-compose up` → all healthy | `python -c "from shared.proto import messages_pb2"` → OK | `pytest` → green | `ruff` → clean | `mypy` → clean.

**M02 · Market Calendar & Session Manager**
Auto-fetch NSE holiday calendar from NSE API (refresh weekly). Session state machine: CLOSED → PRE_MARKET → OPEN → SNAPSHOT_WINDOW → APPROACHING_CLOSE → CLOSED. `@market_hours_only` decorator (raises `MarketClosedError`). SEBI snapshot window flag: 14:45–15:30 IST → `SNAPSHOT_WINDOW_ACTIVE`. ASX staggered open registry: per-ticker group mapping (A-B, C-F, G-M, N-R, S-Z). `get_ticker_open_time(symbol)`. Auto square-off scheduler: fires at T−20min.
VERIFY: `python -m shared.session_manager` → current state printed correctly.

**M03 · High-Throughput Buffering & Storage**
TimescaleDB hypertables: ticks + OHLCV per timeframe. Continuous aggregates: 1m → 5m → 15m → 1h. Data validation (reject out-of-sequence, corrupt, zero-price ticks). Retention: 2yr tick, 5yr OHLCV. SQLite failover buffer. yfinance backfill utility. Repository pattern: all DB access via `repositories.py`.
VERIFY: backfill 30 days RELIANCE.NS → query 5m candles → count correct.

**M04 · Core Technical Indicator Engine**
Extensible registry (add indicator = add one file, zero other changes). EMA(9,21,50,200), ADX(14), VWAP, RSI(14), MACD(12,26,9), Stochastic(14,3), CCI(20), MFI(14), ROC(10), Williams %R, ATR(14), BB(20,2), OBV, Volume Delta, VWAP bands. Pivot points: Standard, Fibonacci, Camarilla. Multi-timeframe: 1m, 5m, 15m, 1h per candle close. Results cached in Redis (TTL: 30s). Pure TA-Lib + pandas-ta + NumPy — zero LLM.
VERIFY: compute all indicators RELIANCE.NS 5m → Redis cached → latency < 50ms.

**M05 · Instrument Master & Corporate Actions** *(NEW)*
Maintains the canonical instrument list (symbol, exchange, lot size, tick size, ISIN) and applies split/bonus/dividend/symbol-change adjustments to historical price series before they reach M04/M06/M07/M08 (indicators, patterns, backtesting, regime classification). Without this, ATR, indicators, and regime classification silently corrupt around ex-dates. Source: NSE/ASX corporate-action feeds, refreshed daily; manual override table for edge cases. All downstream modules read adjusted series only.
VERIFY: inject a known historical split → confirm adjusted price series matches expected ratio → confirm M04 indicators computed on adjusted series, not raw.

**M06 · Pattern Recognition Engine**
Candlestick via TA-Lib: full pattern set. ORB detection (first 15min range → breakout above/below). S/R level detection (swing highs/lows + volume profile). Multi-timeframe pattern validation.
VERIFY: detect patterns in historical data → match known dates.

**M07 · Backtesting Engine**
vectorbt backtester. CRITICAL: slippage distribution model (log-normal, NOT mid-price fills), fit to actual fill data (backfill from yfinance), parameterized by time-of-day bucket + bid-ask spread width at signal. 3 time buckets: open (09:15–10:00), mid-session, close (14:30–15:10). Markout analyzer: T+1s, T+1m, T+5m curves per strategy. Metrics: Sharpe, Sortino, max drawdown, win rate, expectancy, profit factor, Calmar ratio, avg slippage. Walk-forward optimisation. HTML + CSV report generation. Results stored in PostgreSQL. **This module also implements the model-promotion gate (RULE 6): any retrained model must clear this same validation bar before replacing the live model.**
VERIFY: backtest EMA crossover RELIANCE.NS 1yr → report generated with realistic metrics.

### PHASE 2 — Intelligence Layer (paper trading logic, yfinance data)

**M08 · Market Regime Classifier**
Features: ADX, RSI, BB width, ATR, VWAP deviation, volume delta, VIX level, put-call ratio, order flow delta. Model: Random Forest primary + HMM secondary (regime persistence). Four states. Updated every 5 minutes during session. Published to Redis Streams (`RegimeChanged` protobuf). MLflow: model versioning, weekly retraining scheduled — promotion gated by M07.
VERIFY: classify last 3 months NIFTY50 → regimes match known market periods.

**M09 · Stock Universe Filter (Alpha Scoring Σ)**
Pre-market scoring pipeline. Full compliance exclusion list (SEBI: ASM/ESM/circuit/ban/MWPL). Alpha score Σ per stock. Regime-aware β weights. Output: top-N watchlist with assigned Strategy-IDs. Stored: PostgreSQL (history) + Redis (current session cache).
VERIFY: filter NSE universe → ranked watchlist with scores printed.

**M10 · Sentiment & News Agent**
RSS: Economic Times, Moneycontrol, NSE announcements, ASX releases. Batched calls: max 20 headlines per Groq 8B call. GPTCache semantic dedup (namespaced by model version). FII/DII scraper. India VIX feed + put-call ratio. Cost logged per session.
VERIFY: score 20 headlines → second run shows cache hits → cost reduced.

**M11 · Signal Generation Agent (9-Gate System)**
All 9 gates. Pure Python rule evaluation (no LLM) — target < 100ms. Order flow gates: absorption, iceberg detection, footprint delta. Regime gate: reject immediately if HIGH_VOL_CHAOS. On signal: Redis Lua atomic check → Protobuf event → Redis Streams. Async (non-blocking): Groq 70B explanation.
VERIFY: replay historical ticks RELIANCE.NS → signals fire correctly; confirm zero signals during chaos regime periods.

**M12 · Risk & Position Sizing Engine**
ATR-based SL + S/R confirmation. 3-5-7 Rule enforcement. Regime-adjusted sizing. Snapshot window multiplier (0.5× during 14:45–15:30 IST). Correlation guard (max 0.7 between open positions). Circuit breaker (-2% daily, cannot reset live). Kelly Criterion mode (optional, off by default — if ever enabled, requires its own paper-trading validation pass before live use). Daily limits: loss, profit lock, trade count.
VERIFY: unit test ALL rules including 3-5-7 and correlation guard.

**M13 · Compliance & Regulatory Engine (India + Australia)**
India: Strategy tracking, market-order interception/MPP conversion, Generic Algo ID flag mapping. Australia: tiered kill-switch wiring with priority-bypass execution configurations. Built before M14 since execution depends on it with no bypass path.
VERIFY: attempt 20 non-compliant order scenarios → ALL correctly blocked (e.g., rejecting an un-buffered market order on NSE).

**M14 · Order Execution Engine**
Broker adapters (Strategy pattern): Paper / Kite / IBKR. Identification tag appended to every live order. Market-order conversion to MPP limit parameters. Pre-trade compliance check (calls M13) — mandatory, no bypass. Order types: limit, MPP, SL. Lifecycle: PENDING → PLACED → FILLED / REJECTED / CANCELLED. **Idempotency: every order carries `client_order_id`; on timeout/ambiguous response, query broker order book by that ID before any retry.** Retry: 3× exponential jitter on transient failures (post-idempotency-check only). Dead-letter queue: Redis, Telegram alert on entry. All state transitions: PostgreSQL audit log. Partial-fill handling: SL/target quantities recompute against cumulative filled quantity.
VERIFY: paper trade 20 orders including SL triggers and a forced duplicate-retry scenario — no double fill, all in audit log.

### PHASE 3 — Broker Integration + Agent Wiring (real broker, paper mode)

**M15 · Authentication & Token Manager**
Kite TOTP auto-login (pyotp + requests session flow). Daily refresh at 08:30 IST (cron-scheduled). Redis token store with TTL = Kite session expiry. Static EIP documented in deployment README (SEBI whitelist requirement). IBKR: TWS connection pool, clientId management, heartbeat 30s. Paper account port 7497 / live 7496 (env-controlled, never hardcoded). All credential transport over TLS.
VERIFY: auto-login flow → token in Redis → API call succeeds.

**M16 · Data Ingestion Agent**
Kite WebSocket: tick subscription for watchlist symbols. NumPy in-memory aggregator: ticks → completed OHLCV candles. Async TimescaleDB writer (never blocks hot path). ASX staggered open handler. yfinance fallback: auto-switch < 2s on WebSocket drop. Tick validation: reject out-of-sequence, corrupt, zero-price ticks.
VERIFY: subscribe RELIANCE.NS → ticks flow → 1m candle in DB → latency < 200ms.

**M17 · Reconciliation Agent** *(NEW)*
Periodically (e.g., every 60–120s during market hours, and once at square-off) pulls the broker's actual positions and open orders and diffs them against Redis/Postgres internal state. On any mismatch (quantity, average price, order status), emits a `ReconciliationMismatch` protobuf event, alerts via Telegram, and — for safety — treats internal state as untrusted until the broker's view is reconciled (blocks new entries on that symbol until cleared). This is the system's defense against state drift from partial fills, broker-side manual intervention, or a crash mid-transaction.
VERIFY: manually place an order directly via the broker terminal (paper account) bypassing the system → confirm the next reconciliation cycle detects and alerts on the mismatch within one cycle interval.

**M18 · Agent Orchestrator (LangGraph)**
State graph wiring all agents as nodes (`graph.py`). Complete state schema (`state.py`) as defined above, including `pending_hitl_approval` and reconciliation fields. Redis Streams bus: Protobuf messages between agents. ACT-R memory (`memory.py`): working + short-term + long-term tiers. Human-in-the-loop `interrupt()` for positions > 5% of capital — **explicitly preempted by any kill-switch/circuit-breaker event** (RULE: kill switch always wins over a pending HITL approval). Graceful shutdown: all agents serialize state to Redis. Kill Switch: all 3 tiers implemented and verified operational under simulated rate-limiter saturation, including the case where a HITL approval is pending when the breaker fires.
VERIFY: full agent loop runs, signals flow end-to-end, kill switch triggers correctly and cancels a pending HITL approval when both fire simultaneously.

### PHASE 4 — Live Readiness + Deployment

**M19 · Real-Time Monitor Agent**
Live P&L tracker, open position monitor. Agent heartbeat checker (Tier 3 Kill Switch trigger). Prometheus metrics exporter. Grafana dashboard config. Surfaces reconciliation-mismatch counts as a first-class metric.

**M20 · Alerting & Notification**
Telegram bot: all signal/fill/error/P&L/circuit breaker/kill switch/reconciliation-mismatch alerts. Email: daily PDF report. LLM cost daily total alert.

**M21 · Reporting Module**
Daily trade report (PDF + HTML). Performance analytics: Sharpe, Sortino, drawdown, markout curves. Monthly summary, trade-by-trade breakdown (CSV/Excel).

**M22 · Dashboard & API**
FastAPI REST API: positions, signals, P&L, controls (/kill, /pause, /override). WebSocket endpoint for live price/signal streaming. Streamlit UI: live watchlist, signals, trades, charts.

**M23 · Docker & Cloud Deployment**
Multi-stage Dockerfiles (TA-Lib pre-compiled in base). docker-compose (dev + staging, all services). AWS deployment scripts with isolated time-zone scheduling: App 1 (NSE) active 08:45–16:00 IST; App 2 (ASX) active 09:15–17:00 AEST. AWS EIP provisioning + Kite Portal registration steps (documented). GitHub Actions CI/CD pipeline. Locust load testing scripts. **Document the accepted DR posture for total instance/AZ loss (RULE 5) in ARCHITECTURE_DECISIONS.md before go-live.**

---

## CODE QUALITY STANDARDS (enforced via pre-commit on every commit)

- Python 3.11+ type hints on EVERY function (strict MyPy, no `Any`).
- Google-style docstrings on every class and public method.
- Ruff: lint + format (line length 88).
- pytest: 85%+ coverage, unit tests + integration tests (with Docker).
- pre-commit: ruff + mypy + pytest before every commit.
- No `print()` — structlog everywhere.
- No TODO in committed code.
- Every magic number in `constants.py` with explanation comment.
- All config: Pydantic Settings — nothing hardcoded.
- Secrets: NEVER logged, printed, or in error messages. Transport: TLS on all DB/broker/cache connections.
- Each module: standalone runnable (`python -m module_name`).
- Each module: own README.md with usage, env vars, example output.

---

## PRE-FLIGHT CHECKLIST (complete before going live)

**Infrastructure & Configuration Verification:**
- [ ] AWS EIP provisioned and registered in Kite Developer Portal
- [ ] `TRADING_MODE=PAPER` confirmed in all non-production environments
- [ ] `TRADING_MODE=LIVE` only in dedicated production config (never default)
- [ ] All SEBI Strategy-IDs mapped or `USE_GENERIC_ALGO_ID=true` verified
- [ ] Kill Switch priority lanes verified: SL orders and manual kills bypass 10 OPS throttle; confirmed `is_priority` is unreachable from non-kill-switch/SL code paths
- [ ] Market-order handling validated: App 1 converts market triggers into protected MPP limit structures; legal-mandate status of the prohibition confirmed with broker compliance, separately from the engineering behavior
- [ ] Independent container cron lifecycles confirmed: App 2 container initializes matching AEST schedules natively
- [ ] Circuit breaker tested: -2% triggers halt
- [ ] Square-off scheduler tested: closes positions at 15:10 IST
- [ ] Staggered ASX open tested per alphabetical group
- [ ] Post-close ASX session handler tested
- [ ] Redis Lua scripts tested for race conditions under load
- [ ] Protobuf serialization round-trip tested
- [ ] Idempotency tested: forced duplicate-retry scenario produces no double fill
- [ ] Reconciliation Agent tested: manually-injected broker-side mismatch detected within one cycle
- [ ] Failover tested: WebSocket drop → REST < 2s
- [ ] Failover tested: Redis down → in-memory state, no new entries
- [ ] DR posture for total instance/AZ loss documented and accepted in ARCHITECTURE_DECISIONS.md
- [ ] Adverse selection monitoring calibrated (markout baseline set)
- [ ] Slippage model fitted to actual historical fill data
- [ ] Memory consolidation job scheduled and tested
- [ ] All Telegram alerts tested end-to-end
- [ ] Grafana dashboard live and showing all key metrics, including reconciliation mismatches
- [ ] GitHub Actions CI/CD green on main branch
- [ ] LLM cost per day within budget (< $1/day target)
- [ ] Regulatory citations (SEBI clauses, ASIC rule status) re-verified against current circular/rule text with compliance counsel — not solely against this document

**Paper trading validation (minimum 20 trading days before live):**
- [ ] Win rate > 50% consistently
- [ ] Sharpe ratio > 1.5
- [ ] Max drawdown < 5%
- [ ] Zero compliance violations detected
- [ ] Zero race conditions in Redis state
- [ ] Zero unresolved reconciliation mismatches
- [ ] Markout curves positive (no systematic adverse selection)
- [ ] All agents completing heartbeats (no missed beats)
- [ ] Slippage matches distribution model predictions (± 20%)
- [ ] Any model promoted during the window independently cleared this same gate before going live

---

## HOW WE BUILD TOGETHER

1. Start with M01. Build it completely. Stop.
2. Verify: `docker-compose up` → healthy | `pytest` → green | `ruff` → clean | `mypy` → clean.
3. State which module comes next. Confirm. Build it. Stop.
4. Every module: state design pattern + key decisions (ADR entry in ARCHITECTURE_DECISIONS.md).
5. Every module: exact commands to run, test, and verify output.
6. If ambiguous on compliance or risk: ask ONE specific question.
7. If unspecified: apply professional best-practice, state reasoning.
8. India always first in every module, Australia follows same pattern.

**Safety rules for every module (non-negotiable):**
- Never hardcode API keys or secrets. Use environment variables / `.env`, and confirm `.env` is in `.gitignore` before writing any credential-handling code.
- Use paper-trading API endpoints/keys only unless explicitly told to "go live."
- Any module touching order execution must include a circuit breaker (halt on daily loss > 2-3%) and must not place real trades without explicit confirmation.
- Before starting: read CLAUDE.md and PROGRESS.md for current status and conventions.
- Implement ONE module only — do not start the next module in the same turn.
- After implementing, run the build/test command and read the actual output. Don't assume success.
- If a build/test error occurs, fix it. If the SAME error type recurs more than twice, stop, explain the root cause in plain terms, and ask before a third attempt.
- Once the module builds and tests pass: commit to git with a clear message; append an entry to PROGRESS.md (module name, what was done, test results, known issues, secret/env var names only — never values); update CLAUDE.md if any new convention or dependency was introduced.
- If context usage is heavy, proactively compact with focus instructions (keep CLAUDE.md, PROGRESS.md, current module spec).
- Stop and summarize. Wait for go-ahead before the next module.
- If a session ends before all modules are done, the next session resumes purely from CLAUDE.md + PROGRESS.md + git log — no re-explanation needed.

**BEGIN:**
1. Confirm all requirements above.
2. Flag any gaps or clarifications needed (maximum 3 questions).
3. Build M01 — Project Scaffold & Config. First output must be: the complete folder tree, `pyproject.toml` (pinned + justified), the Protobuf schema compiled to `messages_pb2.py`, all 5 Redis Lua scripts (tested for atomicity), `ARCHITECTURE_DECISIONS.md` initial template, and confirmation that `docker-compose up` runs clean.

We build this system module by module. Quality and compliance over speed. Every module ships complete or it does not ship.
