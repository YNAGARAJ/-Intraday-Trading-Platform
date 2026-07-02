"""Unit tests for shared.auth.token_store (M15)."""

from __future__ import annotations

import time

import pytest

from shared.auth.models import AuthMode, TokenRecord
from shared.auth.token_store import AuthError, TokenStore


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, int | None]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        self._store[name] = (value, ex)
        return True

    def get(self, name: str) -> bytes | None:
        entry = self._store.get(name)
        return entry[0].encode() if entry else None

    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._store:
                del self._store[n]
                count += 1
        return count

    def get_stored_ttl(self, name: str) -> int | None:
        entry = self._store.get(name)
        return entry[1] if entry else None


def _record(
    broker: str = "kite",
    token: str = "TOK",
    mode: AuthMode = AuthMode.PAPER,
    offset_ms: int = 10_000,
) -> TokenRecord:
    now_ms = int(time.time() * 1000)
    return TokenRecord(
        broker=broker,
        access_token=token,
        issued_at_ms=now_ms,
        expires_at_ms=now_ms + offset_ms,
        user_id="U1",
        mode=mode,
    )


class TestTokenStore:
    def test_save_and_load_redis(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        rec = _record()
        store.save(rec, ttl_seconds=3600)
        loaded = store.load("kite")
        assert loaded is not None
        assert loaded.access_token == "TOK"

    def test_load_returns_none_when_missing(self) -> None:
        store = TokenStore(redis_client=_FakeRedis())
        assert store.load("kite") is None

    def test_load_returns_none_for_expired(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        now_ms = int(time.time() * 1000)
        expired = TokenRecord(
            broker="kite",
            access_token="OLD",
            issued_at_ms=now_ms - 20_000,
            expires_at_ms=now_ms - 1,
            user_id="U",
            mode=AuthMode.PAPER,
        )
        store.save(expired, ttl_seconds=3600)
        loaded = store.load("kite")
        assert loaded is None

    def test_save_stores_with_correct_ttl(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        store.save(_record(), ttl_seconds=7200)
        ttl = redis.get_stored_ttl("auth:kite:access_token")
        assert ttl == 7200

    def test_delete_removes_token(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        store.save(_record(), ttl_seconds=3600)
        store.delete("kite")
        assert store.load("kite") is None

    def test_in_memory_fallback_no_redis(self) -> None:
        store = TokenStore(redis_client=None)
        rec = _record()
        store.save(rec, ttl_seconds=3600)
        loaded = store.load("kite")
        assert loaded is not None
        assert loaded.access_token == "TOK"

    def test_in_memory_delete(self) -> None:
        store = TokenStore(redis_client=None)
        store.save(_record(), ttl_seconds=3600)
        store.delete("kite")
        assert store.load("kite") is None

    def test_load_different_broker(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        store.save(_record(broker="kite"), ttl_seconds=3600)
        assert store.load("ibkr") is None

    def test_auth_error_is_exception(self) -> None:
        with pytest.raises(AuthError):
            raise AuthError("no token")

    def test_broker_serialised_correctly(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        store.save(_record(broker="kite", token="ABC"), ttl_seconds=3600)
        loaded = store.load("kite")
        assert loaded is not None
        assert loaded.broker == "kite"

    def test_mode_round_trips(self) -> None:
        redis = _FakeRedis()
        store = TokenStore(redis_client=redis)
        store.save(_record(mode=AuthMode.LIVE), ttl_seconds=3600)
        loaded = store.load("kite")
        assert loaded is not None
        assert loaded.mode == AuthMode.LIVE
