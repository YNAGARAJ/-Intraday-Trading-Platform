"""Unit tests for the M08 RegimeClassifier (rule-based + model paths)."""

from __future__ import annotations

import numpy as np
import pytest

from shared.regime.classifier import (
    RegimeClassifier,
    _build_state_map,
    _is_chaos,
    _label_to_regime,
    _regime_to_label,
)
from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures


def _features(**kwargs: float | bool) -> RegimeFeatures:
    defaults: dict[str, float | bool] = dict(
        adx=20.0,
        rsi=50.0,
        bb_width_pct=2.0,
        atr_pct=0.5,
        vwap_deviation_pct=0.0,
        volume_ratio=1.0,
        vix=15.0,
        atr_spike=False,
    )
    defaults.update(kwargs)
    return RegimeFeatures(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestIsChaos:
    def test_high_vix_triggers_chaos(self) -> None:
        assert _is_chaos(_features(vix=26.0)) is True

    def test_vix_at_threshold_not_chaos(self) -> None:
        # > 25, not >= 25
        assert _is_chaos(_features(vix=25.0)) is False

    def test_atr_spike_triggers_chaos(self) -> None:
        assert _is_chaos(_features(atr_spike=True)) is True

    def test_neither_not_chaos(self) -> None:
        assert _is_chaos(_features(vix=20.0, atr_spike=False)) is False


class TestLabelMapping:
    def test_round_trip(self) -> None:
        for regime in MarketRegime:
            assert _label_to_regime(_regime_to_label(regime)) is regime

    def test_labels_are_unique(self) -> None:
        labels = [_regime_to_label(r) for r in MarketRegime]
        assert len(labels) == len(set(labels))


class TestBuildStateMap:
    def test_maps_all_four_states(self) -> None:
        # 40 samples, states cycling 0-3, RF labels match states
        states = np.array(list(range(4)) * 10, dtype=np.int64)
        rf_labels = np.array(list(range(4)) * 10, dtype=np.int32)
        mapping = _build_state_map(states, rf_labels)
        assert len(mapping) == 4
        for state in range(4):
            assert state in mapping
            assert isinstance(mapping[state], MarketRegime)

    def test_unused_state_gets_default(self) -> None:
        # Only states 0 and 1 appear
        states = np.array([0, 0, 1, 1], dtype=np.int64)
        rf_labels = np.array([0, 0, 1, 1], dtype=np.int32)
        mapping = _build_state_map(states, rf_labels)
        # States 2 and 3 should default to MEAN_REVERTING
        assert mapping[2] is MarketRegime.MEAN_REVERTING
        assert mapping[3] is MarketRegime.MEAN_REVERTING


# ---------------------------------------------------------------------------
# Rule-based classifier (no fitted models)
# ---------------------------------------------------------------------------


class TestRuleBasedClassifier:
    def setup_method(self) -> None:
        self.clf = RegimeClassifier()

    def test_not_fitted_by_default(self) -> None:
        assert self.clf._is_fitted is False

    def test_high_vol_chaos_priority_over_everything(self) -> None:
        # Even if ADX is high (trending), VIX > 25 → CHAOS
        f = _features(adx=35.0, vwap_deviation_pct=5.0, vix=30.0)
        result = self.clf.classify(f)
        assert result.regime is MarketRegime.HIGH_VOL_CHAOS
        assert result.confidence == 1.0

    def test_atr_spike_triggers_chaos(self) -> None:
        f = _features(atr_spike=True, vix=10.0)
        result = self.clf.classify(f)
        assert result.regime is MarketRegime.HIGH_VOL_CHAOS

    def test_bull_trend_rule(self) -> None:
        f = _features(adx=30.0, vwap_deviation_pct=1.5, vix=15.0)
        result = self.clf.classify(f)
        assert result.regime is MarketRegime.BULL_TREND

    def test_bear_trend_rule(self) -> None:
        f = _features(adx=30.0, vwap_deviation_pct=-2.0, vix=15.0)
        result = self.clf.classify(f)
        assert result.regime is MarketRegime.BEAR_TREND

    def test_mean_reverting_rule(self) -> None:
        f = _features(adx=15.0, rsi=50.0, vwap_deviation_pct=0.1, vix=12.0)
        result = self.clf.classify(f)
        assert result.regime is MarketRegime.MEAN_REVERTING

    def test_returns_regime_classification_type(self) -> None:
        result = self.clf.classify(_features())
        assert isinstance(result, RegimeClassification)

    def test_classified_at_is_utc(self) -> None:
        result = self.clf.classify(_features())
        assert result.classified_at.tzinfo is not None

    def test_rule_based_confidence_is_zero(self) -> None:
        f = _features(adx=30.0, vwap_deviation_pct=1.0)
        result = self.clf.classify(f)
        assert result.confidence == 0.0

    def test_hmm_state_is_minus_one_when_unfitted(self) -> None:
        result = self.clf.classify(_features())
        assert result.hmm_state == -1


# ---------------------------------------------------------------------------
# Model-based classifier (fitted)
# ---------------------------------------------------------------------------


def _make_training_data(n: int = 200) -> tuple[np.ndarray, list[MarketRegime]]:
    """Generate synthetic balanced training data across all four regimes."""
    rng = np.random.default_rng(0)
    x_rows = []
    y_labels = []
    per_class = n // 4

    for regime in MarketRegime:
        for _ in range(per_class):
            if regime is MarketRegime.BULL_TREND:
                row = [rng.uniform(25, 50), rng.uniform(55, 75), 2.0,
                       0.5, rng.uniform(0.5, 3.0), 1.0, 15.0, 0.0]
            elif regime is MarketRegime.BEAR_TREND:
                row = [rng.uniform(25, 50), rng.uniform(25, 45), 2.0,
                       0.5, rng.uniform(-3.0, -0.5), 1.0, 15.0, 0.0]
            elif regime is MarketRegime.MEAN_REVERTING:
                row = [rng.uniform(5, 20), rng.uniform(40, 60), 2.5,
                       0.4, rng.uniform(-0.5, 0.5), 0.9, 14.0, 0.0]
            else:  # HIGH_VOL_CHAOS
                row = [rng.uniform(10, 60), rng.uniform(20, 80), 6.0,
                       2.0, rng.uniform(-5.0, 5.0), 3.0, 30.0, 1.0]
            x_rows.append(row)
            y_labels.append(regime)

    return np.array(x_rows, dtype=np.float64), y_labels


class TestFittedClassifier:
    def setup_method(self) -> None:
        self.clf = RegimeClassifier()
        x_data, y = _make_training_data(200)
        self.clf.fit(x_data, y)

    def test_is_fitted_after_fit(self) -> None:
        assert self.clf._is_fitted is True

    def test_rf_model_set(self) -> None:
        assert self.clf._rf is not None

    def test_hmm_model_set(self) -> None:
        assert self.clf._hmm is not None

    def test_hmm_state_map_has_four_entries(self) -> None:
        assert len(self.clf._hmm_state_to_regime) == 4

    def test_chaos_still_overrides_fitted_model(self) -> None:
        f = _features(vix=30.0, atr_spike=True)
        result = self.clf.classify(f)
        assert result.regime is MarketRegime.HIGH_VOL_CHAOS
        assert result.confidence == 1.0

    def test_classify_returns_valid_regime(self) -> None:
        f = _features(adx=30.0, rsi=65.0, vwap_deviation_pct=2.0, vix=15.0)
        result = self.clf.classify(f)
        assert result.regime in MarketRegime.__members__.values()

    def test_confidence_in_range(self) -> None:
        f = _features(adx=30.0, rsi=65.0, vwap_deviation_pct=2.0)
        result = self.clf.classify(f)
        assert 0.0 <= result.confidence <= 1.0

    def test_hmm_state_set_after_fit(self) -> None:
        # HMM state should be in [0, 3] after fitting (not -1)
        f = _features(adx=30.0, vwap_deviation_pct=1.5, vix=15.0)
        result = self.clf.classify(f)
        assert result.hmm_state in range(4)

    def test_fit_requires_at_least_two_samples(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(ValueError, match="at least 2"):
            clf.fit(np.array([[1.0, 2.0]]), [MarketRegime.BULL_TREND])

    def test_bull_trend_features_tend_to_bull(self) -> None:
        """With strong bullish synthetic data, model should lean BULL_TREND."""
        rng = np.random.default_rng(99)
        results = []
        for _ in range(20):
            f = RegimeFeatures(
                adx=float(rng.uniform(28, 45)),
                rsi=float(rng.uniform(58, 75)),
                bb_width_pct=2.0,
                atr_pct=0.5,
                vwap_deviation_pct=float(rng.uniform(1.0, 3.0)),
                volume_ratio=1.1,
                vix=14.0,
                atr_spike=False,
            )
            results.append(self.clf.classify(f).regime)
        bull_count = sum(1 for r in results if r is MarketRegime.BULL_TREND)
        assert bull_count >= 10, f"Expected ≥10 BULL_TREND, got {bull_count}"
