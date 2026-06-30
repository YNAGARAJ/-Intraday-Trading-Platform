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

# --- Risk & Position Sizing ---
MAX_POSITION_CORRELATION: Final[float] = 0.7
"""Correlation guard: max allowed correlation between open positions."""

# --- Caching / TTLs ---
PRICE_CACHE_TTL_SECONDS: Final[int] = 5
INDICATOR_CACHE_TTL_SECONDS: Final[int] = 30
SHORT_TERM_MEMORY_TTL_SECONDS: Final[int] = 3600
"""Redis short-term memory tier: rolling 1-hour TTL (ACT-R architecture)."""

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

# --- Reconciliation (M17) ---
RECONCILIATION_INTERVAL_SECONDS: Final[int] = 90
"""Mid-point of the spec's 60-120s reconciliation cycle band; tunable per deployment."""

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
