"""Unit tests for M11 SignalPublisher (Redis mocked)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from shared.signals.models import GateResult, SignalResult
from shared.signals.publisher import SignalPublisher, _build_proto


def _make_result(generated: bool = True, direction: str = "LONG") -> SignalResult:
    return SignalResult(
        generated=generated,
        symbol="RELIANCE",
        exchange="NSE",
        direction=direction,
        confidence=0.78,
        entry_price=2450.0,
        stop_loss=2412.5,
        target1=2487.5,
        target2=2525.0,
        atr=25.0,
        strategy_id="EMAVWAP1",
        gate_results=[GateResult(1, True, "ok")],
        failed_at_gate=None,
        confirming_indicators=["EMA", "RSI"],
        confirming_timeframes=["5m", "1h"],
        candlestick_pattern="CDLHAMMER",
        regime="BULL_TREND",
        evaluated_at=datetime.now(UTC),
    )


def _make_publisher(lua_return: list[object]) -> tuple[SignalPublisher, MagicMock]:
    redis_mock = MagicMock()
    script_mock = MagicMock(return_value=lua_return)
    redis_mock.register_script.return_value = script_mock
    with patch("shared.signals.publisher._load_lua", return_value="--lua"):
        pub = SignalPublisher(redis_client=redis_mock)
    pub._script = script_mock
    return pub, script_mock


class TestSignalPublisherPublish:
    def test_publishes_generated_signal(self) -> None:
        pub, script = _make_publisher([1, b"PUBLISHED", b"1234-5678"])
        result = pub.publish(_make_result(generated=True))
        assert result == "1234-5678"
        script.assert_called_once()

    def test_returns_none_when_halted(self) -> None:
        pub, _ = _make_publisher([0, b"HALTED"])
        result = pub.publish(_make_result())
        assert result is None

    def test_returns_none_when_duplicate(self) -> None:
        pub, _ = _make_publisher([0, b"DUPLICATE"])
        result = pub.publish(_make_result())
        assert result is None

    def test_skips_non_generated_result(self) -> None:
        pub, script = _make_publisher([1, b"PUBLISHED", b"1234"])
        result = pub.publish(_make_result(generated=False))
        assert result is None
        script.assert_not_called()

    def test_dedup_key_contains_symbol_and_direction(self) -> None:
        pub, script = _make_publisher([1, b"PUBLISHED", b"9999"])
        pub.publish(_make_result(direction="LONG"))
        call_kwargs = script.call_args
        keys = call_kwargs[1]["keys"] if call_kwargs[1] else call_kwargs[0][0]
        assert any("RELIANCE" in str(k) and "LONG" in str(k) for k in keys)

    def test_entry_id_decoded_from_bytes(self) -> None:
        pub, _ = _make_publisher([1, b"PUBLISHED", b"stream-id-abc"])
        result = pub.publish(_make_result())
        assert result == "stream-id-abc"

    def test_entry_id_as_string(self) -> None:
        pub, _ = _make_publisher([1, "PUBLISHED", "stream-id-str"])
        result = pub.publish(_make_result())
        assert result == "stream-id-str"


class TestBuildProto:
    def test_proto_fields_populated(self) -> None:
        result = _make_result()
        msg = _build_proto(result, None)
        assert msg.symbol == "RELIANCE"
        assert msg.exchange == "NSE"
        assert msg.direction == "LONG"
        assert abs(msg.confidence - 0.78) < 0.001
        assert msg.strategy_id == "EMAVWAP1"
        assert "EMA" in msg.confirming_indicators
        assert "5m" in msg.confirming_timeframes
        assert msg.candlestick_pattern == "CDLHAMMER"
        assert msg.regime == "BULL_TREND"

    def test_strategy_id_truncated_to_8_chars(self) -> None:
        result = _make_result()
        r2 = SignalResult(
            **{**result.__dict__, "strategy_id": "VERYLONGSTRATEGYID"}
        )
        msg = _build_proto(r2, None)
        assert len(msg.strategy_id) <= 8

    def test_expiry_after_generated_at(self) -> None:
        result = _make_result()
        msg = _build_proto(result, None)
        assert msg.expires_at_ms > msg.generated_at_ms

    def test_signal_id_is_uuid(self) -> None:
        import uuid  # noqa: PLC0415

        result = _make_result()
        msg = _build_proto(result, None)
        parsed = uuid.UUID(msg.signal_id)  # raises if not valid UUID
        assert str(parsed) == msg.signal_id
