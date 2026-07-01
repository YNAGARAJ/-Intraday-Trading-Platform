"""S/R level detection via swing pivots and volume-at-price profiling.

Two complementary detection methods are run and their candidates pooled:

1. **Swing pivots**: a bar qualifies as a swing high (→ resistance) when its `high`
   is strictly greater than all `high` values within `swing_window` bars on each side.
   Symmetrically for swing lows (→ support). Requires `2 * swing_window + 1` candles.

2. **Volume profile**: the close-price range is divided into `volume_profile_buckets`
   equal-width buckets; the accumulated candle volume in each bucket is computed, and
   buckets that are local volume maxima (higher than both neighbours) become additional
   S/R candidates classified by whether the bucket's midpoint is above or below the
   last close.

After pooling, nearby candidates (within `cluster_tolerance_pct`) are merged into a
single level whose representative price is the arithmetic mean of the cluster. Touch
counts are then computed over the full candle series (high for resistance, low for
support), and only levels with ≥ `min_touches` touches are returned.

Strength is normalised 0.0–1.0 relative to the most-touched level in the same result
set, so it is only meaningful for comparisons within one `detect_sr_levels` call.
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from shared.core.constants import (
    SR_CLUSTER_TOLERANCE_PCT,
    SR_MIN_TOUCHES,
    SR_SWING_WINDOW,
    SR_TOUCH_TOLERANCE_PCT,
    VOLUME_PROFILE_BUCKETS,
)
from shared.core.logging import get_logger
from shared.patterns.models import SRLevel
from shared.storage.models import OHLCVCandle

logger = get_logger(__name__)


def _cluster(prices: list[float], tolerance_pct: float) -> list[float]:
    """Merge nearby prices into single representative values.

    Prices are sorted, then scanned left-to-right: a new price that falls within
    `tolerance_pct` percent of the running cluster average is merged (the average
    updates); otherwise it starts a new cluster.

    Args:
        prices: Unsorted list of candidate price levels.
        tolerance_pct: Percentage radius for merging (e.g. 0.3 means ±0.3%).

    Returns:
        Sorted list of cluster representative prices (arithmetic mean of each cluster).
    """
    if not prices:
        return []
    sorted_p = sorted(prices)
    clusters: list[list[float]] = [[sorted_p[0]]]
    for p in sorted_p[1:]:
        centre = sum(clusters[-1]) / len(clusters[-1])
        if abs(p - centre) / centre * 100.0 <= tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [sum(cl) / len(cl) for cl in clusters]


def detect_sr_levels(
    candles: Sequence[OHLCVCandle],
    swing_window: int = SR_SWING_WINDOW,
    touch_tolerance_pct: float = SR_TOUCH_TOLERANCE_PCT,
    min_touches: int = SR_MIN_TOUCHES,
    cluster_tolerance_pct: float = SR_CLUSTER_TOLERANCE_PCT,
    volume_profile_buckets: int = VOLUME_PROFILE_BUCKETS,
) -> list[SRLevel]:
    """Detect support and resistance levels from `candles`.

    Args:
        candles: OHLCV candles (oldest first). Minimum `2 * swing_window + 1` bars
            required; an empty list is returned when this is not met.
        swing_window: Bars on each side of a pivot for swing detection.
        touch_tolerance_pct: Wick must be within this % of the level to count as touch.
        min_touches: Minimum touches for a level to be included in the result.
        cluster_tolerance_pct: Nearby candidates within this % are merged.
        volume_profile_buckets: Number of equal-width price buckets for VAP profiling.

    Returns:
        S/R levels sorted by price ascending; empty list when insufficient data.
    """
    min_required = 2 * swing_window + 1
    if len(candles) < min_required:
        logger.debug(
            "sr_scan_skipped_insufficient_data",
            have=len(candles),
            need=min_required,
        )
        return []

    high: NDArray[np.float64] = np.array([c.high for c in candles], dtype=np.float64)
    low: NDArray[np.float64] = np.array([c.low for c in candles], dtype=np.float64)
    close: NDArray[np.float64] = np.array([c.close for c in candles], dtype=np.float64)
    volume: NDArray[np.float64] = np.array(
        [c.volume for c in candles], dtype=np.float64
    )
    n = len(candles)

    # --- 1. Swing pivots ---
    pivot_resistance: list[float] = []
    pivot_support: list[float] = []

    for i in range(swing_window, n - swing_window):
        left_h = high[i - swing_window : i]
        right_h = high[i + 1 : i + swing_window + 1]
        if float(high[i]) > float(np.max(left_h)) and float(high[i]) > float(
            np.max(right_h)
        ):
            pivot_resistance.append(float(high[i]))

        left_l = low[i - swing_window : i]
        right_l = low[i + 1 : i + swing_window + 1]
        if float(low[i]) < float(np.min(left_l)) and float(low[i]) < float(
            np.min(right_l)
        ):
            pivot_support.append(float(low[i]))

    # --- 2. Volume-at-price profile ---
    price_min = float(np.min(low))
    price_max = float(np.max(high))
    last_close = float(close[-1])

    if price_max > price_min and volume_profile_buckets > 2:
        bucket_size = (price_max - price_min) / volume_profile_buckets
        vol_buckets = np.zeros(volume_profile_buckets, dtype=np.float64)

        for i in range(n):
            bucket_idx = int((float(close[i]) - price_min) / bucket_size)
            bucket_idx = min(bucket_idx, volume_profile_buckets - 1)
            vol_buckets[bucket_idx] += volume[i]

        # Local volume maxima (strictly greater than both neighbours) → candidates
        for i in range(1, volume_profile_buckets - 1):
            if (
                vol_buckets[i] > vol_buckets[i - 1]
                and vol_buckets[i] > vol_buckets[i + 1]
            ):
                bucket_mid = price_min + (i + 0.5) * bucket_size
                if bucket_mid < last_close:
                    pivot_support.append(bucket_mid)
                else:
                    pivot_resistance.append(bucket_mid)

    # --- 3. Cluster nearby candidates ---
    resistance_prices = _cluster(pivot_resistance, cluster_tolerance_pct)
    support_prices = _cluster(pivot_support, cluster_tolerance_pct)

    # --- 4. Count touches and compute strength ---
    def _touch_count(level: float, level_type: str) -> tuple[int, int]:
        """Return (touches, last_touch_bar_index)."""
        tol = level * touch_tolerance_pct / 100.0
        touches = 0
        last_bar = 0
        for i in range(n):
            wick = float(high[i]) if level_type == "RESISTANCE" else float(low[i])
            if abs(wick - level) <= tol:
                touches += 1
                last_bar = i
        return touches, last_bar

    candidates: list[tuple[float, str, int, int]] = []
    max_touches = 1

    for price in resistance_prices:
        tc, last_bar = _touch_count(price, "RESISTANCE")
        if tc >= min_touches:
            candidates.append((price, "RESISTANCE", tc, last_bar))
            max_touches = max(max_touches, tc)

    for price in support_prices:
        tc, last_bar = _touch_count(price, "SUPPORT")
        if tc >= min_touches:
            candidates.append((price, "SUPPORT", tc, last_bar))
            max_touches = max(max_touches, tc)

    levels = [
        SRLevel(
            price=round(price, 6),
            level_type=level_type,
            strength=tc / max_touches,
            touches=tc,
            last_touch_bar=last_bar,
        )
        for price, level_type, tc, last_bar in candidates
    ]
    levels.sort(key=lambda lv: lv.price)

    logger.debug(
        "sr_levels_detected",
        support_count=sum(1 for lv in levels if lv.level_type == "SUPPORT"),
        resistance_count=sum(1 for lv in levels if lv.level_type == "RESISTANCE"),
    )
    return levels
