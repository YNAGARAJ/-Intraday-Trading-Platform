"""Unit tests for M08 regime models.

Covers MarketRegime, RegimeFeatures, and RegimeClassification.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures

# ---------------------------------------------------------------------------
# MarketRegime
# ---------------------------------------------------------------------------


def test_regime_enum_values() -> None:
    assert MarketRegime.BULL_TREND.value == "BULL_TREND"
    assert MarketRegime.BEAR_TREND.value == "BEAR_TREND"
    assert MarketRegime.MEAN_REVERTING.value == "MEAN_REVERTING"
    assert MarketRegime.HIGH_VOL_CHAOS.value == "HIGH_VOL_CHAOS"


def test_regime_is_str_enum() -> None:
    assert MarketRegime.BULL_TREND == "BULL_TREND"
    assert MarketRegime.HIGH_VOL_CHAOS == "HIGH_VOL_CHAOS"


def test_regime_from_string() -> None:
    assert MarketRegime("BULL_TREND") is MarketRegime.BULL_TREND
    assert MarketRegime("HIGH_VOL_CHAOS") is MarketRegime.HIGH_VOL_CHAOS


def test_regime_invalid_value_raises() -> None:
    with pytest.raises(ValueError):
        MarketRegime("UNKNOWN")


# ---------------------------------------------------------------------------
# RegimeFeatures
# ---------------------------------------------------------------------------


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


def test_features_frozen() -> None:
    f = _features()
    with pytest.raises(FrozenInstanceError):
        f.adx = 99.0  # type: ignore[misc]


def test_to_feature_array_length() -> None:
    f = _features()
    arr = f.to_feature_array()
    assert len(arr) == 8


def test_to_feature_array_atr_spike_cast() -> None:
    f_spike = _features(atr_spike=True)
    f_no_spike = _features(atr_spike=False)
    assert f_spike.to_feature_array()[-1] == 1.0
    assert f_no_spike.to_feature_array()[-1] == 0.0


def test_to_feature_array_values() -> None:
    f = _features(adx=30.0, rsi=60.0, vix=20.0, atr_spike=True)
    arr = f.to_feature_array()
    assert arr[0] == 30.0
    assert arr[1] == 60.0
    assert arr[6] == 20.0
    assert arr[7] == 1.0


# ---------------------------------------------------------------------------
# RegimeClassification
# ---------------------------------------------------------------------------


def test_classification_frozen() -> None:
    c = RegimeClassification(
        regime=MarketRegime.BULL_TREND,
        confidence=0.85,
        features=_features(),
        hmm_state=0,
        classified_at=datetime.now(timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        c.confidence = 0.5  # type: ignore[misc]


def test_classification_high_vol_chaos_regime() -> None:
    c = RegimeClassification(
        regime=MarketRegime.HIGH_VOL_CHAOS,
        confidence=1.0,
        features=_features(vix=30.0),
        hmm_state=-1,
        classified_at=datetime.now(timezone.utc),
    )
    assert c.regime == MarketRegime.HIGH_VOL_CHAOS
    assert c.confidence == 1.0
    assert c.hmm_state == -1
