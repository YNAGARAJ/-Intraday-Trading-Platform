"""Opening Range Breakout (ORB) detection.

The Opening Range is formed by all candles whose timestamp falls within the first
`opening_range_minutes` of the session. A breakout is recorded when the first
subsequent candle closes above the range high (bullish) or below the range low
(bearish). Only the first breakout direction is recorded; re-tests are ignored.

Session start inference: when `session_open` is not supplied, the earliest candle time
on the last candle's calendar date is used as a proxy. This works correctly for
single-session intraday feeds (NSE/ASX); multi-session data (e.g. overnight bars)
should pass `session_open` explicitly (see ADR-011).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from shared.core.constants import ORB_OPENING_RANGE_MINUTES
from shared.core.logging import get_logger
from shared.patterns.models import ORBState
from shared.storage.models import OHLCVCandle

logger = get_logger(__name__)


def detect_orb(
    candles: Sequence[OHLCVCandle],
    opening_range_minutes: int = ORB_OPENING_RANGE_MINUTES,
    session_open: datetime | None = None,
) -> ORBState | None:
    """Compute ORB state for the current session visible in `candles`.

    Args:
        candles: Intraday OHLCV candles (oldest first). Only the last calendar date's
            bars are examined; earlier dates are ignored.
        opening_range_minutes: How many minutes from the session open form the range.
            Defaults to `ORB_OPENING_RANGE_MINUTES` (15).
        session_open: Explicit session-open timestamp. When `None`, inferred as the
            earliest candle time on the last candle's date.

    Returns:
        `ORBState` with `range_formed=False` when no session candles are found, or
        `None` when `candles` is empty.
    """
    if not candles:
        return None

    last_date = candles[-1].time.date()
    session_candles = [c for c in candles if c.time.date() == last_date]

    if not session_candles:
        return None

    inferred_open: datetime
    if session_open is None:
        inferred_open = min(c.time for c in session_candles)
    else:
        # Normalise to UTC if the caller passed a naive datetime by mistake.
        if session_open.tzinfo is None:
            inferred_open = session_open.replace(tzinfo=timezone.utc)
        else:
            inferred_open = session_open

    orb_cutoff = inferred_open + timedelta(minutes=opening_range_minutes)

    orb_candles = [
        c for c in session_candles if inferred_open <= c.time <= orb_cutoff
    ]
    post_orb_candles = [c for c in session_candles if c.time > orb_cutoff]

    if not orb_candles:
        logger.debug(
            "orb_no_range_candles",
            inferred_open=inferred_open.isoformat(),
            orb_cutoff=orb_cutoff.isoformat(),
        )
        return ORBState(
            orb_high=0.0,
            orb_low=0.0,
            orb_range=0.0,
            session_open=inferred_open,
            range_formed=False,
            breakout_direction=None,
            breakout_price=None,
        )

    orb_high = max(c.high for c in orb_candles)
    orb_low = min(c.low for c in orb_candles)

    breakout_direction: int | None = None
    breakout_price: float | None = None

    for candle in post_orb_candles:
        if candle.close > orb_high:
            breakout_direction = 1
            breakout_price = candle.close
            break
        if candle.close < orb_low:
            breakout_direction = -1
            breakout_price = candle.close
            break

    logger.debug(
        "orb_computed",
        orb_high=orb_high,
        orb_low=orb_low,
        breakout_direction=breakout_direction,
    )
    return ORBState(
        orb_high=orb_high,
        orb_low=orb_low,
        orb_range=orb_high - orb_low,
        session_open=inferred_open,
        range_formed=True,
        breakout_direction=breakout_direction,
        breakout_price=breakout_price,
    )
