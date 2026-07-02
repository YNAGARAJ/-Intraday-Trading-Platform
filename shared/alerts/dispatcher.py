"""M20 Alerting & Notification — alert dispatcher with rate limiting.

KILL_SWITCH and CIRCUIT_BREAKER alerts bypass the per-minute rate limit (RULE 8).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Protocol

import structlog

from shared.alerts.models import Alert, AlertType
from shared.core.constants import ALERT_TELEGRAM_RATE_LIMIT_PER_MINUTE

logger = structlog.get_logger(__name__)

# Alert types that must NEVER be suppressed by rate limiting — kill switch and
# circuit breaker are safety-critical; missing one is worse than spam.
_BYPASS_RATE_LIMIT: frozenset[AlertType] = frozenset(
    {AlertType.KILL_SWITCH, AlertType.CIRCUIT_BREAKER}
)


class _AlertChannel(Protocol):
    """Structural protocol for real-time text alert channels (Telegram, SMS, etc.)."""

    def send(self, message: str) -> bool:
        """Send a plain-text message to this channel."""
        ...


class _EmailChannel(Protocol):
    """Structural protocol for the email/report channel."""

    def send_daily_report(
        self, subject: str, body: str, pdf_bytes: bytes | None = None
    ) -> bool:
        """Send an email with an optional PDF attachment."""
        ...


def _format_alert(alert: Alert) -> str:
    """Format an Alert as a plain-text string for real-time channels."""
    ts = int(alert.timestamp_ms / 1000)
    return (
        f"[{alert.level.value}][{alert.alert_type.value}] "
        f"{alert.message} (ts={ts})"
    )


class AlertDispatcher:
    """Routes Alert objects to Telegram and/or email channels with rate limiting.

    Real-time alerts (all types) go to the Telegram channel.
    The daily report goes to the email channel via ``dispatch_daily_report``.

    KILL_SWITCH and CIRCUIT_BREAKER alerts bypass the per-minute rate limit.

    Args:
        telegram: Telegram channel (optional).
        email: Email channel (optional).
        rate_limit_per_minute: Max Telegram dispatches per 60-second window.
    """

    def __init__(
        self,
        telegram: _AlertChannel | None = None,
        email: _EmailChannel | None = None,
        rate_limit_per_minute: int = ALERT_TELEGRAM_RATE_LIMIT_PER_MINUTE,
    ) -> None:
        self._telegram = telegram
        self._email = email
        self._rate_limit = rate_limit_per_minute
        self._send_times: deque[float] = deque()

    def _is_rate_limited(self) -> bool:
        now = time.time()
        while self._send_times and self._send_times[0] < now - 60.0:
            self._send_times.popleft()
        return len(self._send_times) >= self._rate_limit

    def dispatch(self, alert: Alert) -> bool:
        """Route an alert to the Telegram channel.

        Args:
            alert: Alert to dispatch.

        Returns:
            True if Telegram accepted the message, False otherwise.
        """
        bypass = alert.alert_type in _BYPASS_RATE_LIMIT
        if not bypass and self._is_rate_limited():
            logger.warning(
                "alert_rate_limited",
                alert_type=alert.alert_type.value,
                level=alert.level.value,
            )
            return False

        if self._telegram is None:
            logger.debug("alert_no_telegram_channel", alert_type=alert.alert_type.value)
            return False

        message = _format_alert(alert)
        ok = self._telegram.send(message)
        if ok:
            self._send_times.append(time.time())
        logger.info(
            "alert_dispatched",
            alert_type=alert.alert_type.value,
            level=alert.level.value,
            ok=ok,
        )
        return ok

    def dispatch_daily_report(
        self,
        subject: str,
        body: str,
        pdf_bytes: bytes | None = None,
    ) -> bool:
        """Send the daily report via the email channel.

        Args:
            subject: Email subject line.
            body: Email plain-text body.
            pdf_bytes: Optional PDF attachment bytes.

        Returns:
            True on success, False if no email channel configured or send fails.
        """
        if self._email is None:
            logger.warning("daily_report_no_email_channel")
            return False
        return self._email.send_daily_report(
            subject=subject, body=body, pdf_bytes=pdf_bytes
        )
