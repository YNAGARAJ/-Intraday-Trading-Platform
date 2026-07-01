"""Log-normal slippage model, parameterized by time-of-day bucket and spread width.

Per RULE 6: "slippage distribution model (log-normal fit to actual fill data),
parameterized by time-of-day bucket AND bid-ask spread width at signal time."

Three NSE time-of-day buckets (spec mandated):
  OPEN        09:15–10:00  — wider spreads around the opening cross
  MID_SESSION 10:00–14:30  — tightest intraday liquidity
  CLOSE       14:30–15:10  — spreads widen ahead of the closing cross

Default mu/sigma are calibrated for NSE large-cap equities. Call `fit_from_fills`
once M16 provides actual broker fill data to replace them with fitted parameters.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from shared.backtesting.models import SlippageBucket
from shared.core.constants import (
    SLIPPAGE_BUCKET_CLOSE_MU,
    SLIPPAGE_BUCKET_CLOSE_SIGMA,
    SLIPPAGE_BUCKET_MID_MU,
    SLIPPAGE_BUCKET_MID_SIGMA,
    SLIPPAGE_BUCKET_OPEN_MU,
    SLIPPAGE_BUCKET_OPEN_SIGMA,
    SLIPPAGE_MIN_FIT_SAMPLES,
    SLIPPAGE_REFERENCE_SPREAD_BPS,
)
from shared.core.logging import get_logger

logger = get_logger(__name__)

OPEN_BUCKET: SlippageBucket = SlippageBucket(
    name="OPEN",
    start_hour=9,
    start_minute=15,
    end_hour=10,
    end_minute=0,
    mu=SLIPPAGE_BUCKET_OPEN_MU,
    sigma=SLIPPAGE_BUCKET_OPEN_SIGMA,
)

MID_SESSION_BUCKET: SlippageBucket = SlippageBucket(
    name="MID_SESSION",
    start_hour=10,
    start_minute=0,
    end_hour=14,
    end_minute=30,
    mu=SLIPPAGE_BUCKET_MID_MU,
    sigma=SLIPPAGE_BUCKET_MID_SIGMA,
)

CLOSE_BUCKET: SlippageBucket = SlippageBucket(
    name="CLOSE",
    start_hour=14,
    start_minute=30,
    end_hour=15,
    end_minute=10,
    mu=SLIPPAGE_BUCKET_CLOSE_MU,
    sigma=SLIPPAGE_BUCKET_CLOSE_SIGMA,
)

_ALL_BUCKETS: list[SlippageBucket] = [OPEN_BUCKET, MID_SESSION_BUCKET, CLOSE_BUCKET]


def _bucket_contains(bucket: SlippageBucket, h: int, m: int) -> bool:
    t = h * 60 + m
    start = bucket.start_hour * 60 + bucket.start_minute
    end = bucket.end_hour * 60 + bucket.end_minute
    return start <= t < end


def get_bucket(signal_time: datetime) -> SlippageBucket:
    """Return the SlippageBucket for `signal_time`.

    Falls back to MID_SESSION for timestamps outside all defined buckets
    (e.g. after-hours data used in daily-bar backtests).

    Args:
        signal_time: Timestamp of the signal bar.

    Returns:
        Matching SlippageBucket.
    """
    h, m = signal_time.hour, signal_time.minute
    for bucket in _ALL_BUCKETS:
        if _bucket_contains(bucket, h, m):
            return bucket
    return MID_SESSION_BUCKET


def sample_slippage_bps(
    signal_time: datetime,
    spread_bps: float = SLIPPAGE_REFERENCE_SPREAD_BPS,
    rng: np.random.Generator | None = None,
) -> float:
    """Sample slippage in basis points from the fitted log-normal distribution.

    The raw sample is scaled by `spread_bps / SLIPPAGE_REFERENCE_SPREAD_BPS` so
    wider-spread instruments produce proportionally larger estimates. This implements
    the spec's "parameterized by time-of-day bucket AND bid-ask spread width"
    requirement.

    Args:
        signal_time: Timestamp at which the signal fires; determines the bucket.
        spread_bps: Estimated bid-ask spread at signal time in basis points.
            Pass the instrument's actual spread when available (M14/M16 data).
            Defaults to SLIPPAGE_REFERENCE_SPREAD_BPS (5 bps) when unknown.
        rng: Optional numpy Generator for reproducible sampling (tests use seed=42).

    Returns:
        Non-negative slippage in basis points.
    """
    bucket = get_bucket(signal_time)
    _rng = rng if rng is not None else np.random.default_rng()
    raw_bps = float(_rng.lognormal(mean=bucket.mu, sigma=bucket.sigma))
    scale = max(spread_bps, 0.0) / SLIPPAGE_REFERENCE_SPREAD_BPS
    return raw_bps * scale


def fit_from_fills(
    fills: list[tuple[datetime, float, float]],
) -> dict[str, tuple[float, float]]:
    """Fit log-normal parameters from actual broker fill data.

    Groups fill observations by time-of-day bucket, computes observed slippage
    in basis points, and fits log-normal (mu, sigma) parameters. Buckets with
    fewer than SLIPPAGE_MIN_FIT_SAMPLES observations retain their default parameters.

    Args:
        fills: Sequence of (signal_time, signal_price, fill_price) tuples.
            signal_price is the last close before the signal (decision price);
            fill_price is the actual broker fill price.

    Returns:
        Mapping of bucket_name -> (mu, sigma) — ready to use as SlippageBucket
        parameters. Covers only the three standard buckets.
    """
    observations: dict[str, list[float]] = {b.name: [] for b in _ALL_BUCKETS}
    for signal_time, signal_price, fill_price in fills:
        if signal_price <= 0:
            continue
        bps = abs(fill_price - signal_price) / signal_price * 10_000.0
        if bps <= 0.0:
            continue
        observations[get_bucket(signal_time).name].append(bps)

    defaults = {b.name: (b.mu, b.sigma) for b in _ALL_BUCKETS}
    result: dict[str, tuple[float, float]] = {}
    for bucket_name, obs in observations.items():
        if len(obs) < SLIPPAGE_MIN_FIT_SAMPLES:
            result[bucket_name] = defaults[bucket_name]
            logger.info(
                "slippage_fit_skipped_insufficient_samples",
                bucket=bucket_name,
                n=len(obs),
                required=SLIPPAGE_MIN_FIT_SAMPLES,
            )
        else:
            log_obs = np.log(np.array(obs, dtype=np.float64))
            mu = float(np.mean(log_obs))
            sigma = float(np.std(log_obs, ddof=1))
            result[bucket_name] = (mu, sigma)
            logger.info(
                "slippage_fitted",
                bucket=bucket_name,
                n=len(obs),
                mu=round(mu, 4),
                sigma=round(sigma, 4),
            )
    return result
