"""Tests for M17 MismatchPublisher."""

from __future__ import annotations

from shared.reconciliation.models import MismatchField, ReconciliationMismatch
from shared.reconciliation.publisher import MismatchPublisher

NOW_MS = 1_700_000_000_000

_SAMPLE = ReconciliationMismatch(
    symbol="RELIANCE",
    exchange="NSE",
    field=MismatchField.QUANTITY,
    internal_value="10",
    broker_value="5",
    detected_at_ms=NOW_MS,
)


class TestMismatchPublisher:
    def test_no_redis_returns_none(self) -> None:
        pub = MismatchPublisher(redis_client=None)
        assert pub.publish(_SAMPLE) is None

    def test_publish_returns_entry_id(self) -> None:
        published: list[dict[str, object]] = []

        class FakeStream:
            def xadd(
                self,
                name: str,
                fields: dict[str, object],
                id: str = "*",
                maxlen: int | None = None,
            ) -> bytes:
                published.append({"name": name, "fields": fields})
                return b"1234-0"

        pub = MismatchPublisher(redis_client=FakeStream())  # type: ignore[arg-type]
        eid = pub.publish(_SAMPLE)
        assert eid == "b'1234-0'"
        assert len(published) == 1

    def test_publish_includes_symbol_and_field(self) -> None:
        captured: list[dict[str, object]] = []

        class FakeStream:
            def xadd(
                self,
                name: str,
                fields: dict[str, object],
                id: str = "*",
                maxlen: int | None = None,
            ) -> bytes:
                captured.append(fields)
                return b"1235-0"

        pub = MismatchPublisher(redis_client=FakeStream())  # type: ignore[arg-type]
        pub.publish(_SAMPLE)
        assert captured[0]["symbol"] == "RELIANCE"
        assert captured[0]["field"] == "quantity"
        assert captured[0]["exchange"] == "NSE"

    def test_redis_error_returns_none(self) -> None:
        class BrokenStream:
            def xadd(
                self,
                name: str,
                fields: dict[str, object],
                id: str = "*",
                maxlen: int | None = None,
            ) -> bytes:
                raise ConnectionError("redis down")

        pub = MismatchPublisher(redis_client=BrokenStream())  # type: ignore[arg-type]
        result = pub.publish(_SAMPLE)
        assert result is None

    def test_publish_all_returns_entry_ids(self) -> None:
        counter = {"n": 0}

        class FakeStream:
            def xadd(
                self,
                name: str,
                fields: dict[str, object],
                id: str = "*",
                maxlen: int | None = None,
            ) -> bytes:
                counter["n"] += 1
                return f"{counter['n']}-0".encode()

        pub = MismatchPublisher(redis_client=FakeStream())  # type: ignore[arg-type]
        mm2 = ReconciliationMismatch(
            symbol="TCS",
            exchange="NSE",
            field=MismatchField.AVG_PRICE,
            internal_value="3500.00",
            broker_value="3550.00",
            detected_at_ms=NOW_MS,
        )
        eids = pub.publish_all([_SAMPLE, mm2])
        assert len(eids) == 2

    def test_publish_all_no_redis(self) -> None:
        pub = MismatchPublisher(redis_client=None)
        mm2 = ReconciliationMismatch(
            symbol="WIPRO",
            exchange="NSE",
            field=MismatchField.POSITION_MISSING,
            internal_value="5",
            broker_value="0",
            detected_at_ms=NOW_MS,
        )
        eids = pub.publish_all([_SAMPLE, mm2])
        assert eids == []

    def test_custom_stream_key(self) -> None:
        captured_name: list[str] = []

        class FakeStream:
            def xadd(
                self,
                name: str,
                fields: dict[str, object],
                id: str = "*",
                maxlen: int | None = None,
            ) -> bytes:
                captured_name.append(name)
                return b"1-0"

        pub = MismatchPublisher(
            redis_client=FakeStream(),  # type: ignore[arg-type]
            stream_key="custom:stream",
        )
        pub.publish(_SAMPLE)
        assert captured_name[0] == "custom:stream"
