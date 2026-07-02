"""System-wide constants.

Every numeric parameter that governs trading, risk, or compliance behavior lives here
with an explanation of where it comes from in MASTER_BUILD_PROMPT_FINAL.MD. No module
should hardcode a magic number that already has a home in this file. Constants are
grouped to mirror the spec's own section structure so a reader can cross-reference
directly.

Constants for modules not yet built (M02+) are added incrementally by the module that
first needs them, not pre-populated speculatively here in M01.
"""

from typing import Final

# --- RULE 8 / Daily System Circuit Breakers ---
DAILY_LOSS_LIMIT_PCT: Final[float] = -2.0
"""Autonomous Tier 1 kill switch trigger threshold (% of starting capital)."""

MAX_DAILY_TRADES: Final[int] = 10
"""Max trades per day; configurable via environment in modules that enforce it."""

ORDERS_PER_SECOND_SELF_THROTTLE: Final[int] = 10
"""Self-imposed safety margin to stay under SEBI's algo-registration trigger
threshold -- not itself a SEBI-mandated hard ceiling. See change-log item 4."""

# --- The 3-5-7 Risk Rule ---
MAX_SINGLE_TRADE_LOSS_PCT: Final[float] = 3.0
"""Absolute max loss on any single trade sequence (backup if broker SL fails)."""

MAX_SECTOR_EXPOSURE_PCT: Final[float] = 5.0
"""Max total capital exposure allowed within a single industrial sector."""

MAX_PORTFOLIO_HEAT_PCT: Final[float] = 7.0
"""Max portfolio heat: sum of all active risk exposures across the engine."""

# --- Regime-based risk posture (Market Regime Classification table) ---
RISK_PCT_BULL_TREND: Final[float] = 1.0
RISK_PCT_BEAR_TREND: Final[float] = 0.75
RISK_PCT_MEAN_REVERTING: Final[float] = 0.5
RISK_PCT_HIGH_VOL_CHAOS: Final[float] = 0.0
"""HIGH_VOL_CHAOS is a hard halt -- zero risk, no exceptions (RULE 2)."""

REWARD_RISK_RATIO_BULL_TREND: Final[float] = 3.0
REWARD_RISK_RATIO_BEAR_TREND: Final[float] = 2.0
REWARD_RISK_RATIO_MEAN_REVERTING: Final[float] = 1.5

SNAPSHOT_WINDOW_SIZE_MULTIPLIER: Final[float] = 0.5
"""Position sizing multiplier during the SEBI snapshot window (14:45-15:30 IST)."""

# --- Stop-Loss & Target Rules ---
ATR_PERIOD: Final[int] = 14
ATR_STOP_LOSS_MULTIPLIER: Final[float] = 1.5
"""Entry +/- 1.5x ATR(14) defines the hard stop-loss boundary."""

TARGET_1_REWARD_RISK_RATIO: Final[float] = 1.5
TARGET_1_LIQUIDATE_PCT: Final[float] = 50.0
TARGET_2_REWARD_RISK_RATIO: Final[float] = 3.0
TRAILING_STOP_ATR_MULTIPLIER: Final[float] = 0.5
"""Trailing stop distance, active only after Target 1 is hit."""

# --- Compliance: India (SEBI) ---
MWPL_EXCLUSION_THRESHOLD_PCT: Final[float] = 90.0
"""Exclude stocks where open interest > this % of Market Wide Position Limit."""

MAX_LEVERAGE: Final[float] = 5.0
UPFRONT_MARGIN_PCT: Final[float] = 20.0

STRATEGY_ID_MAX_LENGTH: Final[int] = 8
"""Zerodha Kite order `tag` field cap -- all Strategy-IDs compress to this length."""

MPP_SLIPPAGE_BUFFER_PCT: Final[float] = 0.25
"""Default Market Price Protection buffer for highly liquid instruments;
per-instrument overrides belong in the instrument master (M05), not here."""

WASH_TRADE_LOOKBACK_SECONDS: Final[int] = 60
"""Window to check own orders in the same symbol for wash-trade prevention (Australia).
"""

# --- Signal Engine: 9-Gate System ---
GATE_2_MIN_INDICATORS_AGREEING: Final[int] = 3
GATE_2_TOTAL_INDICATORS: Final[int] = 8
GATE_5_MIN_TIMEFRAMES_AGREEING: Final[int] = 2
GATE_7_OPENING_NOISE_FILTER_MINUTES: Final[int] = 15
GATE_7_CLOSING_WINDOW_MINUTES: Final[int] = 30
GATE_9_CONFIDENCE_THRESHOLD: Final[float] = 0.70
GATE_9_CONFIDENCE_THRESHOLD_SNAPSHOT_WINDOW: Final[float] = 0.80
VOLUME_CONFIRMATION_MULTIPLIER: Final[float] = 1.5
"""Volume confirmation gate: volume must exceed this multiple of the rolling average."""

RSI_BULLISH_LEVEL: Final[float] = 55.0
RSI_BEARISH_LEVEL: Final[float] = 45.0

# --- Risk & Position Sizing (M12) ---
MAX_POSITION_CORRELATION: Final[float] = 0.7
"""Correlation guard: max allowed correlation between open positions."""

KELLY_FRACTION: Final[float] = 0.25
"""Quarter-Kelly fraction for conservative fractional Kelly sizing.
Kelly is OFF by default; requires paper-trading validation before enabling live."""

CORRELATION_LOOKBACK_DAYS: Final[int] = 20
"""Days of daily returns used for Pearson correlation guard computation."""

PROFIT_LOCK_PCT: Final[float] = 2.0
"""Optional daily profit-lock threshold: no new entries once daily P&L > +2%."""

RISK_HALTED_REDIS_KEY: Final[str] = "system:status:halted"
"""Redis key set to 'true' by M18 Kill Switch; M12 reads this to block entries."""

RISK_DAILY_PNL_REDIS_KEY: Final[str] = "risk:daily:pnl:{date}"
"""Redis key pattern for daily P&L tracking (YYYYMMDD substituted at runtime)."""

RISK_DAILY_TRADES_REDIS_KEY: Final[str] = "risk:daily:trades:{date}"
"""Redis key pattern for daily trade count (YYYYMMDD substituted at runtime)."""

MIN_STOP_DISTANCE_PCT: Final[float] = 0.05
"""Minimum stop distance as % of entry price to prevent division-by-zero in sizing."""

# --- Compliance: India force square-off (SEBI) ---
FORCE_SQUARE_OFF_IST_HOUR: Final[int] = 15
FORCE_SQUARE_OFF_IST_MINUTE: Final[int] = 10
"""All positions must be closed by 15:10 IST via the compliance cron (App 1)."""

SNAPSHOT_WINDOW_START_IST_HOUR: Final[int] = 14
SNAPSHOT_WINDOW_START_IST_MINUTE: Final[int] = 45
SNAPSHOT_WINDOW_END_IST_HOUR: Final[int] = 15
SNAPSHOT_WINDOW_END_IST_MINUTE: Final[int] = 30

# --- Compliance: Australia (ASIC) ---
ASX_POST_CLOSE_CUTOFF_HOUR: Final[int] = 16
ASX_POST_CLOSE_CUTOFF_MINUTE: Final[int] = 21
ASX_POST_CLOSE_CUTOFF_SECOND: Final[int] = 30
"""Positions still open after 16:21:30 AEST are a compliance violation (ASIC)."""

ASX_STAGGERED_OPEN_NOISE_FILTER_MINUTES: Final[int] = 15
"""Per-ticker 15-min noise filter from ASX group open time (ASIC staggered open)."""

# --- Kill Switch Redis keys ---
KILL_SWITCH_HALTED_KEY: Final[str] = "system:status:halted"
"""Alias for RISK_HALTED_REDIS_KEY — set atomically by M13 KillSwitchManager."""

KILL_SWITCH_TIER_KEY: Final[str] = "system:kill_switch:tier"
"""Records which tier triggered the kill switch (audit trail)."""

KILL_SWITCH_REASON_KEY: Final[str] = "system:kill_switch:reason"
"""Human-readable reason stored alongside the halt flag (audit trail)."""

# --- Caching / TTLs ---
PRICE_CACHE_TTL_SECONDS: Final[int] = 5
INDICATOR_CACHE_TTL_SECONDS: Final[int] = 30
SHORT_TERM_MEMORY_TTL_SECONDS: Final[int] = 3600
"""Redis short-term memory tier: rolling 1-hour TTL (ACT-R architecture)."""

# --- Order Execution Engine (M14) ---
MAX_RETRIES: Final[int] = 3
"""Maximum broker submission retries on transient errors before dead-lettering."""

RETRY_BASE_DELAY_SECONDS: Final[float] = 0.5
"""Base delay for exponential jitter retry: ``base * 2^attempt + uniform(0, 0.1)``."""

DLQ_REDIS_KEY: Final[str] = "dlq:orders"
"""Redis list key for the dead-letter queue (permanently-failed orders)."""

# --- Ingestion buffering pipeline ---
BATCH_FLUSH_MAX_TICKS: Final[int] = 1000
BATCH_FLUSH_MAX_SECONDS: Final[float] = 5.0
"""Batch consumer flushes to TimescaleDB at 1,000 ticks or 5s, whichever is first."""

# --- ACT-R memory decay ---
WORKING_MEMORY_MAX_TOKENS: Final[int] = 2000
ACT_R_DECAY_PARAMETER_D: Final[float] = 0.5

# --- Data retention ---
TICK_DATA_RETENTION_YEARS: Final[int] = 2
OHLCV_DATA_RETENTION_YEARS: Final[int] = 5
AUSTRALIA_TRADE_LOG_RETENTION_YEARS: Final[int] = 7

# --- Market Calendar & Session Manager (M02) ---
SQUARE_OFF_WARNING_LEAD_MINUTES: Final[int] = 20
"""Auto square-off scheduler fires its warning this many minutes before the hard
square-off deadline (square_off_local)."""

HOLIDAY_CACHE_MAX_AGE_DAYS: Final[int] = 7
"""Holiday calendars are auto-refreshed weekly; a cache older than this is stale."""

ASX_GROUP_OPEN_TOLERANCE_SECONDS: Final[int] = 15
"""+/- tolerance band on each ASX staggered-open group's published open time."""

# --- Reconciliation Agent (M17) ---
RECONCILIATION_INTERVAL_SECONDS: Final[int] = 90
"""Mid-point of the spec's 60-120s reconciliation cycle band; tunable per deployment."""

RECONCILIATION_BLOCKED_REDIS_KEY_PREFIX: Final[str] = "reconciliation:blocked"
"""Redis key prefix for per-symbol entry block.
Key format: ``reconciliation:blocked:<EXCHANGE>:<SYMBOL>``.
Set to 'true' on mismatch; cleared when reconciled."""

RECONCILIATION_MISMATCH_REDIS_STREAM: Final[str] = "reconciliation:mismatches"
"""Redis Stream key for ReconciliationMismatch proto events (M18/M20)."""

RECONCILIATION_TOLERANCE_PRICE_PCT: Final[float] = 0.001
"""Avg-price mismatch threshold (0.1%).
Below this fraction, rounding differences at the broker API are ignored."""

RECONCILIATION_SQUAREOFF_DELAY_SECONDS: Final[int] = 30
"""Seconds before square-off to trigger a final reconciliation pass."""

# --- Agent health (M19) ---
HEARTBEAT_INTERVAL_SECONDS: Final[int] = 30
MAX_MISSED_HEARTBEATS_BEFORE_KILL: Final[int] = 2
"""Tier 3 kill switch trigger: consecutive missed heartbeats from a monitored agent."""

# --- LLM cost optimisation ---
SENTIMENT_BATCH_MAX_HEADLINES: Final[int] = 20
GPTCACHE_SIMILARITY_THRESHOLD: Final[float] = 0.95
GPTCACHE_TARGET_HIT_RATE_PCT: Final[float] = 90.0
COMPLEX_MODEL_MAX_CALLS_PER_DAY: Final[int] = 2
DAILY_SUMMARY_MAX_CALLS_PER_DAY: Final[int] = 1
LLM_DAILY_COST_TARGET_USD: Final[float] = 1.0

# --- Paper trading validation gate (RULE 6) ---
PAPER_TRADING_MIN_DAYS: Final[int] = 20
PAPER_TRADING_MIN_SHARPE: Final[float] = 1.5
PAPER_TRADING_MIN_WIN_RATE_PCT: Final[float] = 50.0
PAPER_TRADING_MAX_DRAWDOWN_PCT: Final[float] = 5.0

# --- Core Technical Indicator Engine (M04) ---
EMA_PERIODS: Final[tuple[int, ...]] = (9, 21, 50, 200)
ADX_PERIOD: Final[int] = 14
RSI_PERIOD: Final[int] = 14
MACD_FAST_PERIOD: Final[int] = 12
MACD_SLOW_PERIOD: Final[int] = 26
MACD_SIGNAL_PERIOD: Final[int] = 9
STOCH_FASTK_PERIOD: Final[int] = 14
STOCH_SLOWK_PERIOD: Final[int] = 3
STOCH_SLOWD_PERIOD: Final[int] = 3
CCI_PERIOD: Final[int] = 20
MFI_PERIOD: Final[int] = 14
ROC_PERIOD: Final[int] = 10
WILLR_PERIOD: Final[int] = 14
# ATR_PERIOD (14) already defined above under "Stop-Loss & Target Rules" -- M04's
# ATR indicator and M12's stop-loss sizing intentionally share the same period.
BBANDS_PERIOD: Final[int] = 20
BBANDS_STDDEV: Final[float] = 2.0
VWAP_BAND_STDDEV_MULTIPLIER: Final[float] = 2.0
"""Spec lists 'VWAP bands' with no explicit width -- 2 standard deviations is the
common default (~95% coverage under a normal assumption), consistent with
BBANDS_STDDEV above."""

CAMARILLA_RANGE_MULTIPLIER: Final[float] = 1.1
"""Standard Camarilla pivot constant (R1-R4/S1-S4 are this times the prior range,
divided by 12/6/4/2 respectively)."""

INDICATOR_LATENCY_BUDGET_MS: Final[float] = 50.0
"""M04 VERIFY threshold: compute-all-indicators + Redis-cache-write must stay under
this. Excludes the upstream DB query, which is I/O-bound and only runs once per
candle close, not on the signal-evaluation hot path."""

INDICATOR_LOOKBACK_CANDLES: Final[int] = 250
"""Default history window fetched per compute call -- comfortably covers the longest
single-indicator requirement (EMA_200) plus warm-up margin for TA-Lib's unstable
period at the start of any series."""

# --- Instrument Master & Corporate Actions (M05) ---
NSE_EQUITY_TICK_SIZE: Final[float] = 0.05
"""NSE's standard equity tick size in INR -- a fixed exchange-wide constant. ASX's
tick size is price-tiered (varies by price band), not a single instrument-level
value, so `Instrument.tick_size` is left `None` for ASX here; the tiered lookup
belongs to M14 (Order Execution Engine), the module that actually needs to round an
order price to a valid increment, not to the instrument master."""

CORPORATE_ACTIONS_REFRESH_WINDOW_DAYS: Final[int] = 365
"""How far back NSECorporateActionSource looks when refreshing -- one year is enough
to catch any action whose ex-date could still affect an indicator's lookback window
(the longest is EMA_200 on 1h candles, ~8 trading days) with generous margin for
catching up after a missed refresh."""

# --- Pattern Recognition Engine (M06) ---
ORB_OPENING_RANGE_MINUTES: Final[int] = 15
"""Opening Range Breakout window: the first N minutes of the session form the price
range. TA-Lib/signal literature widely uses 15 min for NSE/ASX intraday ORB. The
GATE_7_OPENING_NOISE_FILTER_MINUTES constant (also 15 min) is the opening-noise filter
in the signal engine -- same value, different role: one defines the ORB range formation
window, the other gates the signal after the range is formed."""

SR_LOOKBACK_CANDLES: Final[int] = 100
"""How many bars to scan when detecting swing-high/low S/R levels. 100 bars at 5-minute
granularity covers ~8 hours of intraday data -- enough to see multiple sessions while
keeping S/R computation fast (< 1ms)."""

SR_SWING_WINDOW: Final[int] = 5
"""Bars on each side of a pivot required to qualify as a swing high or swing low.
A 5-bar window on 5-minute candles corresponds to ~25 minutes each side, filtering
noise while still capturing meaningful intraday turning points."""

SR_TOUCH_TOLERANCE_PCT: Final[float] = 0.5
"""A candle's wick (high for resistance, low for support) must land within this
percentage of a candidate level to count as a 'touch'. 0.5% matches typical
institutional order clustering observed in NSE/ASX Level 2 data."""

SR_MIN_TOUCHES: Final[int] = 2
"""Minimum number of touch events for a price level to be reported as S/R. A level
touched only once is a single-bar spike; two independent approaches raise confidence
that it represents real order flow at that price."""

SR_CLUSTER_TOLERANCE_PCT: Final[float] = 0.3
"""Swing highs/lows within this percentage of each other are merged into one level.
0.3% at typical NSE prices (e.g. ₹1000) = ₹3 -- tighter than SR_TOUCH_TOLERANCE_PCT
to avoid prematurely collapsing distinct levels before touches are counted."""

VOLUME_PROFILE_BUCKETS: Final[int] = 50
"""Number of equal-width price buckets for the volume-at-price S/R computation. 50
buckets over a typical 1-2% intraday range puts each bucket at ~0.03%, narrower than
SR_CLUSTER_TOLERANCE_PCT, giving adequate resolution without noise amplification."""

CDL_MIN_CANDLES: Final[int] = 10
"""Minimum candles required before running TA-Lib CDL pattern functions. The most
complex TA-Lib candlestick function (CDLABANDONEDBABY) has a lookback of ~9 bars;
10 is a safe floor that covers all current CDL functions with one bar of margin."""

PATTERN_CACHE_TTL_SECONDS: Final[int] = 30
"""Redis TTL for a cached PatternSnapshot -- same as INDICATOR_CACHE_TTL_SECONDS,
since patterns are derived from the same OHLCV data and become stale at the same
rate (when a new bar closes)."""

# --- Backtesting Engine (M07) ---
BACKTEST_INITIAL_CAPITAL: Final[float] = 100_000.0
"""Default starting capital for paper-mode backtests in INR."""

BACKTEST_POSITION_SIZE_PCT: Final[float] = 0.02
"""Fraction of portfolio allocated per trade (2%) matching production M12 default."""

BACKTEST_RISK_FREE_RATE_ANNUAL: Final[float] = 0.065
"""India 10-year G-Sec benchmark rate used to annualise Sharpe/Sortino ratios."""

# Slippage model — log-normal distribution parameters per time-of-day bucket.
# mu/sigma are in log-space so E[bps] = exp(mu + sigma²/2).
# Default values calibrated to typical NSE large-cap liquid equity fill quality;
# replace with fit_from_fills() once M16 provides actual broker fills.
SLIPPAGE_BUCKET_OPEN_MU: Final[float] = 2.0
"""OPEN bucket (09:15–10:00): median ~7.4 bps — wider spreads at the open cross."""

SLIPPAGE_BUCKET_OPEN_SIGMA: Final[float] = 0.5

SLIPPAGE_BUCKET_MID_MU: Final[float] = 1.4
"""MID_SESSION bucket (10:00–14:30): median ~4.1 bps — tightest intraday liquidity."""

SLIPPAGE_BUCKET_MID_SIGMA: Final[float] = 0.4

SLIPPAGE_BUCKET_CLOSE_MU: Final[float] = 1.8
"""CLOSE bucket (14:30–15:10): median ~6.0 bps — spreads widen into close cross."""

SLIPPAGE_BUCKET_CLOSE_SIGMA: Final[float] = 0.5

SLIPPAGE_REFERENCE_SPREAD_BPS: Final[float] = 5.0
"""Reference spread used to scale sampled slippage. A 10 bps actual spread would
double the sampled slippage versus the default parameters."""

SLIPPAGE_MIN_FIT_SAMPLES: Final[int] = 30
"""Minimum fill observations per bucket before refitting; buckets below this threshold
retain the default parameters (conservative floor, not silent degradation)."""

# Walk-forward optimisation
WALK_FORWARD_IN_SAMPLE_DAYS: Final[int] = 60
"""In-sample window length for each walk-forward fold (trading days)."""

WALK_FORWARD_OUT_OF_SAMPLE_DAYS: Final[int] = 20
"""Out-of-sample evaluation window per fold (trading days)."""

WALK_FORWARD_STEP_DAYS: Final[int] = 10
"""How many trading days to advance the window between folds."""

# Markout curve offsets (minutes after fill)
MARKOUT_OFFSET_1M: Final[int] = 1
MARKOUT_OFFSET_5M: Final[int] = 5

# --- Market Regime Classifier (M08) ---
REGIME_ADX_TREND_THRESHOLD: Final[float] = 25.0
"""ADX above this value indicates a trending regime (BULL or BEAR)."""

REGIME_ADX_MEAN_REVERT_THRESHOLD: Final[float] = 20.0
"""ADX below this value indicates a mean-reverting regime."""

REGIME_VIX_CHAOS_THRESHOLD: Final[float] = 25.0
"""VIX above this value is a HIGH_VOL_CHAOS signal (RULE 2 hard halt)."""

REGIME_RSI_MEAN_REVERT_LOW: Final[float] = 40.0
"""RSI lower bound for MEAN_REVERTING confirmation (40–60 band)."""

REGIME_RSI_MEAN_REVERT_HIGH: Final[float] = 60.0
"""RSI upper bound for MEAN_REVERTING confirmation."""

REGIME_ATR_SPIKE_MULTIPLIER: Final[float] = 2.0
"""ATR spike threshold: current ATR > this multiple of rolling mean → chaos signal."""

REGIME_RF_N_ESTIMATORS: Final[int] = 100
"""Number of trees in the Random Forest classifier."""

REGIME_RF_MAX_DEPTH: Final[int] = 6
"""Max tree depth — shallow enough to prevent overfitting on limited intraday
history."""

REGIME_HMM_N_COMPONENTS: Final[int] = 4
"""Number of HMM hidden states (one per regime)."""

REGIME_CONFIDENCE_THRESHOLD: Final[float] = 0.60
"""Minimum RF confidence to publish a RegimeChanged event; below this the prior
regime is retained to avoid noisy state flips on ambiguous market conditions."""

REGIME_UPDATE_INTERVAL_MINUTES: Final[int] = 5
"""Re-classify market regime every N minutes during the trading session."""

REGIME_REDIS_STREAM: Final[str] = "regime:changes"
"""Redis Stream key for RegimeChanged protobuf messages."""

REGIME_MLFLOW_EXPERIMENT: Final[str] = "market_regime_classifier"
"""MLflow experiment name for RF + HMM model versioning."""

REGIME_MIN_TRAINING_SAMPLES: Final[int] = 500
"""Minimum labelled candle bars required before fitting the RF model."""

REGIME_FEATURE_LOOKBACK: Final[int] = 50
"""Candle lookback window for feature computation (covers ATR/BB warmup)."""

REGIME_ATR_SPIKE_LOOKBACK: Final[int] = 20
"""Rolling window (bars) used to compute the mean ATR for the spike detector."""

# --- Stock Universe Filter (M09) ---
WATCHLIST_TOP_N: Final[int] = 20
"""Default number of stocks in the daily watchlist per exchange. Configurable via CLI
--top-n flag; M18 orchestrator may override at runtime."""

WATCHLIST_REDIS_TTL_SECONDS: Final[int] = 28_800
"""Redis cache TTL for the current-session watchlist (8 hours ≈ one trading session).
Key per exchange: ``universe:watchlist:<EXCHANGE>``."""

WATCHLIST_CANDLE_LOOKBACK_DAYS: Final[int] = 5
"""Days of 5-minute candle history fetched per instrument for alpha scoring. 5 days
≈ 375 bars at NSE open hours, comfortably covering EMA(21) + ADX(14) warm-up."""

WATCHLIST_MIN_CANDLES: Final[int] = 50
"""Minimum candle bars required to compute a valid alpha score. Instruments with fewer
bars receive composite_score = 0.0 and rank last in the watchlist."""

COMPLIANCE_CACHE_MAX_AGE_HOURS: Final[int] = 24
"""Max age of cached ASM/ESM/ban/MWPL lists before a fresh live fetch is attempted."""

COMPLIANCE_CACHE_DIR: Final[str] = "shared/data/compliance_cache"
"""Directory for compliance list JSON cache files (relative to repo root; gitignored).
"""

ALPHA_TREND_ADX_SCALE: Final[float] = 50.0
"""ADX is divided by this value to normalise TrendScore to [0, 1].
ADX > 50 is treated as 1.0 (very strong trend)."""

ALPHA_VOL_BB_WIDTH_SCALE: Final[float] = 5.0
"""Bollinger Band width % is divided by this to normalise VolScore to [0, 1].
BB width of 5% (typical high-volatility intraday) maps to VolScore = 1.0."""

ALPHA_LIQ_VOLUME_RATIO_CAP: Final[float] = 3.0
"""Volume ratio (recent 5-bar / 20-bar average) is capped here before normalising to
[0, 1]. A stock trading at 3× its average volume maps to LiqScore = 1.0."""

ALPHA_LIQ_RECENT_BARS: Final[int] = 5
"""Number of recent bars averaged as the 'recent volume' for LiqScore."""

ALPHA_LIQ_AVERAGE_BARS: Final[int] = 20
"""Rolling window (bars) for the baseline volume average in LiqScore."""

MWPL_OI_THRESHOLD_BARS: Final[int] = 1
"""Placeholder: MWPL OI check uses the latest available OI bar (M09 fetches daily)."""

# β weight tables per regime — must sum to 1.0 within each row.
# Sent β is reserved for M10 (SentScore always 0.0 until M10 is built).
ALPHA_BETA_BULL_TREND: Final[tuple[float, float, float, float]] = (
    0.50, 0.20, 0.20, 0.10
)
"""(β_Trend, β_Vol, β_Liq, β_Sent) for BULL_TREND: trend maximised per spec."""

ALPHA_BETA_BEAR_TREND: Final[tuple[float, float, float, float]] = (
    0.45, 0.25, 0.20, 0.10
)
"""(β_Trend, β_Vol, β_Liq, β_Sent) for BEAR_TREND: slightly higher vol weight for
downside volatility."""

ALPHA_BETA_MEAN_REVERTING: Final[tuple[float, float, float, float]] = (
    0.20, 0.45, 0.25, 0.10
)
"""(β_Trend, β_Vol, β_Liq, β_Sent) for MEAN_REVERTING: vol and pivot proximity (Liq
proxy) take structural precedence per spec."""

# Strategy ID full names → 8-character compressed Zerodha Kite tag tokens.
# Compression table lives here so M09 (assignment) and M13 (validation) share
# the same source of truth. Keys are the canonical full names used throughout
# the system; values are the STRATEGY_ID_MAX_LENGTH-capped tag strings.
STRATEGY_ID_COMPRESSED: Final[dict[str, str]] = {
    "EMA_VWAP_TREND": "EMAVWAP1",
    "ORB_BREAKOUT": "ORBBRK01",
    "MOMENTUM_RSI": "MOMRSI01",
    "MEAN_REVERT_PIVOT": "MRVPVT01",
    "ORDER_FLOW_ABSORPTION": "ORDFLW01",
}

# Threshold above which trend_score triggers EMA_VWAP_TREND assignment.
STRATEGY_TREND_SCORE_THRESHOLD: Final[float] = 0.6

# --- Sentiment & News Agent (M10) ---
SENTIMENT_CACHE_REDIS_TTL_SECONDS: Final[int] = 86_400
"""Semantic dedup cache TTL: 24h. Intraday macro themes repeat; a daily reset ensures
yesterday's cached scores do not pollute today's aggregate (spec §cost-controls)."""

SENTIMENT_MAX_FEED_AGE_HOURS: Final[int] = 24
"""Discard RSS/announcement headlines older than this. Stale headlines would skew
the aggregate score and count toward the per-run cap unnecessarily."""

SENTIMENT_MAX_HEADLINES_PER_RUN: Final[int] = 100
"""Hard cap on total headlines scored per SentimentAgent.run() call. Prevents a
single noisy feed from flooding the batch queue and breaching the $1/day budget."""

SENTIMENT_GROQ_COST_PER_1M_INPUT_USD: Final[float] = 0.05
"""Groq Llama 3.1-8B input token cost (USD / 1M tokens). Spec: Tier 1 = $0.05/1M."""

SENTIMENT_GROQ_COST_PER_1M_OUTPUT_USD: Final[float] = 0.08
"""Groq Llama 3.1-8B output token cost (USD / 1M tokens). Higher than input per
Groq's published pricing; spec cited a blended ~$0.05/1M for rough budgeting."""

SENTIMENT_EMBEDDING_DIM: Final[int] = 384
"""Embedding dimension for all-MiniLM-L6-v2 (gptcache.embedding.Onnx).
Used to validate deserialized embedding shapes from Redis."""

SENTIMENT_COST_REDIS_KEY_PREFIX: Final[str] = "sentiment:cost:daily"
"""Redis key prefix for daily LLM cost tracking: `sentiment:cost:daily:<YYYYMMDD>`."""

SENTIMENT_CACHE_REDIS_KEY_PREFIX: Final[str] = "sentiment:cache"
"""Redis key prefix for semantic dedup cache: `sentiment:cache:<model_version>`."""

SENTIMENT_DEFAULT_MODEL: Final[str] = "groq/llama-3.1-8b-instant"
"""Default LiteLLM model string for headline scoring (Tier 1 Groq 8B).
Switched to a more capable model only when ``COMPLEX_MODEL_MAX_CALLS_PER_DAY``
budget permits — see RULE 4 (hot path is zero LLM)."""

# --- Signal Generation Agent (M11) ---
SIGNAL_REDIS_STREAM: Final[str] = "signals:generated"
"""Redis Stream key for SignalGenerated protobuf messages (consumed by M12/M14)."""

SIGNAL_EXPIRY_MINUTES: Final[int] = 5
"""Signals are valid for this many minutes after generation; stale signals dropped."""

SIGNAL_EXPLAIN_MODEL: Final[str] = "groq/llama-3.1-70b-versatile"
"""LiteLLM model string for async post-signal explanation (Tier 2 Groq 70B)."""

SIGNAL_DEDUP_WINDOW_SECONDS: Final[int] = 60
"""Min seconds between identical (symbol + direction) signals; dedup window."""

GATE_6_SR_PROXIMITY_PCT: Final[float] = 0.5
"""Price must be within this percentage of a support/resistance level to pass Gate 6."""

GATE_3_ABSORPTION_VOLUME_RATIO: Final[float] = 2.0
"""Volume ≥ this multiple of rolling average to suspect absorption (Gate 3)."""

GATE_3_ABSORPTION_DELTA_RATIO: Final[float] = 0.2
"""If |volume_delta| / total_volume < this ratio at high volume, absorption flagged."""

GATE_2_INDICATOR_BASE_CONFIDENCE: Final[float] = 0.40
"""Base confidence once Gates 1-7 all pass; Gate 2/8 bonuses are added on top."""

GATE_2_PER_INDICATOR_BONUS: Final[float] = 0.02
"""Confidence bonus per agreeing indicator in Gate 2 (max 0.16 for 8/8 agreement)."""

GATE_3_CONFIDENCE_BONUS: Final[float] = 0.07
"""Confidence bonus when Gate 3 (order flow) passes with no absorption detected."""

GATE_4_CONFIDENCE_BONUS: Final[float] = 0.07
"""Confidence bonus for a confirming candlestick pattern (Gate 4), capped at 0.07."""

GATE_5_CONFIDENCE_BONUS: Final[float] = 0.10
"""Confidence bonus for multi-timeframe pattern confirmation (Gate 5)."""

GATE_6_CONFIDENCE_BONUS: Final[float] = 0.05
"""Confidence bonus when price is near a strong S/R level (Gate 6)."""

GATE_8_DIVERGENCE_PENALTY: Final[float] = 0.10
"""Confidence reduction when Gate 8 detects divergence against the signal direction."""

GATE_8_ALIGNMENT_BONUS: Final[float] = 0.05
"""Confidence boost when Gate 8 indicators align with signal direction."""

# --- Authentication & Token Manager (M15) ---
KITE_SESSION_TTL_SECONDS: Final[int] = 30_600
"""Kite session TTL in Redis: 8.5 hours (expires at end of India trading day)."""

KITE_DAILY_REFRESH_IST_HOUR: Final[int] = 8
KITE_DAILY_REFRESH_IST_MINUTE: Final[int] = 30
"""Daily token refresh scheduled for 08:30 IST — before NSE market open at 09:15."""

KITE_TOKEN_REDIS_KEY: Final[str] = "auth:kite:access_token"
"""Redis key storing the live Kite access token."""

KITE_LOGIN_URL: Final[str] = "https://kite.zerodha.com/api/login"
"""Kite TOTP login endpoint (username + password step)."""

KITE_TWOFA_URL: Final[str] = "https://kite.zerodha.com/api/twofa"
"""Kite TOTP two-factor endpoint (TOTP code step)."""

IBKR_PAPER_PORT: Final[int] = 7497
"""IBKR TWS paper-trading port — must match TWS/Gateway configuration."""

IBKR_LIVE_PORT: Final[int] = 7496
"""IBKR TWS live-trading port — must match TWS/Gateway configuration."""

IBKR_HEARTBEAT_INTERVAL_SECONDS: Final[int] = 30
"""TWS connection heartbeat interval to keep the socket alive (per IBKR docs)."""

IBKR_CLIENT_ID_POOL_MAX: Final[int] = 8
"""Maximum concurrent clientId slots in the IBKR connection pool.
IBKR allows up to 32 concurrent connections per TWS instance; 8 is conservative."""

IBKR_CONNECTION_TIMEOUT_SECONDS: Final[int] = 10
"""Timeout for establishing a new TWS EClient connection."""

AUTH_TOKEN_REDIS_KEY_PREFIX: Final[str] = "auth"
"""Redis key namespace for all auth tokens: ``auth:<broker>:<field>``."""

# --- Data Ingestion Agent (M16) ---
TICK_BUFFER_REDIS_KEY: Final[str] = "ticker:buffer:queue"
"""Redis List key for the async tick buffer queue. Batch worker reads from here."""

TICK_BUFFER_FLUSH_COUNT: Final[int] = 1_000
"""Flush the Redis tick queue to TimescaleDB when this many ticks have accumulated."""

TICK_BUFFER_FLUSH_INTERVAL_SECONDS: Final[int] = 5
"""Maximum seconds between batch flushes even if TICK_BUFFER_FLUSH_COUNT not reached."""

WS_FALLBACK_TIMEOUT_SECONDS: Final[int] = 2
"""Switch to REST/yfinance fallback if no WebSocket tick arrives within this window.
RULE 5: WebSocket drop → fallback within 2 seconds."""

INGESTION_DEGRADED_REDIS_KEY: Final[str] = "system:status:degraded"
"""Redis key (string) set to 'true' when ingestion is in DEGRADED_EXIT_ONLY mode.
M18 orchestrator checks this before allowing new entry signals."""

TICK_MAX_BACKWARD_MS: Final[int] = 500
"""Reject ticks whose timestamp is more than this many ms before the last accepted tick
for the same symbol — guards against feed replay / duplicate delivery."""

TICK_MAX_FUTURE_MS: Final[int] = 2_000
"""Reject ticks whose timestamp is more than this many ms ahead of wall-clock time."""

CANDLE_INTERVAL_1M: Final[int] = 60
"""Canonical 1-minute OHLCV candle interval in seconds."""

CANDLE_INTERVAL_5M: Final[int] = 300
"""Canonical 5-minute OHLCV candle interval in seconds."""
