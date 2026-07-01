"""Unit tests for M11 async signal explainer (LLM mocked)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from shared.signals.explainer import _build_prompt, explain_signal
from shared.signals.models import GateResult, SignalResult


def _make_result() -> SignalResult:
    return SignalResult(
        generated=True,
        symbol="RELIANCE",
        exchange="NSE",
        direction="LONG",
        confidence=0.78,
        entry_price=2450.0,
        stop_loss=2412.5,
        target1=2487.5,
        target2=2525.0,
        atr=25.0,
        strategy_id="EMAVWAP1",
        gate_results=[GateResult(1, True, "ok")],
        failed_at_gate=None,
        confirming_indicators=["EMA", "RSI", "MACD"],
        confirming_timeframes=["5m", "1h"],
        candlestick_pattern="CDLHAMMER",
        regime="BULL_TREND",
        evaluated_at=datetime.now(UTC),
    )


class TestBuildPrompt:
    def test_contains_symbol(self) -> None:
        r = _make_result()
        prompt = _build_prompt(r)
        assert "RELIANCE" in prompt

    def test_contains_direction(self) -> None:
        r = _make_result()
        prompt = _build_prompt(r)
        assert "LONG" in prompt

    def test_contains_regime(self) -> None:
        r = _make_result()
        prompt = _build_prompt(r)
        assert "BULL_TREND" in prompt

    def test_contains_pattern(self) -> None:
        r = _make_result()
        prompt = _build_prompt(r)
        assert "CDLHAMMER" in prompt

    def test_empty_indicators_shows_none(self) -> None:
        r = SignalResult(
            **{**_make_result().__dict__, "confirming_indicators": []}
        )
        prompt = _build_prompt(r)
        assert "none" in prompt.lower()


class TestExplainSignal:
    def _mock_response(self, text: str) -> MagicMock:
        choice = MagicMock()
        choice.message.content = text
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage.total_tokens = 50
        return resp

    def test_returns_explanation_on_success(self) -> None:
        expected = "RELIANCE shows bullish momentum."
        with patch("shared.signals.explainer.litellm") as mock_litellm:
            mock_litellm.completion.return_value = self._mock_response(expected)
            result = asyncio.run(explain_signal(_make_result()))
        assert result == expected

    def test_returns_empty_string_on_error(self) -> None:
        with patch("shared.signals.explainer.litellm") as mock_litellm:
            mock_litellm.completion.side_effect = RuntimeError("API error")
            result = asyncio.run(explain_signal(_make_result()))
        assert result == ""

    def test_passes_custom_model(self) -> None:
        with patch("shared.signals.explainer.litellm") as mock_litellm:
            mock_litellm.completion.return_value = self._mock_response("ok")
            asyncio.run(
                explain_signal(_make_result(), model="groq/llama-3.1-8b-instant")
            )
            call_kwargs = mock_litellm.completion.call_args[1]
            assert call_kwargs["model"] == "groq/llama-3.1-8b-instant"

    def test_passes_api_key_when_provided(self) -> None:
        with patch("shared.signals.explainer.litellm") as mock_litellm:
            mock_litellm.completion.return_value = self._mock_response("ok")
            asyncio.run(explain_signal(_make_result(), api_key="test-key-123"))
            call_kwargs = mock_litellm.completion.call_args[1]
            assert call_kwargs["api_key"] == "test-key-123"

    def test_max_tokens_200(self) -> None:
        with patch("shared.signals.explainer.litellm") as mock_litellm:
            mock_litellm.completion.return_value = self._mock_response("ok")
            asyncio.run(explain_signal(_make_result()))
            call_kwargs = mock_litellm.completion.call_args[1]
            assert call_kwargs["max_tokens"] == 200

    def test_strips_whitespace_from_response(self) -> None:
        with patch("shared.signals.explainer.litellm") as mock_litellm:
            mock_litellm.completion.return_value = self._mock_response(
                "  explanation  "
            )
            result = asyncio.run(explain_signal(_make_result()))
        assert result == "explanation"
