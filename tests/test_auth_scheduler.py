"""Unit tests for shared.auth.scheduler (M15)."""

from __future__ import annotations

import threading
import time

from shared.auth.scheduler import DailyRefreshScheduler, _seconds_until
from zoneinfo import ZoneInfo


class TestSecondsUntil:
    def test_returns_positive_value(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")
        delay = _seconds_until(8, 30, tz)
        assert delay > 0

    def test_within_one_day(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")
        delay = _seconds_until(8, 30, tz)
        assert delay <= 86_400


class TestDailyRefreshScheduler:
    def test_callback_fires_on_direct_call(self) -> None:
        fired: list[bool] = []
        scheduler = DailyRefreshScheduler(callback=lambda: fired.append(True))
        scheduler._fire()
        scheduler.stop()
        assert len(fired) == 1

    def test_start_creates_timer(self) -> None:
        scheduler = DailyRefreshScheduler(callback=lambda: None)
        scheduler.start()
        assert scheduler._timer is not None
        scheduler.stop()

    def test_stop_cancels_timer(self) -> None:
        scheduler = DailyRefreshScheduler(callback=lambda: None)
        scheduler.start()
        scheduler.stop()
        assert scheduler._timer is None

    def test_double_start_is_idempotent(self) -> None:
        scheduler = DailyRefreshScheduler(callback=lambda: None)
        scheduler.start()
        timer_a = scheduler._timer
        scheduler.start()
        timer_b = scheduler._timer
        assert timer_a is timer_b
        scheduler.stop()

    def test_fire_reschedules(self) -> None:
        scheduler = DailyRefreshScheduler(callback=lambda: None)
        scheduler._running = True
        scheduler._fire()
        assert scheduler._timer is not None
        scheduler.stop()

    def test_callback_exception_does_not_prevent_reschedule(self) -> None:
        def bad_cb() -> None:
            raise RuntimeError("boom")

        scheduler = DailyRefreshScheduler(callback=bad_cb)
        scheduler._running = True
        scheduler._fire()
        assert scheduler._timer is not None
        scheduler.stop()

    def test_timer_thread_is_daemon(self) -> None:
        scheduler = DailyRefreshScheduler(callback=lambda: None)
        scheduler.start()
        assert scheduler._timer is not None
        assert scheduler._timer.daemon is True
        scheduler.stop()

    def test_custom_hour_minute(self) -> None:
        scheduler = DailyRefreshScheduler(
            callback=lambda: None, refresh_hour=9, refresh_minute=0
        )
        assert scheduler._hour == 9
        assert scheduler._minute == 0
