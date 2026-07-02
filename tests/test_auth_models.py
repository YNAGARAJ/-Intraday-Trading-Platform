"""Unit tests for shared.auth.models (M15)."""

from __future__ import annotations

import time

import pytest

from shared.auth.models import AuthMode, IBKRClientSlot, TokenRecord


class TestAuthMode:
    def test_values(self) -> None:
        assert AuthMode.PAPER == "PAPER"
        assert AuthMode.LIVE == "LIVE"

    def test_is_str(self) -> None:
        assert isinstance(AuthMode.PAPER, str)


class TestTokenRecord:
    def _make(self, **kwargs: object) -> TokenRecord:
        now_ms = int(time.time() * 1000)
        defaults: dict[str, object] = {
            "broker": "kite",
            "access_token": "TOK",
            "issued_at_ms": now_ms,
            "expires_at_ms": now_ms + 10_000,
            "user_id": "U1",
            "mode": AuthMode.PAPER,
        }
        defaults.update(kwargs)
        return TokenRecord(**defaults)  # type: ignore[arg-type]

    def test_is_valid_fresh(self) -> None:
        rec = self._make()
        assert rec.is_valid(int(time.time() * 1000))

    def test_is_valid_expired(self) -> None:
        now_ms = int(time.time() * 1000)
        rec = self._make(issued_at_ms=now_ms - 20_000, expires_at_ms=now_ms - 1)
        assert not rec.is_valid(now_ms)

    def test_is_valid_at_boundary(self) -> None:
        now_ms = int(time.time() * 1000)
        rec = self._make(expires_at_ms=now_ms)
        assert not rec.is_valid(now_ms)

    def test_repr_hides_token(self) -> None:
        rec = self._make(access_token="SECRET_TOKEN_VALUE")
        assert "SECRET_TOKEN_VALUE" not in repr(rec)

    def test_repr_shows_broker(self) -> None:
        rec = self._make(broker="kite")
        assert "kite" in repr(rec)

    def test_frozen(self) -> None:
        rec = self._make()
        with pytest.raises((AttributeError, TypeError)):
            rec.broker = "other"  # type: ignore[misc]

    def test_mode_paper(self) -> None:
        rec = self._make(mode=AuthMode.PAPER)
        assert rec.mode == AuthMode.PAPER

    def test_mode_live(self) -> None:
        rec = self._make(mode=AuthMode.LIVE)
        assert rec.mode == AuthMode.LIVE


class TestIBKRClientSlot:
    def _make(self, **kwargs: object) -> IBKRClientSlot:
        defaults: dict[str, object] = {
            "client_id": 1,
            "host": "127.0.0.1",
            "port": 7497,
        }
        defaults.update(kwargs)
        return IBKRClientSlot(**defaults)  # type: ignore[arg-type]

    def test_default_not_in_use(self) -> None:
        slot = self._make()
        assert not slot.in_use

    def test_acquire(self) -> None:
        slot = self._make()
        slot.acquire()
        assert slot.in_use

    def test_release(self) -> None:
        slot = self._make()
        slot.acquire()
        slot.release()
        assert not slot.in_use

    def test_release_keeps_connection_intact(self) -> None:
        slot = self._make()
        obj = object()
        slot.connection = obj
        slot.release()
        assert slot.connection is obj  # pool.shutdown() clears it, not release()

    def test_acquire_twice_is_idempotent(self) -> None:
        slot = self._make()
        slot.acquire()
        slot.acquire()
        assert slot.in_use
