"""M10 Sentiment & News Agent — LiteLLM batched Groq sentiment scorer.

Headlines are scored in batches of ``SENTIMENT_BATCH_MAX_HEADLINES`` (max 20)
to minimise LLM cost while keeping latency acceptable for pre-market use.

Public API
----------
score_headlines_batch(headlines, model, api_key) → (list[SentimentScore], int)
    Scores all headlines in ≤20 headline batches.  Returns (scores, total_tokens).
"""

from __future__ import annotations

import json
import re

import litellm
import structlog

from shared.core.constants import SENTIMENT_BATCH_MAX_HEADLINES
from shared.sentiment.models import SentimentScore

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT: str = (
    "You are a financial sentiment analyzer for Indian (NSE/BSE) and Australian "
    "(ASX) equity markets. Analyze each headline for its likely short-term impact "
    "on the broad equity market or a specific stock.\n\n"
    "Respond with valid JSON only — no markdown fences, no explanation:\n"
    '{"results": [\n'
    '  {"score": <float -1.0 to 1.0>, "label": "BULLISH"|"BEARISH"|"NEUTRAL", '
    '"confidence": <float 0.0 to 1.0>},\n'
    "  ...\n"
    "]}\n\n"
    "One object per headline, in the same order as the input. "
    "score: -1.0 = strongly bearish, 0.0 = neutral, 1.0 = strongly bullish. "
    "confidence: how certain you are."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_llm_response(
    content: str, n_headlines: int, model_version: str, from_cache: bool
) -> list[SentimentScore]:
    """Parse a JSON response from the LLM into SentimentScore objects.

    Falls back to NEUTRAL with confidence 0.0 on any parse failure.
    """
    fallback = [
        SentimentScore(
            headline=f"headline_{i}",
            score=0.0,
            label="NEUTRAL",
            confidence=0.0,
            tokens_used=0,
            from_cache=from_cache,
            model_version=model_version,
        )
        for i in range(n_headlines)
    ]

    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(
            "scorer_json_parse_failed", error=str(exc), preview=cleaned[:200]
        )
        return fallback

    if isinstance(data, dict):
        results_raw = data.get("results", [])
    elif isinstance(data, list):
        results_raw = data
    else:
        logger.warning("scorer_unexpected_response_type", type=type(data).__name__)
        return fallback

    if not isinstance(results_raw, list):
        return fallback

    scores: list[SentimentScore] = []
    for i, item in enumerate(results_raw[:n_headlines]):
        if not isinstance(item, dict):
            scores.append(fallback[i])
            continue
        try:
            raw_score = float(str(item.get("score", 0.0)))
            raw_label = str(item.get("label", "NEUTRAL")).upper().strip()
            raw_conf = float(str(item.get("confidence", 0.5)))
            _valid = ("BULLISH", "BEARISH", "NEUTRAL")
            label = raw_label if raw_label in _valid else "NEUTRAL"
            scores.append(
                SentimentScore(
                    headline=f"headline_{i}",
                    score=_clamp(raw_score, -1.0, 1.0),
                    label=label,
                    confidence=_clamp(raw_conf, 0.0, 1.0),
                    tokens_used=0,
                    from_cache=from_cache,
                    model_version=model_version,
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning("scorer_item_parse_failed", index=i, error=str(exc))
            scores.append(fallback[i] if i < len(fallback) else fallback[0])

    # Pad with fallback if LLM returned fewer items than headlines
    while len(scores) < n_headlines:
        scores.append(fallback[len(scores)])

    return scores


def _call_llm(
    headlines: list[str],
    model: str,
    api_key: str | None,
) -> tuple[list[tuple[float, str, float]], int]:
    """Issue a single LLM call for a batch of headlines.

    Returns:
        Tuple of (list[(score, label, confidence)], tokens_used).
        Falls back to all-NEUTRAL on any LLM/network error.
    """
    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Score these headlines:\n{numbered}"},
    ]
    try:
        raw = litellm.completion(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=len(headlines) * 40,
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scorer_llm_call_failed",
            model=model,
            n_headlines=len(headlines),
            error=str(exc),
        )
        return [(0.0, "NEUTRAL", 0.0)] * len(headlines), 0

    # litellm.completion returns ModelResponse | CustomStreamWrapper;
    # without stream=True the concrete type is always ModelResponse.
    try:
        usage = getattr(raw, "usage", None)
        tokens: int = int(getattr(usage, "total_tokens", 0)) if usage else 0
        choices = getattr(raw, "choices", [])
        first = choices[0] if choices else None
        message = getattr(first, "message", None) if first else None
        content: str = str(getattr(message, "content", "") or "")
    except (IndexError, AttributeError, TypeError) as exc:
        logger.warning("scorer_response_parse_failed", error=str(exc))
        return [(0.0, "NEUTRAL", 0.0)] * len(headlines), 0

    parsed = _parse_llm_response(content, len(headlines), model, from_cache=False)
    result = [(s.score, s.label, s.confidence) for s in parsed]
    return result, tokens


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_headlines_batch(
    headlines: list[str],
    model: str,
    api_key: str | None = None,
) -> tuple[list[SentimentScore], int]:
    """Score all headlines using batched LLM calls (max 20 per call).

    Headlines are split into batches of ``SENTIMENT_BATCH_MAX_HEADLINES``.
    Each batch is scored in a single LLM inference.  The ``tokens_used``
    field on each returned SentimentScore is the tokens consumed by the
    *entire batch* divided equally across headlines (an approximation; the
    caller should use the returned ``total_tokens`` for accurate cost tracking).

    Args:
        headlines:  Headline texts to score.
        model:      LiteLLM model string (e.g. ``"groq/llama-3.1-8b-instant"``).
        api_key:    Optional API key override; ``None`` uses the environment
                    variable expected by the provider (e.g. ``GROQ_API_KEY``).

    Returns:
        Tuple of (list[SentimentScore], total_tokens_used).
    """
    if not headlines:
        return [], 0

    all_scores: list[SentimentScore] = []
    total_tokens = 0

    batch_size = SENTIMENT_BATCH_MAX_HEADLINES
    for batch_start in range(0, len(headlines), batch_size):
        batch = headlines[batch_start : batch_start + batch_size]
        raw_results, batch_tokens = _call_llm(batch, model, api_key)
        total_tokens += batch_tokens

        tokens_per_headline = (
            batch_tokens // len(batch) if batch_tokens > 0 else 0
        )
        for i, (score_val, label, confidence) in enumerate(raw_results):
            all_scores.append(
                SentimentScore(
                    headline=batch[i],
                    score=score_val,
                    label=label,
                    confidence=confidence,
                    tokens_used=tokens_per_headline,
                    from_cache=False,
                    model_version=model,
                )
            )

        logger.info(
            "scorer_batch_complete",
            model=model,
            batch_size=len(batch),
            batch_tokens=batch_tokens,
            total_so_far=total_tokens,
        )

    return all_scores, total_tokens
