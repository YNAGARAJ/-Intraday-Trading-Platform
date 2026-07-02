"""Daily token refresh scheduler for M15.

Schedules a daily re-login at 08:30 IST (``KITE_DAILY_REFRESH_IST_HOUR:MINUTE``)
using a background ``threading.Timer``.  No APScheduler
dependency required.

The scheduler is fire-and-forget: if the refresh fails, it logs the error and the
next tick will retry.  The ``KiteAuthManager.get_token()`` call path handles
on-demand re-login whenever the token is found to be expired or missing.
"""

from __future__ import annotations

import datetime
import threading
import time
from collections.abc import Callable
from zoneinfo import ZoneInfo

import structlog

from shared.core.constants import (
    KITE_DAILY_REFRESH_IST_HOUR,
    KITE_DAILY_REFRESH_IST_MINUTE,
)

logger = structlog.get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_ONE_DAY_SECONDS: int = 86_400


def _seconds_until(hour: int, minute: int, tz: ZoneInfo) -> float:
    """Return seconds from now until the next occurrence of hour:minute in tz."""
    now = datetime.datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


class DailyRefreshScheduler:
    """Fires a callback once per day at the configured IST time.

    Args:
        callback: Zero-argument callable invoked at each scheduled tick.
            Should call ``KiteAuthManager.login()`` (or equivalent).
        refresh_hour: Hour (IST) for the daily refresh (default 08).
        refresh_minute: Minute (IST) for the daily refresh (default 30).
    """

    def __init__(
        self,
        callback: Callable[[], None],
        refresh_hour: int = KITE_DAILY_REFRESH_IST_HOUR,
        refresh_minute: int = KITE_DAILY_REFRESH_IST_MINUTE,
    ) -> None:
        self._callback = callback
        self._hour = refresh_hour
        self._minute = refresh_minute
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        """Schedule the first tick and start the recurring cycle."""
        if self._running:
            return
        self._running = True
        self._schedule_next()
        logger.info(
            "daily_refresh_scheduler_started",
            refresh_ist=f"{self._hour:02d}:{self._minute:02d}",
        )

    def stop(self) -> None:
        """Cancel any pending timer and stop the scheduler."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("daily_refresh_scheduler_stopped")

    def _schedule_next(self) -> None:
        if not self._running:
            return
        delay = _seconds_until(self._hour, self._minute, _IST)
        self._timer = threading.Timer(delay, self._fire)
        self._timer.daemon = True
        self._timer.start()
        logger.debug("daily_refresh_scheduled", delay_seconds=round(delay))

    def _fire(self) -> None:
        fired_at = time.time()
        try:
            self._callback()
            logger.info("daily_refresh_completed", fired_at_ms=int(fired_at * 1000))
        except Exception as exc:  # noqa: BLE001
            logger.error("daily_refresh_failed", error=str(exc))
        finally:
            self._schedule_next()  # reschedule unconditionally
