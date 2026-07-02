"""Tests for M20 EmailAlerter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.alerts.email_sender import EmailAlerter
from shared.alerts.models import Alert, AlertLevel, AlertType


def _make_alerter(
    host: str = "smtp.test",
    port: int = 587,
    username: str = "user",
    password: str = "pass",
    from_addr: str = "from@test.com",
    to_addrs: list[str] | None = None,
) -> EmailAlerter:
    return EmailAlerter(
        smtp_host=host,
        smtp_port=port,
        username=username,
        password=password,
        from_addr=from_addr,
        to_addrs=to_addrs or ["to@test.com"],
    )


class TestBuildPdf:
    def test_returns_bytes(self) -> None:
        ea = _make_alerter()
        data = ea.build_pdf("Report", ["line 1", "line 2"])
        assert isinstance(data, bytes)

    def test_non_empty_output(self) -> None:
        ea = _make_alerter()
        data = ea.build_pdf("Title", ["content"])
        assert len(data) > 100

    def test_pdf_header_signature(self) -> None:
        ea = _make_alerter()
        data = ea.build_pdf("T", [])
        assert data[:4] == b"%PDF"

    def test_empty_lines_accepted(self) -> None:
        ea = _make_alerter()
        data = ea.build_pdf("Empty", [])
        assert len(data) > 0

    def test_many_lines(self) -> None:
        ea = _make_alerter()
        lines = [f"Line {i}: value={i*100}" for i in range(20)]
        data = ea.build_pdf("Multi", lines)
        assert isinstance(data, bytes) and len(data) > 0


class TestSendDailyReport:
    def _smtp_mock(self) -> MagicMock:
        instance = MagicMock()
        return instance

    def test_returns_true_on_success(self) -> None:
        ea = _make_alerter()
        with patch("smtplib.SMTP") as mock_smtp:
            instance = self._smtp_mock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            result = ea.send_daily_report("Subject", "Body")
        assert result is True

    def test_returns_false_when_host_empty(self) -> None:
        ea = _make_alerter(host="")
        assert ea.send_daily_report("S", "B") is False

    def test_returns_false_when_to_addrs_empty(self) -> None:
        ea = _make_alerter(to_addrs=[])
        assert ea.send_daily_report("S", "B") is False

    def test_smtp_error_returns_false(self) -> None:
        ea = _make_alerter()
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            result = ea.send_daily_report("S", "B")
        assert result is False

    def test_starttls_called(self) -> None:
        ea = _make_alerter()
        with patch("smtplib.SMTP") as mock_smtp:
            instance = self._smtp_mock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            ea.send_daily_report("S", "B")
        instance.starttls.assert_called_once()

    def test_login_called_when_username_set(self) -> None:
        ea = _make_alerter(username="user", password="pass")
        with patch("smtplib.SMTP") as mock_smtp:
            instance = self._smtp_mock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            ea.send_daily_report("S", "B")
        instance.login.assert_called_once_with("user", "pass")

    def test_login_not_called_when_username_empty(self) -> None:
        ea = _make_alerter(username="")
        with patch("smtplib.SMTP") as mock_smtp:
            instance = self._smtp_mock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            ea.send_daily_report("S", "B")
        instance.login.assert_not_called()

    def test_pdf_attachment_included(self) -> None:
        ea = _make_alerter()
        pdf = b"%PDF-1.4 fake bytes"
        with patch("smtplib.SMTP") as mock_smtp:
            instance = self._smtp_mock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            result = ea.send_daily_report("S", "B", pdf_bytes=pdf)
        assert result is True
        # sendmail called with a message that contains attachment
        call_args = instance.sendmail.call_args
        raw_message: str = call_args[0][2]
        assert "daily_report.pdf" in raw_message

    def test_sendmail_called_with_correct_from(self) -> None:
        ea = _make_alerter(from_addr="sender@x.com")
        with patch("smtplib.SMTP") as mock_smtp:
            instance = self._smtp_mock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            ea.send_daily_report("S", "B")
        args = instance.sendmail.call_args[0]
        assert args[0] == "sender@x.com"


class TestSendMethod:
    def test_send_calls_send_daily_report(self) -> None:
        ea = _make_alerter()
        with patch("smtplib.SMTP") as mock_smtp:
            instance = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            result = ea.send("some alert message")
        assert result is True

    def test_send_returns_false_when_not_configured(self) -> None:
        ea = _make_alerter(host="")
        assert ea.send("msg") is False


class TestFromAlert:
    def test_includes_alert_type(self) -> None:
        a = Alert(AlertType.KILL_SWITCH, AlertLevel.CRITICAL, "halted")
        body = EmailAlerter.from_alert(a)
        assert "KILL_SWITCH" in body

    def test_includes_level(self) -> None:
        a = Alert(AlertType.ERROR, AlertLevel.WARNING, "warn")
        body = EmailAlerter.from_alert(a)
        assert "WARNING" in body

    def test_includes_message(self) -> None:
        a = Alert(AlertType.PNL, AlertLevel.INFO, "profit 500")
        body = EmailAlerter.from_alert(a)
        assert "profit 500" in body

    def test_includes_metadata(self) -> None:
        a = Alert(
            AlertType.FILL,
            AlertLevel.INFO,
            "filled",
            metadata={"symbol": "RELIANCE"},
        )
        body = EmailAlerter.from_alert(a)
        assert "RELIANCE" in body

    def test_no_metadata_section_when_empty(self) -> None:
        a = Alert(AlertType.SIGNAL, AlertLevel.INFO, "sig")
        body = EmailAlerter.from_alert(a)
        assert "Context" not in body

    @pytest.mark.parametrize(
        "atype,level",
        [
            (AlertType.CIRCUIT_BREAKER, AlertLevel.CRITICAL),
            (AlertType.RECONCILIATION_MISMATCH, AlertLevel.WARNING),
        ],
    )
    def test_all_alert_types_render(self, atype: AlertType, level: AlertLevel) -> None:
        a = Alert(atype, level, "test")
        body = EmailAlerter.from_alert(a)
        assert atype.value in body
