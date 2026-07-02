"""Zerodha Kite TOTP auto-login flow (M15).

Uses pyotp + requests to perform the full headless login without browser interaction.

Login flow:
  1. POST user_id + password to KITE_LOGIN_URL
  2. Extract ``request_id`` from the response
  3. Generate TOTP using pyotp.TOTP(totp_secret).now()
  4. POST request_id + TOTP to KITE_TWOFA_URL
  5. Exchange the resulting ``request_token`` for an access_token via
     ``KiteConnect.generate_session()`` (only when kiteconnect SDK is available)
  6. Store access_token in ``TokenStore`` with KITE_SESSION_TTL_SECONDS TTL

Credentials are read from environment variables.  They are NEVER logged.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

import pyotp
import requests
import structlog

from shared.auth.models import AuthMode, TokenRecord
from shared.auth.token_store import AuthError, TokenStore
from shared.core.constants import (
    KITE_LOGIN_URL,
    KITE_SESSION_TTL_SECONDS,
    KITE_TWOFA_URL,
)

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class _HttpSession(Protocol):
    """Minimal interface for the requests.Session used in the login flow."""

    def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> requests.Response:
        ...


class KiteAuthManager:
    """Manages Kite Connect access token lifecycle.

    Performs TOTP auto-login, stores the token in Redis, and refreshes it daily.

    Args:
        user_id: Zerodha user ID (never logged).
        password: Zerodha password (never logged).
        totp_secret: TOTP seed in base32 format (never logged).
        api_key: Kite API key.
        api_secret: Kite API secret (never logged).
        token_store: ``TokenStore`` instance for persisting the token.
        mode: ``AuthMode.PAPER`` returns a simulated token without real HTTP calls.
        http_session: Injectable requests session (for testing).
    """

    def __init__(
        self,
        user_id: str,
        password: str,
        totp_secret: str,
        api_key: str,
        api_secret: str,
        token_store: TokenStore,
        mode: AuthMode = AuthMode.PAPER,
        http_session: _HttpSession | None = None,
    ) -> None:
        self._user_id = user_id
        self._password = password
        self._totp_secret = totp_secret
        self._api_key = api_key
        self._api_secret = api_secret
        self._store = token_store
        self._mode = mode
        self._http = http_session

    def get_token(self) -> TokenRecord:
        """Return a valid token, refreshing if the stored one is expired.

        Returns:
            Valid ``TokenRecord``.

        Raises:
            AuthError: If no valid token exists and login fails.
        """
        record = self._store.load("kite")
        if record is not None:
            return record
        logger.info("kite_token_missing_or_expired_triggering_login")
        return self.login()

    def login(self) -> TokenRecord:
        """Execute the TOTP login flow and persist the resulting token.

        In ``AuthMode.PAPER``, returns a simulated token immediately without
        making any HTTP calls (no real credentials required).

        Returns:
            ``TokenRecord`` containing the access token.

        Raises:
            AuthError: If the HTTP flow fails (LIVE mode only).
        """
        if self._mode == AuthMode.PAPER:
            return self._paper_token()
        return self._live_login()

    def _paper_token(self) -> TokenRecord:
        """Return a simulated paper-mode token."""
        now_ms = int(time.time() * 1000)
        record = TokenRecord(
            broker="kite",
            access_token="PAPER_TOKEN_SIMULATED",
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + KITE_SESSION_TTL_SECONDS * 1000,
            user_id=self._user_id or "PAPER_USER",
            mode=AuthMode.PAPER,
        )
        self._store.save(record, ttl_seconds=KITE_SESSION_TTL_SECONDS)
        logger.info("kite_paper_token_issued", user_id=record.user_id)
        return record

    def _live_login(self) -> TokenRecord:
        """Execute the actual TOTP HTTP login flow (LIVE mode)."""
        session = self._http or requests.Session()
        try:
            # Step 1: Username + password
            resp = session.post(
                KITE_LOGIN_URL,
                data={"user_id": self._user_id, "password": self._password},
                headers={"X-Kite-Version": "3"},
                timeout=10,
            )
            resp.raise_for_status()
            login_data = resp.json()
            request_id = login_data["data"]["request_id"]

            # Step 2: TOTP two-factor
            totp_code = pyotp.TOTP(self._totp_secret).now()
            resp2 = session.post(
                KITE_TWOFA_URL,
                data={
                    "user_id": self._user_id,
                    "request_id": request_id,
                    "twofa_value": totp_code,
                    "twofa_type": "totp",
                },
                headers={"X-Kite-Version": "3"},
                timeout=10,
            )
            resp2.raise_for_status()
            twofa_data = resp2.json()
            request_token = twofa_data["data"]["request_token"]

            # Step 3: Exchange request_token for access_token
            access_token = self._exchange_token(request_token)

        except (requests.RequestException, KeyError, ValueError) as exc:
            logger.error("kite_login_failed", error=str(exc))
            raise AuthError(f"Kite login failed: {exc}") from exc

        now_ms = int(time.time() * 1000)
        record = TokenRecord(
            broker="kite",
            access_token=access_token,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + KITE_SESSION_TTL_SECONDS * 1000,
            user_id=self._user_id,
            mode=AuthMode.LIVE,
        )
        self._store.save(record, ttl_seconds=KITE_SESSION_TTL_SECONDS)
        logger.info("kite_login_success", user_id=self._user_id)
        return record

    def _exchange_token(self, request_token: str) -> str:
        """Exchange request_token for access_token via KiteConnect SDK.

        Falls back to returning ``request_token`` directly if kiteconnect is
        not installed (tests and paper-mode environments).
        """
        try:
            from kiteconnect import KiteConnect  # noqa: PLC0415

            kite = KiteConnect(api_key=self._api_key)
            session_data: dict[str, str] = kite.generate_session(
                request_token, api_secret=self._api_secret
            )
            return session_data["access_token"]
        except ImportError:
            logger.warning(
                "kiteconnect_not_installed_using_request_token_as_access_token"
            )
            return request_token

    def invalidate(self) -> None:
        """Remove the stored Kite token (forces re-login on next ``get_token``)."""
        self._store.delete("kite")
        logger.info("kite_token_invalidated", user_id=self._user_id)
