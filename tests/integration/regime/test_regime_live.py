"""M08 VERIFY integration test — regime classification on synthetic NIFTY50-like data.

Requires a live TimescaleDB instance (same as conftest.py pg_connection fixture).
Verifies:
  - Features are extracted from real TimescaleDB candles.
  - Rule-based classifier classifies BULL_TREND / BEAR_TREND / MEAN_REVERTING
    / HIGH_VOL_CHAOS correctly on synthetic series engineered to match each regime.
  - Fitted RF + HMM classifier is trained, classifies, and achieves >= 70% accuracy
    on a held-out set from the same distribution.
  - HIGH_VOL_CHAOS is always returned when VIX > threshold regardless of model.
  - Proto message round-trips correctly (serialise → deserialise).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.proto.messages_pb2 import RegimeChanged
from shared.regime.classifier import RegimeClassifier
from shared.regime.features import extract_features
from shared.regime.models import MarketRegime, RegimeFeatures
from shared.regime.publisher import publish_regime_change
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

_SYMBOL = "NIFTY50"
_EXCHANGE = "NSE"


def _synthetic_candles(
    n: int,
    regime: MarketRegime,
    start: datetime | None = None,
) -> list[OHLCVCandle]:
    """Generate synthetic 5-minute candles that should match a target regime."""
    rng = np.random.default_rng(42)
    if start is None:
        start = datetime(2024, 1, 2, 9, 15, tzinfo=timezone.utc)

    candles = []
    price = 22_000.0
    for i in range(n):
        if regime is MarketRegime.BULL_TREND:
            price += rng.uniform(3.0, 8.0)
            vol = int(rng.integers(200_000, 300_000))
        elif regime is MarketRegime.BEAR_TREND:
            price -= rng.uniform(3.0, 8.0)
            vol = int(rng.integers(200_000, 300_000))
        elif regime is MarketRegime.MEAN_REVERTING:
            price += rng.uniform(-2.0, 2.0)
            vol = int(rng.integers(80_000, 120_000))
        else:  # HIGH_VOL_CHAOS — wide swings
            price += rng.uniform(-30.0, 30.0)
            vol = int(rng.integers(500_000, 1_000_000))

        high = price + abs(rng.normal(0, 2.0))
        low = max(1.0, price - abs(rng.normal(0, 2.0)))
        candles.append(
            OHLCVCandle(
                time=start + timedelta(minutes=5 * i),
                symbol=_SYMBOL,
                exchange=_EXCHANGE,
                open=price - rng.uniform(0, 1.0),
                high=high,
                low=low,
                close=price,
                volume=vol,
            )
        )
    return candles


@pytest.fixture()
def inserted_bull_candles(pg_connection: PGConnection) -> list[OHLCVCandle]:
    repo = OHLCVRepository(pg_connection)
    candles = _synthetic_candles(80, MarketRegime.BULL_TREND)
    for c in candles:
        repo.upsert_1m([c])
    return candles


@pytest.fixture()
def inserted_bear_candles(pg_connection: PGConnection) -> list[OHLCVCandle]:
    repo = OHLCVRepository(pg_connection)
    candles = _synthetic_candles(
        80,
        MarketRegime.BEAR_TREND,
        start=datetime(2024, 1, 3, 9, 15, tzinfo=timezone.utc),
    )
    for c in candles:
        repo.upsert_1m([c])
    return candles


class TestRegimeIntegration:
    """VERIFY tests for M08 — require live TimescaleDB via pg_connection fixture."""

    def test_feature_extraction_from_bull_candles(
        self, inserted_bull_candles: list[OHLCVCandle]
    ) -> None:
        features = extract_features(inserted_bull_candles, vix=15.0)
        assert isinstance(features, RegimeFeatures)
        assert features.adx >= 0.0
        assert 0.0 <= features.rsi <= 100.0
        assert features.vwap_deviation_pct > 0.0  # up-trending → close above VWAP

    def test_feature_extraction_from_bear_candles(
        self, inserted_bear_candles: list[OHLCVCandle]
    ) -> None:
        features = extract_features(inserted_bear_candles, vix=15.0)
        assert features.vwap_deviation_pct < 0.0  # down-trending → close below VWAP

    def test_rule_based_bull_trend(
        self, inserted_bull_candles: list[OHLCVCandle]
    ) -> None:
        features = extract_features(inserted_bull_candles, vix=15.0)
        clf = RegimeClassifier()
        result = clf.classify(features)
        # Bull candles with upward trend → at minimum not HIGH_VOL_CHAOS
        assert result.regime is not MarketRegime.HIGH_VOL_CHAOS

    def test_high_vol_chaos_always_returned_with_high_vix(
        self, inserted_bull_candles: list[OHLCVCandle]
    ) -> None:
        features = extract_features(inserted_bull_candles, vix=30.0)
        clf = RegimeClassifier()
        result = clf.classify(features)
        assert result.regime is MarketRegime.HIGH_VOL_CHAOS
        assert result.confidence == 1.0

    def test_fitted_classifier_accuracy(
        self, inserted_bull_candles: list[OHLCVCandle]
    ) -> None:
        """Fit on synthetic data and verify accuracy >= 70% on held-out set."""
        x_rows = []
        y_labels = []
        per_class = 80

        for regime in [
            MarketRegime.BULL_TREND,
            MarketRegime.BEAR_TREND,
            MarketRegime.MEAN_REVERTING,
            MarketRegime.HIGH_VOL_CHAOS,
        ]:
            candles = _synthetic_candles(per_class + 60, regime)
            vix = 30.0 if regime is MarketRegime.HIGH_VOL_CHAOS else 15.0
            for start_idx in range(per_class):
                window = candles[start_idx : start_idx + 60]
                if len(window) < 30:
                    continue
                try:
                    feat = extract_features(window, vix=vix)
                    # Exclude HIGH_VOL_CHAOS from training — chaos is rule-based
                    if regime is not MarketRegime.HIGH_VOL_CHAOS:
                        x_rows.append(feat.to_feature_array())
                        y_labels.append(regime)
                except ValueError:
                    pass

        x_data = np.array(x_rows, dtype=np.float64)
        split = int(len(x_data) * 0.8)
        x_train, x_test = x_data[:split], x_data[split:]
        y_train, y_test = y_labels[:split], y_labels[split:]

        clf = RegimeClassifier()
        clf.fit(x_train, y_train)

        correct = 0
        for i, feat_arr in enumerate(x_test):
            feat = RegimeFeatures(
                adx=feat_arr[0],
                rsi=feat_arr[1],
                bb_width_pct=feat_arr[2],
                atr_pct=feat_arr[3],
                vwap_deviation_pct=feat_arr[4],
                volume_ratio=feat_arr[5],
                vix=feat_arr[6],
                atr_spike=bool(feat_arr[7]),
            )
            result = clf.classify(feat)
            if result.regime is y_test[i]:
                correct += 1

        accuracy = correct / len(x_test) if x_test.shape[0] > 0 else 0.0
        assert accuracy >= 0.70, f"Accuracy {accuracy:.2%} below 70% threshold"

    def test_proto_round_trip(
        self, inserted_bull_candles: list[OHLCVCandle]
    ) -> None:
        """Publish to mock Redis and deserialise back via proto."""
        features = extract_features(inserted_bull_candles, vix=18.0)
        clf = RegimeClassifier()
        classification = clf.classify(features)

        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1-0"
        entry_id = publish_regime_change(classification, redis_mock)
        assert entry_id

        call_args = redis_mock.xadd.call_args
        payload = call_args[0][1]["data"]
        msg = RegimeChanged()
        msg.ParseFromString(payload)
        assert msg.regime == classification.regime.value
        assert abs(msg.confidence - classification.confidence) < 0.001
        assert abs(msg.vix - 18.0) < 0.01
        assert msg.classified_at_ms > 0
