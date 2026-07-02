"""M20 Alerting & Notification — Telegram Bot API channel.

Uses raw HTTP (requests library) to avoid adding the python-telegram-bot SDK.
Bot token and chat ID are never logged.
"""

from __future__ import annotations

from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class _HttpResponse(Protocol):
    """Structural protocol matching requests.Response (subset used here)."""

    @property
    def status_code(self) -> int:
        """HTTP response status code."""
        ...


class _HttpSession(Protocol):
    """Structural protocol for an injectable HTTP session (matches requests.Session)."""

    def post(
        self, url: str, *, json: dict[str, str], timeout: float
    ) -> _HttpResponse:
        """POST JSON body to url and return a response-like object."""
        ...


class TelegramAlerter:
    """Posts alert messages to a Telegram chat via the Bot API.

    Args:
        bot_token: Telegram Bot token (never logged).
        chat_id: Target chat or channel ID.
        http_session: Injectable HTTP session for testing; falls back to
            raw ``requests.post`` when None.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        http_session: _HttpSession | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._session = http_session

    def send(self, message: str) -> bool:
        """Post a plain-text (HTML-formatted) message to Telegram.

        Args:
            message: Text to send (Telegram limit: 4096 chars).

        Returns:
            True if the Bot API returned HTTP 200, False otherwise.
        """
        if not self._token or not self._chat_id:
            logger.warning("telegram_not_configured")
            return False
        url = _API_URL.format(token=self._token)
        payload: dict[str, str] = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        try:
            if self._session is not None:
                resp = self._session.post(url, json=payload, timeout=5.0)
            else:
                import requests

                resp = requests.post(url, json=payload, timeout=5.0)
            ok = resp.status_code == 200
            if not ok:
                logger.warning("telegram_send_failed", status=resp.status_code)
            return ok
        except Exception as exc:
            logger.warning("telegram_send_error", error=str(exc))
            return False
