"""Unit tests for shared.backtesting.slippage — log-normal slippage model."""

from datetime import datetime, timezone

import numpy as np
import pytest

from shared.backtesting.slippage import (
    MID_SESSION_BUCKET,
    fit_from_fills,
    get_bucket,
    sample_slippage_bps,
)
from shared.core.constants import (
    SLIPPAGE_MIN_FIT_SAMPLES,
    SLIPPAGE_REFERENCE_SPREAD_BPS,
)

_NSE_OPEN = datetime(2024, 1, 15, 9, 20, tzinfo=timezone.utc)
_NSE_MID = datetime(2024, 1, 15, 11, 0, tzinfo=timezone.utc)
_NSE_CLOSE = datetime(2024, 1, 15, 14, 45, tzinfo=timezone.utc)
_AFTER_HOURS = datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc)


class TestGetBucket:
    def test_open_bucket_at_session_start(self) -> None:
        assert get_bucket(_NSE_OPEN).name == "OPEN"

    def test_open_bucket_at_boundary(self) -> None:
        t = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        assert get_bucket(t).name == "OPEN"

    def test_mid_session_bucket(self) -> None:
        assert get_bucket(_NSE_MID).name == "MID_SESSION"

    def test_close_bucket(self) -> None:
        assert get_bucket(_NSE_CLOSE).name == "CLOSE"

    def test_fallback_to_mid_session_after_hours(self) -> None:
        # Times outside all defined buckets fall back to MID_SESSION
        assert get_bucket(_AFTER_HOURS).name == "MID_SESSION"

    def test_bucket_boundary_transitions(self) -> None:
        # 10:00 is the start of MID_SESSION (exclusive end of OPEN)
        t = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        assert get_bucket(t).name == "MID_SESSION"

    def test_close_bucket_end_boundary(self) -> None:
        # 15:09 is inside CLOSE; 15:10 is past the end → fallback
        inside = datetime(2024, 1, 15, 15, 9, tzinfo=timezone.utc)
        outside = datetime(2024, 1, 15, 15, 10, tzinfo=timezone.utc)
        assert get_bucket(inside).name == "CLOSE"
        assert get_bucket(outside).name == "MID_SESSION"


class TestSampleSlippageBps:
    def test_returns_non_negative(self) -> None:
        rng = np.random.default_rng(0)
        for _ in range(50):
            val = sample_slippage_bps(_NSE_MID, rng=rng)
            assert val >= 0.0

    def test_reproducible_with_same_seed(self) -> None:
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        assert sample_slippage_bps(_NSE_MID, rng=rng1) == sample_slippage_bps(
            _NSE_MID, rng=rng2
        )

    def test_spread_scaling_doubles_slippage(self) -> None:
        # With double the reference spread, expected slippage should double on average
        rng1 = np.random.default_rng(7)
        rng2 = np.random.default_rng(7)
        base = sample_slippage_bps(
            _NSE_MID, spread_bps=SLIPPAGE_REFERENCE_SPREAD_BPS, rng=rng1
        )
        doubled = sample_slippage_bps(
            _NSE_MID, spread_bps=SLIPPAGE_REFERENCE_SPREAD_BPS * 2, rng=rng2
        )
        assert pytest.approx(doubled, rel=1e-9) == base * 2.0

    def test_open_bucket_higher_than_mid_on_average(self) -> None:
        # OPEN mu > MID mu → OPEN should produce higher mean slippage
        rng = np.random.default_rng(99)
        open_samples = [sample_slippage_bps(_NSE_OPEN, rng=rng) for _ in range(500)]
        mid_samples = [sample_slippage_bps(_NSE_MID, rng=rng) for _ in range(500)]
        assert np.mean(open_samples) > np.mean(mid_samples)

    def test_zero_spread_returns_zero(self) -> None:
        rng = np.random.default_rng(1)
        val = sample_slippage_bps(_NSE_MID, spread_bps=0.0, rng=rng)
        assert val == 0.0


class TestFitFromFills:
    def _make_fills(
        self,
        signal_time: datetime,
        bps_values: list[float],
        signal_price: float = 1000.0,
    ) -> list[tuple[datetime, float, float]]:
        fills = []
        for bps in bps_values:
            fill_price = signal_price * (1 + bps / 10_000)
            fills.append((signal_time, signal_price, fill_price))
        return fills

    def test_insufficient_samples_retains_defaults(self) -> None:
        fills = self._make_fills(_NSE_MID, [5.0] * (SLIPPAGE_MIN_FIT_SAMPLES - 1))
        result = fit_from_fills(fills)
        assert result["MID_SESSION"] == (
            MID_SESSION_BUCKET.mu,
            MID_SESSION_BUCKET.sigma,
        )

    def test_sufficient_samples_produces_fitted_params(self) -> None:
        target_bps = 8.0
        fills = self._make_fills(_NSE_OPEN, [target_bps] * SLIPPAGE_MIN_FIT_SAMPLES)
        result = fit_from_fills(fills)
        mu, sigma = result["OPEN"]
        # With constant bps, sigma ~ 0 and mu ~ log(target_bps)
        import math

        assert abs(mu - math.log(target_bps)) < 0.01
        assert sigma < 0.01

    def test_zero_signal_price_skipped(self) -> None:
        fills = [(datetime(2024, 1, 15, 11, 0, tzinfo=timezone.utc), 0.0, 1000.0)]
        result = fit_from_fills(fills)
        # Sparse — should retain defaults
        assert "MID_SESSION" in result

    def test_all_three_buckets_in_result(self) -> None:
        fills = self._make_fills(_NSE_MID, [4.0] * (SLIPPAGE_MIN_FIT_SAMPLES - 1))
        result = fit_from_fills(fills)
        assert set(result.keys()) == {"OPEN", "MID_SESSION", "CLOSE"}
