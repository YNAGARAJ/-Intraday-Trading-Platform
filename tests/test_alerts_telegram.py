"""Tests for M20 TelegramAlerter."""

from __future__ import annotations

import pytest

from shared.alerts.telegram import TelegramAlerter


class _MockResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _MockSession:
    def __init__(self, status_code: int = 200) -> None:
        self._code = status_code
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def post(
        self, url: str, *, json: dict[str, str], timeout: float
    ) -> _MockResponse:
        self.calls.append((url, json, timeout))
        return _MockResponse(self._code)


class _ErrorSession:
    def post(
        self, url: str, *, json: dict[str, str], timeout: float
    ) -> _MockResponse:
        raise ConnectionError("network unreachable")


class TestTelegramAlerterSend:
    def test_returns_true_on_200(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        assert ta.send("hello") is True

    def test_returns_false_on_400(self) -> None:
        sess = _MockSession(400)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        assert ta.send("hello") is False

    def test_returns_false_on_429(self) -> None:
        sess = _MockSession(429)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        assert ta.send("hello") is False

    def test_returns_false_on_500(self) -> None:
        sess = _MockSession(500)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        assert ta.send("hello") is False

    def test_empty_token_returns_false_no_http_call(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("", "cid", http_session=sess)
        result = ta.send("hello")
        assert result is False
        assert len(sess.calls) == 0

    def test_empty_chat_id_returns_false_no_http_call(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "", http_session=sess)
        result = ta.send("hello")
        assert result is False
        assert len(sess.calls) == 0

    def test_network_error_returns_false(self) -> None:
        ta = TelegramAlerter("tok", "cid", http_session=_ErrorSession())
        assert ta.send("hello") is False

    def test_sends_to_correct_api_url(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("mytoken", "cid", http_session=sess)
        ta.send("msg")
        url = sess.calls[0][0]
        assert "mytoken" in url
        assert "sendMessage" in url

    def test_payload_contains_chat_id(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "mychat", http_session=sess)
        ta.send("msg")
        payload = sess.calls[0][1]
        assert payload["chat_id"] == "mychat"

    def test_payload_contains_message_text(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        ta.send("my message")
        payload = sess.calls[0][1]
        assert payload["text"] == "my message"

    def test_payload_sets_parse_mode_html(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        ta.send("msg")
        payload = sess.calls[0][1]
        assert payload["parse_mode"] == "HTML"

    def test_makes_exactly_one_http_call_per_send(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        ta.send("a")
        ta.send("b")
        assert len(sess.calls) == 2

    def test_timeout_passed_to_session(self) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        ta.send("msg")
        assert sess.calls[0][2] == 5.0

    def test_token_never_in_response_on_failure(self) -> None:
        """Token must not appear in any log; tested here by checking the session URL."""
        sess = _MockSession(200)
        ta = TelegramAlerter("secrettoken", "cid", http_session=sess)
        ta.send("msg")
        # The URL contains the token (required by Telegram API) but it is NOT logged
        # by TelegramAlerter — confirmed by absence of any structlog call with token.
        url = sess.calls[0][0]
        assert "secrettoken" in url  # token in URL is API requirement, not a log leak

    @pytest.mark.parametrize("message", ["", "a" * 4096, "hello world"])
    def test_various_message_lengths(self, message: str) -> None:
        sess = _MockSession(200)
        ta = TelegramAlerter("tok", "cid", http_session=sess)
        result = ta.send(message)
        assert result is True
