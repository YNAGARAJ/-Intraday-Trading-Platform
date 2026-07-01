"""Markout curve analyzer: T+1m and T+5m post-fill price return.

Per RULE 6: "Track markout curves in production (T+1s, T+1m, T+5m post-fill)."
In a candle-based backtest, T+1s is not resolvable below the candle frequency;
we compute T+1m and T+5m using the closest available candle at each offset.
When the next candle at offset T+N is not present (end of data), the trade is
excluded from that offset's sample rather than assumed breakeven.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from shared.backtesting.models import MarkoutPoint, Trade
from shared.core.constants import MARKOUT_OFFSET_1M, MARKOUT_OFFSET_5M
from shared.storage.models import OHLCVCandle

_OFFSETS: list[tuple[str, int]] = [
    (f"T+{MARKOUT_OFFSET_1M}m", MARKOUT_OFFSET_1M),
    (f"T+{MARKOUT_OFFSET_5M}m", MARKOUT_OFFSET_5M),
]


def _find_candle_at_offset(
    entry_time: datetime,
    offset_minutes: int,
    time_index: dict[datetime, int],
    candles: list[OHLCVCandle],
) -> float | None:
    """Return the close price of the candle nearest to entry_time + offset, or None."""
    target = entry_time + timedelta(minutes=offset_minutes)
    idx = time_index.get(target)
    if idx is not None:
        return candles[idx].close
    # Try up to 2 bars later (handles missing bars due to auction gaps)
    for extra in range(1, 3):
        idx = time_index.get(target + timedelta(minutes=extra))
        if idx is not None:
            return candles[idx].close
    return None


def compute_markout_curves(
    trades: list[Trade],
    candles: list[OHLCVCandle],
) -> list[MarkoutPoint]:
    """Compute T+1m and T+5m markout curves across all trades.

    For each trade entry bar, look up the candle at T+1m and T+5m and compute
    the long-direction return relative to the trade's entry_price.

    Args:
        trades: Trades from a completed backtest (must have entry_time / entry_price).
        candles: Full OHLCV candle series used in the backtest (oldest first).

    Returns:
        List of MarkoutPoint (one per offset), oldest-offset first. Empty list
        when `trades` is empty or no candles are available.
    """
    if not trades or not candles:
        return []

    time_index: dict[datetime, int] = {c.time: i for i, c in enumerate(candles)}
    points: list[MarkoutPoint] = []

    for label, offset_min in _OFFSETS:
        returns: list[float] = []
        for trade in trades:
            future_close = _find_candle_at_offset(
                trade.entry_time, offset_min, time_index, candles
            )
            if future_close is None or trade.entry_price <= 0.0:
                continue
            ret_pct = (future_close - trade.entry_price) / trade.entry_price * 100.0
            # Flip sign for short trades (positive = correct direction)
            returns.append(ret_pct * trade.direction)

        if not returns:
            points.append(
                MarkoutPoint(
                    offset_label=label,
                    avg_return_pct=0.0,
                    median_return_pct=0.0,
                    win_rate_at_offset=0.0,
                    sample_count=0,
                )
            )
            continue

        arr = np.array(returns, dtype=np.float64)
        points.append(
            MarkoutPoint(
                offset_label=label,
                avg_return_pct=round(float(np.mean(arr)), 4),
                median_return_pct=round(float(np.median(arr)), 4),
                win_rate_at_offset=round(float(np.mean(arr > 0.0)), 4),
                sample_count=len(returns),
            )
        )

    return points
