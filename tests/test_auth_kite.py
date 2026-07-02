"""Unit tests for shared.auth.kite_auth (M15)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from shared.auth.kite_auth import KiteAuthManager
from shared.auth.models import AuthMode, TokenRecord
from shared.auth.token_store import AuthError, TokenStore


def _mgr(
    mode: AuthMode = AuthMode.PAPER,
    http_session: object | None = None,
    token_store: TokenStore | None = None,
) -> KiteAuthManager:
    return KiteAuthManager(
        user_id="TEST_USER",
        password="pass",
        totp_secret="JBSWY3DPEHPK3PXP",
        api_key="api_key",
        api_secret="api_secret",
        token_store=token_store or TokenStore(),
        mode=mode,
        http_session=http_session,  # type: ignore[arg-type]
    )


class TestKiteAuthManagerPaper:
    def test_login_returns_paper_token(self) -> None:
        rec = _mgr().login()
        assert rec.access_token == "PAPER_TOKEN_SIMULATED"
        assert rec.mode == AuthMode.PAPER

    def test_login_sets_broker(self) -> None:
        rec = _mgr().login()
        assert rec.broker == "kite"

    def test_login_sets_user_id(self) -> None:
        rec = _mgr().login()
        assert rec.user_id == "TEST_USER"

    def test_get_token_returns_cached(self) -> None:
        mgr = _mgr()
        r1 = mgr.get_token()
        r2 = mgr.get_token()
        assert r1.access_token == r2.access_token

    def test_invalidate_clears_token(self) -> None:
        store = TokenStore()
        mgr = _mgr(token_store=store)
        mgr.login()
        mgr.invalidate()
        assert store.load("kite") is None

    def test_get_token_after_invalidate_relogins(self) -> None:
        mgr = _mgr()
        mgr.get_token()
        mgr.invalidate()
        rec = mgr.get_token()
        assert rec.access_token == "PAPER_TOKEN_SIMULATED"

    def test_token_validity(self) -> None:
        rec = _mgr().login()
        assert rec.is_valid(int(time.time() * 1000))

    def test_token_stored_in_provided_store(self) -> None:
        store = TokenStore()
        _mgr(token_store=store).login()
        assert store.load("kite") is not None


class TestKiteAuthManagerLive:
    def _mock_session(self) -> MagicMock:
        session = MagicMock()
        session.post.side_effect = [
            MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"data": {"request_id": "REQ1"}}),
            ),
            MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"data": {"request_token": "RTOK1"}}),
            ),
        ]
        return session

    def test_live_login_calls_http(self) -> None:
        session = self._mock_session()
        mgr = _mgr(mode=AuthMode.LIVE, http_session=session)
        rec = mgr.login()
        assert rec.mode == AuthMode.LIVE
        assert session.post.call_count == 2

    def test_live_login_token_contains_request_token(self) -> None:
        session = self._mock_session()
        mgr = _mgr(mode=AuthMode.LIVE, http_session=session)
        rec = mgr.login()
        # kiteconnect not installed — falls back to request_token
        assert "RTOK1" in rec.access_token

    def test_live_login_http_failure_raises_auth_error(self) -> None:
        import requests

        session = MagicMock()
        session.post.side_effect = requests.RequestException("connection refused")
        mgr = _mgr(mode=AuthMode.LIVE, http_session=session)
        with pytest.raises(AuthError):
            mgr.login()

    def test_live_login_bad_json_raises_auth_error(self) -> None:
        session = MagicMock()
        session.post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={}),
        )
        mgr = _mgr(mode=AuthMode.LIVE, http_session=session)
        with pytest.raises(AuthError):
            mgr.login()
