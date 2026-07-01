"""Data shapes for the pattern recognition engine.

Parallel to `shared.indicators.models` -- the snapshot types M11 (signal engine) and
M07 (backtester) will consume when evaluating Gate 4 (candlestick pattern) and Gate 6
(S/R proximity) of the 9-gate signal system.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CandlestickSignal:
    """A single TA-Lib candlestick pattern detected at a specific bar.

    `bar_index` is 0-based from the oldest candle in the input series, so
    `bar_index == len(candles) - 1` means the current (most recent) bar.
    """

    name: str
    """TA-Lib function name, e.g. 'CDLHAMMER', 'CDLDOJI'."""
    direction: int
    """+100 = bullish signal, -100 = bearish signal (TA-Lib ±200 normalised to ±100)."""
    bar_index: int
    """0-based position in the candle list (oldest = 0) where the pattern appears."""


@dataclass(frozen=True)
class ORBState:
    """Opening Range Breakout state for one trading session.

    `range_formed` is False when the provided candle series contains no bars inside
    the opening-range window -- the result is still returned so callers can distinguish
    "engine ran, no ORB data yet" from "engine was not called".
    """

    orb_high: float
    """Highest high of the candles within the opening-range window."""
    orb_low: float
    """Lowest low of the candles within the opening-range window."""
    orb_range: float
    """`orb_high - orb_low`; zero when `range_formed` is False."""
    session_open: datetime
    """Time used as the session start -- either supplied by the caller or inferred as
    the earliest candle time on the last candle's date."""
    range_formed: bool
    """True once at least one candle falls inside the opening-range window."""
    breakout_direction: int | None
    """+1 = bullish breakout (close above orb_high), -1 = bearish (close below orb_low),
    None = no breakout detected yet."""
    breakout_price: float | None
    """Closing price of the first candle that triggered the breakout, or None."""


@dataclass(frozen=True)
class SRLevel:
    """A detected support or resistance price level.

    Derived from swing pivots (local high/low extrema) and volume-at-price clustering.
    `strength` is normalised to 0.0–1.0 relative to the level with the highest touch
    count in the same batch, so comparisons across batches are not meaningful.
    """

    price: float
    """Representative price of the level (midpoint of the cluster after merging)."""
    level_type: str
    """'SUPPORT' or 'RESISTANCE'."""
    strength: float
    """0.0–1.0 normalised touch count; 1.0 = most-touched level in this batch."""
    touches: int
    """Raw count of candles whose wick came within `SR_TOUCH_TOLERANCE_PCT` of this
    level."""
    last_touch_bar: int
    """0-based bar index (oldest = 0) of the most recent touch -- recency signal."""


@dataclass(frozen=True)
class PatternSnapshot:
    """All patterns detected for one symbol/exchange/timeframe at one point in time.

    This is the object returned by `shared.patterns.engine.compute_snapshot` and cached
    in Redis. M11's Gate 4 and Gate 6 consume `candlestick_signals` and `sr_levels`
    respectively.
    """

    symbol: str
    exchange: str
    timeframe: str
    computed_at: datetime
    """Wall-clock time the computation ran (UTC)."""
    candle_time: datetime
    """Time of the most recent candle used in the computation (not wall-clock time)."""
    candlestick_signals: list[CandlestickSignal]
    """All CDL* pattern detections, sorted by bar_index ascending (oldest first)."""
    orb_state: ORBState | None
    """None when the candle series has no intraday data (e.g. daily bars)."""
    sr_levels: list[SRLevel]
    """S/R levels sorted by price ascending."""


@dataclass(frozen=True)
class MultiTimeframePatterns:
    """Pattern results aggregated across multiple timeframes.

    `confirmed_bullish_patterns` / `confirmed_bearish_patterns` list CDL pattern names
    that appear with the same direction on at least `GATE_5_MIN_TIMEFRAMES_AGREEING`
    distinct timeframes -- satisfying Gate 5 of the signal system.
    """

    symbol: str
    exchange: str
    computed_at: datetime
    snapshots: dict[str, PatternSnapshot]
    """Keyed by timeframe string ('1m', '5m', '15m', etc.)."""
    confirmed_bullish_patterns: list[str]
    """CDL names seen bullish on ≥ GATE_5_MIN_TIMEFRAMES_AGREEING timeframes."""
    confirmed_bearish_patterns: list[str]
    """CDL names seen bearish on ≥ GATE_5_MIN_TIMEFRAMES_AGREEING timeframes."""
