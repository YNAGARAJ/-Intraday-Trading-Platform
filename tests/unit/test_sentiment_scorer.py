"""Unit tests for M10 batched LLM scorer (scorer.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from shared.core.constants import SENTIMENT_BATCH_MAX_HEADLINES
from shared.sentiment.models import SentimentScore
from shared.sentiment.scorer import (
    _call_llm,
    _clamp,
    _parse_llm_response,
    score_headlines_batch,
)

_MODEL = "groq/llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------


class TestClamp:
    def test_within_range(self) -> None:
        assert _clamp(0.5, -1.0, 1.0) == 0.5

    def test_below_min(self) -> None:
        assert _clamp(-2.0, -1.0, 1.0) == -1.0

    def test_above_max(self) -> None:
        assert _clamp(1.5, -1.0, 1.0) == 1.0

    def test_exactly_at_boundary(self) -> None:
        assert _clamp(-1.0, -1.0, 1.0) == -1.0
        assert _clamp(1.0, -1.0, 1.0) == 1.0


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    def _parse(self, content: str, n: int = 2) -> list[SentimentScore]:
        return _parse_llm_response(content, n, _MODEL, from_cache=False)

    def test_valid_json_parsed(self) -> None:
        content = json.dumps(
            {"results": [
                {"score": 0.8, "label": "BULLISH", "confidence": 0.9},
                {"score": -0.5, "label": "BEARISH", "confidence": 0.7},
            ]}
        )
        scores = self._parse(content, 2)
        assert len(scores) == 2
        assert scores[0].label == "BULLISH"
        assert scores[1].label == "BEARISH"

    def test_bare_list_response(self) -> None:
        content = json.dumps([
            {"score": 0.0, "label": "NEUTRAL", "confidence": 0.5},
        ])
        scores = self._parse(content, 1)
        assert scores[0].label == "NEUTRAL"

    def test_markdown_fences_stripped(self) -> None:
        content = "```json\n" + json.dumps(
            {"results": [{"score": 0.3, "label": "BULLISH", "confidence": 0.6}]}
        ) + "\n```"
        scores = self._parse(content, 1)
        assert scores[0].label == "BULLISH"

    def test_invalid_json_returns_neutral_fallback(self) -> None:
        scores = self._parse("not json at all", 3)
        assert len(scores) == 3
        assert all(s.label == "NEUTRAL" for s in scores)

    def test_score_clamped_above(self) -> None:
        content = json.dumps(
            {"results": [{"score": 2.0, "label": "BULLISH", "confidence": 0.9}]}
        )
        scores = self._parse(content, 1)
        assert scores[0].score == 1.0

    def test_score_clamped_below(self) -> None:
        content = json.dumps(
            {"results": [{"score": -5.0, "label": "BEARISH", "confidence": 0.8}]}
        )
        scores = self._parse(content, 1)
        assert scores[0].score == -1.0

    def test_unknown_label_becomes_neutral(self) -> None:
        content = json.dumps(
            {"results": [{"score": 0.5, "label": "POSITIVE", "confidence": 0.7}]}
        )
        scores = self._parse(content, 1)
        assert scores[0].label == "NEUTRAL"

    def test_fewer_results_padded_with_neutral(self) -> None:
        content = json.dumps(
            {"results": [{"score": 0.5, "label": "BULLISH", "confidence": 0.8}]}
        )
        scores = self._parse(content, 3)  # 3 headlines but only 1 result
        assert len(scores) == 3
        assert scores[0].label == "BULLISH"
        assert scores[1].label == "NEUTRAL"
        assert scores[2].label == "NEUTRAL"

    def test_confidence_clamped(self) -> None:
        content = json.dumps(
            {"results": [{"score": 0.5, "label": "BULLISH", "confidence": 1.5}]}
        )
        scores = self._parse(content, 1)
        assert scores[0].confidence == 1.0

    def test_empty_results_list_returns_fallback(self) -> None:
        content = json.dumps({"results": []})
        scores = self._parse(content, 2)
        assert len(scores) == 2
        assert all(s.label == "NEUTRAL" for s in scores)


# ---------------------------------------------------------------------------
# _call_llm — mocking litellm
# ---------------------------------------------------------------------------


def _make_litellm_response(
    content: str, total_tokens: int = 100
) -> MagicMock:
    """Build a MagicMock that looks like a litellm ModelResponse."""
    resp = MagicMock()
    resp.usage.total_tokens = total_tokens
    resp.choices[0].message.content = content
    return resp


class TestCallLLM:
    @patch("shared.sentiment.scorer.litellm")
    def test_returns_results_and_tokens(self, mock_litellm: MagicMock) -> None:
        content = json.dumps(
            {"results": [
                {"score": 0.7, "label": "BULLISH", "confidence": 0.9},
                {"score": -0.3, "label": "BEARISH", "confidence": 0.6},
            ]}
        )
        mock_litellm.completion.return_value = _make_litellm_response(content, 80)
        results, tokens = _call_llm(["h1", "h2"], _MODEL, None)
        assert len(results) == 2
        assert tokens == 80

    @patch("shared.sentiment.scorer.litellm")
    def test_llm_exception_returns_neutral_fallback(
        self, mock_litellm: MagicMock
    ) -> None:
        mock_litellm.completion.side_effect = RuntimeError("API error")
        results, tokens = _call_llm(["h1", "h2"], _MODEL, None)
        assert tokens == 0
        assert all(label == "NEUTRAL" for _, label, _ in results)

    @patch("shared.sentiment.scorer.litellm")
    def test_api_key_forwarded(self, mock_litellm: MagicMock) -> None:
        content = json.dumps(
            {"results": [{"score": 0.0, "label": "NEUTRAL", "confidence": 0.5}]}
        )
        mock_litellm.completion.return_value = _make_litellm_response(content)
        _call_llm(["h1"], _MODEL, api_key="test-key-123")
        _, kwargs = mock_litellm.completion.call_args
        assert kwargs.get("api_key") == "test-key-123"


# ---------------------------------------------------------------------------
# score_headlines_batch — batching logic
# ---------------------------------------------------------------------------


class TestScoreHeadlinesBatch:
    @patch("shared.sentiment.scorer._call_llm")
    def test_empty_input_returns_empty(self, mock_call: MagicMock) -> None:
        scores, tokens = score_headlines_batch([], _MODEL)
        assert scores == []
        assert tokens == 0
        mock_call.assert_not_called()

    @patch("shared.sentiment.scorer._call_llm")
    def test_single_batch(self, mock_call: MagicMock) -> None:
        n = 5
        mock_call.return_value = ([(0.5, "BULLISH", 0.8)] * n, 100)
        scores, tokens = score_headlines_batch([f"h{i}" for i in range(n)], _MODEL)
        assert len(scores) == n
        assert tokens == 100
        mock_call.assert_called_once()

    @patch("shared.sentiment.scorer._call_llm")
    def test_two_batches_for_over_twenty(self, mock_call: MagicMock) -> None:
        n = SENTIMENT_BATCH_MAX_HEADLINES + 5
        mock_call.side_effect = [
            ([(0.5, "BULLISH", 0.8)] * SENTIMENT_BATCH_MAX_HEADLINES, 200),
            ([(0.0, "NEUTRAL", 0.5)] * 5, 50),
        ]
        scores, tokens = score_headlines_batch([f"h{i}" for i in range(n)], _MODEL)
        assert len(scores) == n
        assert tokens == 250
        assert mock_call.call_count == 2

    @patch("shared.sentiment.scorer._call_llm")
    def test_exactly_max_batch_one_call(self, mock_call: MagicMock) -> None:
        mock_call.return_value = (
            [(0.0, "NEUTRAL", 0.5)] * SENTIMENT_BATCH_MAX_HEADLINES, 400
        )
        scores, tokens = score_headlines_batch(
            [f"h{i}" for i in range(SENTIMENT_BATCH_MAX_HEADLINES)], _MODEL
        )
        assert len(scores) == SENTIMENT_BATCH_MAX_HEADLINES
        mock_call.assert_called_once()

    @patch("shared.sentiment.scorer._call_llm")
    def test_headline_text_preserved_on_score(self, mock_call: MagicMock) -> None:
        mock_call.return_value = ([(0.9, "BULLISH", 0.95)], 50)
        scores, _ = score_headlines_batch(["NIFTY hits record"], _MODEL)
        assert scores[0].headline == "NIFTY hits record"

    @patch("shared.sentiment.scorer._call_llm")
    def test_model_version_on_score(self, mock_call: MagicMock) -> None:
        mock_call.return_value = ([(0.1, "NEUTRAL", 0.4)], 30)
        scores, _ = score_headlines_batch(["some news"], _MODEL)
        assert scores[0].model_version == _MODEL

    @patch("shared.sentiment.scorer._call_llm")
    def test_from_cache_false_on_llm_scores(self, mock_call: MagicMock) -> None:
        mock_call.return_value = ([(0.5, "BULLISH", 0.8)], 50)
        scores, _ = score_headlines_batch(["news"], _MODEL)
        assert scores[0].from_cache is False
