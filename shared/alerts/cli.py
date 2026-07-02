"""M20 Alerting & Notification — 20 VERIFY scenarios.

Run via: ``python -m shared.alerts``
"""

from __future__ import annotations

import time
from datetime import date
from typing import NoReturn
from unittest.mock import MagicMock, patch

import structlog

from shared.alerts.cost_alert import LLMCostAlerter
from shared.alerts.dispatcher import AlertDispatcher
from shared.alerts.email_sender import EmailAlerter
from shared.alerts.models import Alert, AlertLevel, AlertType
from shared.alerts.telegram import TelegramAlerter
from shared.core.constants import (
    ALERT_TELEGRAM_RATE_LIMIT_PER_MINUTE,
    LLM_COST_ALERT_THRESHOLD_USD,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _MockSession:
    def __init__(self, status_code: int = 200) -> None:
        self._code = status_code
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, *, json: dict[str, str], timeout: float) -> _MockResponse:
        self.calls.append((url, json))
        return _MockResponse(self._code)


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


class _FakeRedis:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = store or {}

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None


class _FakeDispatcher:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def dispatch(self, alert: Alert) -> bool:
        self.alerts.append(alert)
        return True


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _s01_alert_level_enum() -> bool:
    """S01: AlertLevel has INFO, WARNING, CRITICAL."""
    return {AlertLevel.INFO, AlertLevel.WARNING, AlertLevel.CRITICAL} == set(AlertLevel)


def _s02_alert_type_enum() -> bool:
    """S02: AlertType has all 10 expected values."""
    expected = {
        "SIGNAL", "FILL", "ERROR", "PNL", "CIRCUIT_BREAKER",
        "KILL_SWITCH", "RECONCILIATION_MISMATCH", "LLM_COST",
        "DEAD_LETTER", "HEARTBEAT",
    }
    return {t.value for t in AlertType} == expected


def _s03_alert_defaults() -> bool:
    """S03: Alert.timestamp_ms defaults to now, metadata defaults to empty dict."""
    before = time.time() * 1000
    a = Alert(alert_type=AlertType.SIGNAL, level=AlertLevel.INFO, message="hi")
    after = time.time() * 1000
    return before <= a.timestamp_ms <= after and a.metadata == {}


def _s04_alert_metadata() -> bool:
    """S04: Alert stores metadata key-value pairs."""
    a = Alert(
        alert_type=AlertType.FILL,
        level=AlertLevel.INFO,
        message="filled",
        metadata={"symbol": "RELIANCE", "qty": "100"},
    )
    return a.metadata["symbol"] == "RELIANCE" and a.metadata["qty"] == "100"


def _s05_telegram_send_success() -> bool:
    """S05: TelegramAlerter returns True when HTTP 200."""
    sess = _MockSession(200)
    ta = TelegramAlerter("token123", "chat456", http_session=sess)
    result = ta.send("hello")
    return result is True and len(sess.calls) == 1


def _s06_telegram_send_failure() -> bool:
    """S06: TelegramAlerter returns False when HTTP 429."""
    sess = _MockSession(429)
    ta = TelegramAlerter("token123", "chat456", http_session=sess)
    return ta.send("hello") is False


def _s07_telegram_empty_token() -> bool:
    """S07: TelegramAlerter returns False immediately when token is empty."""
    sess = _MockSession(200)
    ta = TelegramAlerter("", "chat456", http_session=sess)
    result = ta.send("hello")
    return result is False and len(sess.calls) == 0


def _s08_telegram_network_error() -> bool:
    """S08: TelegramAlerter returns False on network exception."""

    class _ErrorSession:
        def post(self, url: str, *, json: dict[str, str], timeout: float) -> NoReturn:
            raise ConnectionError("timeout")

    ta = TelegramAlerter("tok", "cid", http_session=_ErrorSession())
    return ta.send("hello") is False


def _s09_email_build_pdf() -> bool:
    """S09: EmailAlerter.build_pdf returns non-empty PDF bytes."""
    ea = EmailAlerter("h", 587, "u", "p", "f@x.com", ["t@x.com"])
    data = ea.build_pdf("Daily Report", ["P&L: +500", "Trades: 3"])
    return isinstance(data, bytes) and len(data) > 100


def _s10_email_send_daily_report() -> bool:
    """S10: EmailAlerter.send_daily_report calls SMTP stack correctly."""
    ea = EmailAlerter("smtp.test", 587, "user", "pass", "from@x.com", ["to@x.com"])
    with patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        result = ea.send_daily_report("Subject", "Body")
    return result is True


def _s11_email_not_configured() -> bool:
    """S11: EmailAlerter returns False when smtp_host is empty."""
    ea = EmailAlerter("", 587, "", "", "", ["to@x.com"])
    return ea.send_daily_report("S", "B") is False


def _s12_dispatcher_no_channels() -> bool:
    """S12: AlertDispatcher with no channels returns False."""
    d = AlertDispatcher()
    a = Alert(AlertType.SIGNAL, AlertLevel.INFO, "signal")
    return d.dispatch(a) is False


def _s13_dispatcher_telegram_channel() -> bool:
    """S13: AlertDispatcher routes to Telegram; returns True on success."""
    tg = _FakeTelegram(returns=True)
    d = AlertDispatcher(telegram=tg)
    a = Alert(AlertType.FILL, AlertLevel.INFO, "fill ok")
    result = d.dispatch(a)
    return result is True and len(tg.messages) == 1


def _s14_dispatcher_rate_limit() -> bool:
    """S14: AlertDispatcher blocks the (N+1)th message per minute."""
    tg = _FakeTelegram(returns=True)
    limit = ALERT_TELEGRAM_RATE_LIMIT_PER_MINUTE
    d = AlertDispatcher(telegram=tg, rate_limit_per_minute=limit)
    for _ in range(limit):
        d.dispatch(Alert(AlertType.PNL, AlertLevel.INFO, "pnl"))
    # (limit+1)th should be blocked
    result = d.dispatch(Alert(AlertType.PNL, AlertLevel.INFO, "pnl"))
    return result is False and len(tg.messages) == limit


def _s15_dispatcher_kill_switch_bypasses_rate_limit() -> bool:
    """S15: KILL_SWITCH alert bypasses the rate limit."""
    tg = _FakeTelegram(returns=True)
    d = AlertDispatcher(telegram=tg, rate_limit_per_minute=0)
    a = Alert(AlertType.KILL_SWITCH, AlertLevel.CRITICAL, "kill!")
    return d.dispatch(a) is True and len(tg.messages) == 1


def _s16_dispatcher_circuit_breaker_bypasses_rate_limit() -> bool:
    """S16: CIRCUIT_BREAKER alert bypasses the rate limit."""
    tg = _FakeTelegram(returns=True)
    d = AlertDispatcher(telegram=tg, rate_limit_per_minute=0)
    a = Alert(AlertType.CIRCUIT_BREAKER, AlertLevel.CRITICAL, "cb!")
    return d.dispatch(a) is True


def _s17_dispatcher_daily_report_email() -> bool:
    """S17: dispatch_daily_report calls email channel with correct args."""
    em = _FakeEmail()
    d = AlertDispatcher(email=em)
    pdf = b"%PDF-1.4 fake"
    result = d.dispatch_daily_report("Daily Report", "P&L +500", pdf_bytes=pdf)
    return result is True and em.reports[0] == ("Daily Report", "P&L +500", pdf)


def _s18_dispatcher_no_email_channel() -> bool:
    """S18: dispatch_daily_report returns False when no email channel."""
    d = AlertDispatcher()
    return d.dispatch_daily_report("Report", "body") is False


def _s19_cost_alerter_below_threshold() -> bool:
    """S19: LLMCostAlerter below threshold — no alert, returns correct cost."""
    redis = _FakeRedis({"sentiment:cost:daily:20260101": "0.20"})
    disp = _FakeDispatcher()
    alerter = LLMCostAlerter(redis, disp)
    cost = alerter.check(now_date=date(2026, 1, 1))
    return abs(cost - 0.20) < 1e-6 and len(disp.alerts) == 0


def _s20_cost_alerter_above_threshold() -> bool:
    """S20: LLMCostAlerter at/above threshold — fires LLM_COST alert once per day."""
    redis = _FakeRedis({
        "sentiment:cost:daily:20260101": "0.50",
        "orchestrator:llm:complex:20260101": "0.40",
    })
    disp = _FakeDispatcher()
    alerter = LLMCostAlerter(redis, disp, threshold_usd=LLM_COST_ALERT_THRESHOLD_USD)
    today = date(2026, 1, 1)
    cost1 = alerter.check(now_date=today)
    cost2 = alerter.check(now_date=today)  # second call same day → no duplicate
    return (
        abs(cost1 - 0.90) < 1e-6
        and abs(cost2 - 0.90) < 1e-6
        and len(disp.alerts) == 1
        and disp.alerts[0].alert_type is AlertType.LLM_COST
        and disp.alerts[0].level is AlertLevel.WARNING
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SCENARIOS = [
    _s01_alert_level_enum,
    _s02_alert_type_enum,
    _s03_alert_defaults,
    _s04_alert_metadata,
    _s05_telegram_send_success,
    _s06_telegram_send_failure,
    _s07_telegram_empty_token,
    _s08_telegram_network_error,
    _s09_email_build_pdf,
    _s10_email_send_daily_report,
    _s11_email_not_configured,
    _s12_dispatcher_no_channels,
    _s13_dispatcher_telegram_channel,
    _s14_dispatcher_rate_limit,
    _s15_dispatcher_kill_switch_bypasses_rate_limit,
    _s16_dispatcher_circuit_breaker_bypasses_rate_limit,
    _s17_dispatcher_daily_report_email,
    _s18_dispatcher_no_email_channel,
    _s19_cost_alerter_below_threshold,
    _s20_cost_alerter_above_threshold,
]


def run_verify() -> bool:
    """Execute all 20 VERIFY scenarios. Returns True if all pass."""
    passed = 0
    failed = 0
    for fn in _SCENARIOS:
        label = fn.__name__
        doc = (fn.__doc__ or "").strip()
        try:
            ok = fn()
        except Exception as exc:
            ok = False
            logger.error("verify_scenario_exception", scenario=label, error=str(exc))
        if ok:
            passed += 1
            logger.info("verify_pass", scenario=label, description=doc)
        else:
            failed += 1
            logger.error("verify_fail", scenario=label, description=doc)

    logger.info(
        "VERIFY_SUMMARY",
        passed=passed,
        failed=failed,
        total=len(_SCENARIOS),
    )
    return failed == 0
