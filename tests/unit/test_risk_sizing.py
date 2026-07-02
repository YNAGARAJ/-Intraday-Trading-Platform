"""Unit tests for M12 position sizing (ATR fixed-risk and Kelly)."""

from __future__ import annotations

import pytest

from shared.risk.sizing import compute_atr_position_size, compute_kelly_position_size


class TestATRPositionSize:
    def test_basic_sizing(self) -> None:
        ps = compute_atr_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        assert ps.quantity >= 1
        assert ps.sizing_method == "ATR_FIXED_RISK"
        assert ps.risk_pct > 0

    def test_quantity_is_integer(self) -> None:
        ps = compute_atr_position_size(
            capital=50_000.0,
            entry_price=500.0,
            stop_loss=490.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        assert isinstance(ps.quantity, int)

    def test_snapshot_window_halves_risk(self) -> None:
        normal = compute_atr_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        snapshot = compute_atr_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=True,
        )
        assert snapshot.snapshot_multiplier == 0.5
        assert snapshot.risk_pct <= normal.risk_pct * 0.6

    def test_regime_bear_reduces_size(self) -> None:
        bull = compute_atr_position_size(
            capital=100_000.0,
            entry_price=1000.0,
            stop_loss=980.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        bear = compute_atr_position_size(
            capital=100_000.0,
            entry_price=1000.0,
            stop_loss=980.0,
            base_risk_pct=0.75,
            regime_multiplier=0.75,
            is_snapshot_window=False,
        )
        assert bear.quantity <= bull.quantity

    def test_regime_multiplier_stored(self) -> None:
        ps = compute_atr_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            base_risk_pct=0.75,
            regime_multiplier=0.75,
            is_snapshot_window=False,
        )
        assert ps.regime_multiplier == 0.75

    def test_notional_equals_qty_times_entry(self) -> None:
        ps = compute_atr_position_size(
            capital=100_000.0,
            entry_price=500.0,
            stop_loss=490.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        assert abs(ps.notional_value - ps.quantity * 500.0) < 0.01

    def test_minimum_quantity_one(self) -> None:
        # Very large stop distance relative to small capital
        ps = compute_atr_position_size(
            capital=1_000.0,
            entry_price=10_000.0,
            stop_loss=9_000.0,
            base_risk_pct=0.5,
            regime_multiplier=0.5,
            is_snapshot_window=False,
        )
        assert ps.quantity >= 1

    def test_zero_entry_raises(self) -> None:
        with pytest.raises(ValueError, match="entry_price must be > 0"):
            compute_atr_position_size(
                capital=100_000.0,
                entry_price=0.0,
                stop_loss=0.0,
                base_risk_pct=1.0,
                regime_multiplier=1.0,
                is_snapshot_window=False,
            )

    def test_stop_too_close_raises(self) -> None:
        with pytest.raises(ValueError, match="stop_distance"):
            compute_atr_position_size(
                capital=100_000.0,
                entry_price=2450.0,
                stop_loss=2449.99,
                base_risk_pct=1.0,
                regime_multiplier=1.0,
                is_snapshot_window=False,
            )

    def test_risk_amount_consistent(self) -> None:
        ps = compute_atr_position_size(
            capital=100_000.0,
            entry_price=1000.0,
            stop_loss=980.0,
            base_risk_pct=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        expected_risk = ps.quantity * abs(1000.0 - 980.0)
        assert abs(ps.risk_amount - expected_risk) < 0.01


class TestKellyPositionSize:
    def test_basic_kelly(self) -> None:
        ps = compute_kelly_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            win_rate=0.6,
            avg_win_loss_ratio=2.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        assert ps.quantity >= 1
        assert ps.sizing_method == "KELLY"

    def test_kelly_snapshot_halves_risk(self) -> None:
        normal = compute_kelly_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            win_rate=0.6,
            avg_win_loss_ratio=2.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        snap = compute_kelly_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            win_rate=0.6,
            avg_win_loss_ratio=2.0,
            regime_multiplier=1.0,
            is_snapshot_window=True,
        )
        assert snap.risk_pct <= normal.risk_pct * 0.6

    def test_negative_kelly_gives_zero_quantity_one(self) -> None:
        # Very low win rate → negative raw Kelly → clamped to 0 → still qty 1
        ps = compute_kelly_position_size(
            capital=100_000.0,
            entry_price=2450.0,
            stop_loss=2413.0,
            win_rate=0.1,
            avg_win_loss_ratio=1.0,
            regime_multiplier=1.0,
            is_snapshot_window=False,
        )
        assert ps.quantity >= 1

    def test_invalid_win_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="win_rate"):
            compute_kelly_position_size(
                capital=100_000.0,
                entry_price=2450.0,
                stop_loss=2413.0,
                win_rate=1.5,
                avg_win_loss_ratio=2.0,
                regime_multiplier=1.0,
                is_snapshot_window=False,
            )

    def test_invalid_win_loss_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="avg_win_loss_ratio"):
            compute_kelly_position_size(
                capital=100_000.0,
                entry_price=2450.0,
                stop_loss=2413.0,
                win_rate=0.6,
                avg_win_loss_ratio=0.0,
                regime_multiplier=1.0,
                is_snapshot_window=False,
            )

    def test_zero_win_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="win_rate"):
            compute_kelly_position_size(
                capital=100_000.0,
                entry_price=2450.0,
                stop_loss=2413.0,
                win_rate=0.0,
                avg_win_loss_ratio=2.0,
                regime_multiplier=1.0,
                is_snapshot_window=False,
            )

    def test_stop_too_close_raises(self) -> None:
        with pytest.raises(ValueError, match="stop_distance"):
            compute_kelly_position_size(
                capital=100_000.0,
                entry_price=2450.0,
                stop_loss=2449.99,
                win_rate=0.6,
                avg_win_loss_ratio=2.0,
                regime_multiplier=1.0,
                is_snapshot_window=False,
            )
