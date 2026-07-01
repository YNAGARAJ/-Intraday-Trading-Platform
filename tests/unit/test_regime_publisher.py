"""Unit tests for the M08 Redis Stream publisher."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from shared.proto.messages_pb2 import RegimeChanged
from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures
from shared.regime.publisher import publish_regime_change, read_latest_regime


def _features(**kwargs: float | bool) -> RegimeFeatures:
    defaults: dict[str, float | bool] = dict(
        adx=30.0,
        rsi=65.0,
        bb_width_pct=2.0,
        atr_pct=0.5,
        vwap_deviation_pct=1.5,
        volume_ratio=1.2,
        vix=18.0,
        atr_spike=False,
    )
    defaults.update(kwargs)
    return RegimeFeatures(**defaults)  # type: ignore[arg-type]


def _classification(
    regime: MarketRegime = MarketRegime.BULL_TREND,
) -> RegimeClassification:
    return RegimeClassification(
        regime=regime,
        confidence=0.82,
        features=_features(),
        hmm_state=1,
        classified_at=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
    )


class TestPublishRegimeChange:
    def test_calls_xadd_on_redis(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1234-0"

        entry_id = publish_regime_change(_classification(), redis_mock)

        redis_mock.xadd.assert_called_once()
        assert "1234" in entry_id

    def test_publishes_to_correct_stream(self) -> None:
        from shared.core.constants import REGIME_REDIS_STREAM

        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1-0"
        publish_regime_change(_classification(), redis_mock)

        call_args = redis_mock.xadd.call_args
        assert call_args[0][0] == REGIME_REDIS_STREAM

    def test_payload_is_valid_protobuf(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1-0"
        publish_regime_change(_classification(MarketRegime.BEAR_TREND), redis_mock)

        fields = redis_mock.xadd.call_args[0][1]
        payload = fields["data"]
        msg = RegimeChanged()
        msg.ParseFromString(payload)
        assert msg.regime == "BEAR_TREND"

    def test_proto_fields_populated(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1-0"
        clf = _classification(MarketRegime.BULL_TREND)
        publish_regime_change(clf, redis_mock)

        fields = redis_mock.xadd.call_args[0][1]
        msg = RegimeChanged()
        msg.ParseFromString(fields["data"])
        assert msg.regime == "BULL_TREND"
        assert abs(msg.confidence - 0.82) < 0.01
        assert abs(msg.adx - 30.0) < 0.01
        assert abs(msg.rsi - 65.0) < 0.01
        assert abs(msg.vix - 18.0) < 0.01
        assert msg.classified_at_ms > 0

    def test_maxlen_set_on_xadd(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1-0"
        publish_regime_change(_classification(), redis_mock)

        call_kwargs = redis_mock.xadd.call_args[1]
        assert "maxlen" in call_kwargs
        assert call_kwargs["maxlen"] > 0

    def test_high_vol_chaos_published_correctly(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"5-0"
        clf = RegimeClassification(
            regime=MarketRegime.HIGH_VOL_CHAOS,
            confidence=1.0,
            features=_features(vix=30.0, atr_spike=True),
            hmm_state=-1,
            classified_at=datetime.now(timezone.utc),
        )
        publish_regime_change(clf, redis_mock)

        fields = redis_mock.xadd.call_args[0][1]
        msg = RegimeChanged()
        msg.ParseFromString(fields["data"])
        assert msg.regime == "HIGH_VOL_CHAOS"


class TestReadLatestRegime:
    def test_returns_none_when_stream_empty(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xrevrange.return_value = []
        result = read_latest_regime(redis_mock)
        assert result is None

    def test_returns_none_when_data_field_missing(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xrevrange.return_value = [(b"1-0", {})]
        result = read_latest_regime(redis_mock)
        assert result is None

    def test_deserialises_regime_classification(self) -> None:
        redis_mock = MagicMock()
        redis_mock.xadd.return_value = b"1-0"
        # Build the proto payload directly
        clf = _classification(MarketRegime.MEAN_REVERTING)
        msg = RegimeChanged()
        msg.regime = clf.regime.value
        msg.confidence = float(clf.confidence)
        msg.adx = float(clf.features.adx)
        msg.rsi = float(clf.features.rsi)
        msg.vwap_deviation = float(clf.features.vwap_deviation_pct)
        msg.volume_delta = float(clf.features.volume_ratio)
        msg.vix = float(clf.features.vix)
        msg.classified_at_ms = int(clf.classified_at.timestamp() * 1000)

        redis_mock.xrevrange.return_value = [
            (b"1-0", {b"data": msg.SerializeToString()})
        ]

        result = read_latest_regime(redis_mock)
        assert result is not None
        assert result.regime is MarketRegime.MEAN_REVERTING
        assert abs(result.confidence - 0.82) < 0.01

    def test_returns_none_on_unknown_regime_string(self) -> None:
        redis_mock = MagicMock()
        msg = RegimeChanged()
        msg.regime = "UNKNOWN_REGIME"
        msg.classified_at_ms = 1_700_000_000_000
        redis_mock.xrevrange.return_value = [
            (b"1-0", {b"data": msg.SerializeToString()})
        ]
        result = read_latest_regime(redis_mock)
        assert result is None
