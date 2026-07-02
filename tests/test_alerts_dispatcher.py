"""Tests for M20 AlertDispatcher."""

from __future__ import annotations

import pytest

from shared.alerts.dispatcher import AlertDispatcher, _format_alert
from shared.alerts.models import Alert, AlertLevel, AlertType


class _FakeTelegram:
    def __init__(self, returns: bool = True) -> None:
        self.messages: list[str] = []
        self._returns = returns

    def send(self, message: str) -> bool:
        self.messages.append(message)
        return self._returns


class _FakeEmail:
    def __init__(self) -> None:
        self.reports: list[tuple[str, str, bytes | None]] = []

    def send_daily_report(
        self, subject: str, body: str, pdf_bytes: bytes | None = None
    ) -> bool:
        self.reports.append((subject, body, pdf_bytes))
        return True


def _alert(
    atype: AlertType = AlertType.PNL, level: AlertLevel = AlertLevel.INFO
) -> Alert:
    return Alert(atype, level, "test message")


class TestFormatAlert:
    def test_includes_level(self) -> None:
        a = _alert(level=AlertLevel.CRITICAL)
        msg = _format_alert(a)
        assert "CRITICAL" in msg

    def test_includes_type(self) -> None:
        a = _alert(atype=AlertType.KILL_SWITCH)
        msg = _format_alert(a)
        assert "KILL_SWITCH" in msg

    def test_includes_message_text(self) -> None:
        a = Alert(AlertType.SIGNAL, AlertLevel.INFO, "entry signal RELIANCE")
        msg = _format_alert(a)
        assert "entry signal RELIANCE" in msg

    def test_includes_timestamp(self) -> None:
        a = _alert()
        msg = _format_alert(a)
        assert "ts=" in msg


class TestDispatch:
    def test_no_channels_returns_false(self) -> None:
        d = AlertDispatcher()
        assert d.dispatch(_alert()) is False

    def test_telegram_success_returns_true(self) -> None:
        tg = _FakeTelegram(returns=True)
        d = AlertDispatcher(telegram=tg)
        assert d.dispatch(_alert()) is True

    def test_telegram_failure_returns_false(self) -> None:
        tg = _FakeTelegram(returns=False)
        d = AlertDispatcher(telegram=tg)
        assert d.dispatch(_alert()) is False

    def test_telegram_receives_formatted_message(self) -> None:
        tg = _FakeTelegram()
        d = AlertDispatcher(telegram=tg)
        d.dispatch(_alert(atype=AlertType.FILL))
        assert "FILL" in tg.messages[0]

    def test_rate_limit_blocks_excess_messages(self) -> None:
        tg = _FakeTelegram()
        limit = 5
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=limit)
        for _ in range(limit):
            d.dispatch(_alert())
        result = d.dispatch(_alert())
        assert result is False
        assert len(tg.messages) == limit

    def test_rate_limit_allows_up_to_limit(self) -> None:
        tg = _FakeTelegram()
        limit = 3
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=limit)
        results = [d.dispatch(_alert()) for _ in range(limit)]
        assert all(results)
        assert len(tg.messages) == limit

    def test_kill_switch_bypasses_rate_limit(self) -> None:
        tg = _FakeTelegram()
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=0)
        a = Alert(AlertType.KILL_SWITCH, AlertLevel.CRITICAL, "kill!")
        assert d.dispatch(a) is True
        assert len(tg.messages) == 1

    def test_circuit_breaker_bypasses_rate_limit(self) -> None:
        tg = _FakeTelegram()
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=0)
        a = Alert(AlertType.CIRCUIT_BREAKER, AlertLevel.CRITICAL, "cb!")
        assert d.dispatch(a) is True

    def test_normal_alert_blocked_at_zero_limit(self) -> None:
        tg = _FakeTelegram()
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=0)
        assert d.dispatch(_alert(atype=AlertType.PNL)) is False

    def test_rate_counter_increments_on_success(self) -> None:
        tg = _FakeTelegram(returns=True)
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=10)
        for _ in range(5):
            d.dispatch(_alert())
        assert len(d._send_times) == 5

    def test_rate_counter_not_incremented_on_failure(self) -> None:
        tg = _FakeTelegram(returns=False)
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=10)
        d.dispatch(_alert())
        assert len(d._send_times) == 0

    @pytest.mark.parametrize(
        "atype",
        [
            AlertType.SIGNAL,
            AlertType.FILL,
            AlertType.ERROR,
            AlertType.RECONCILIATION_MISMATCH,
        ],
    )
    def test_various_types_dispatched(self, atype: AlertType) -> None:
        tg = _FakeTelegram()
        d = AlertDispatcher(telegram=tg, rate_limit_per_minute=20)
        assert d.dispatch(Alert(atype, AlertLevel.INFO, "msg")) is True


class TestDispatchDailyReport:
    def test_no_email_channel_returns_false(self) -> None:
        d = AlertDispatcher()
        assert d.dispatch_daily_report("S", "B") is False

    def test_email_channel_receives_args(self) -> None:
        em = _FakeEmail()
        d = AlertDispatcher(email=em)
        d.dispatch_daily_report("Daily", "body text", pdf_bytes=b"pdf")
        assert em.reports[0] == ("Daily", "body text", b"pdf")

    def test_returns_true_on_success(self) -> None:
        em = _FakeEmail()
        d = AlertDispatcher(email=em)
        assert d.dispatch_daily_report("S", "B") is True

    def test_pdf_bytes_none_when_not_provided(self) -> None:
        em = _FakeEmail()
        d = AlertDispatcher(email=em)
        d.dispatch_daily_report("S", "B")
        assert em.reports[0][2] is None
