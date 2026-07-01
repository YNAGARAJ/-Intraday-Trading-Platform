"""Async post-signal explanation via Groq 70B (non-blocking, RULE 4).

The LLM explanation is generated AFTER the signal is published to Redis Streams.
It never blocks order flow. Failures are logged and swallowed — the signal is
already committed by the time this function runs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import litellm
import structlog

from shared.core.constants import SIGNAL_EXPLAIN_MODEL

logger = structlog.get_logger(__name__)

_EXPLAIN_PROMPT_TEMPLATE = """\
Explain this trade signal concisely in 2-3 sentences:

Symbol: {symbol} ({exchange})
Direction: {direction}
Confidence: {confidence:.1%}
Regime: {regime}
Entry: {entry_price:.2f}  Stop: {stop_loss:.2f}
Target1: {target1:.2f}  Target2: {target2:.2f}
Indicators: {indicators}
Timeframes: {timeframes}
Pattern: {pattern}

Be specific about WHY this is a valid signal given the current regime and technicals.
"""


def _build_prompt(result: object) -> str:
    """Build the explanation prompt from a `SignalResult`."""
    r = result  # type: ignore[assignment]
    return _EXPLAIN_PROMPT_TEMPLATE.format(
        symbol=r.symbol,  # type: ignore[attr-defined]
        exchange=r.exchange,  # type: ignore[attr-defined]
        direction=r.direction,  # type: ignore[attr-defined]
        confidence=r.confidence,  # type: ignore[attr-defined]
        regime=r.regime,  # type: ignore[attr-defined]
        entry_price=r.entry_price,  # type: ignore[attr-defined]
        stop_loss=r.stop_loss,  # type: ignore[attr-defined]
        target1=r.target1,  # type: ignore[attr-defined]
        target2=r.target2,  # type: ignore[attr-defined]
        indicators=", ".join(r.confirming_indicators) or "none",  # type: ignore[attr-defined]
        timeframes=", ".join(r.confirming_timeframes) or "none",  # type: ignore[attr-defined]
        pattern=r.candlestick_pattern or "none",  # type: ignore[attr-defined]
    )


async def explain_signal(
    result: object,
    model: str = SIGNAL_EXPLAIN_MODEL,
    api_key: str | None = None,
) -> str:
    """Generate an async LLM explanation for a generated signal.

    This function is intentionally fire-and-forget from the caller's perspective.
    It should be launched with ``asyncio.create_task()`` or equivalent, never
    awaited on the hot path.

    Args:
        result: A ``SignalResult`` with ``generated=True``.
        model: LiteLLM model string (default: Groq 70B).
        api_key: Optional API key override; falls back to env var.

    Returns:
        Explanation string, or an empty string on any failure.
    """
    prompt = _build_prompt(result)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.3,
    }
    if api_key:
        kwargs["api_key"] = api_key

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: litellm.completion(**kwargs),
        )
        text: str = response.choices[0].message.content or ""
        r = result  # type: ignore[assignment]
        logger.info(
            "signal_explanation_generated",
            symbol=r.symbol,  # type: ignore[attr-defined]
            model=model,
            tokens=response.usage.total_tokens if response.usage else 0,
        )
        return text.strip()
    except Exception:
        r = result  # type: ignore[assignment]
        logger.warning(
            "signal_explanation_failed",
            symbol=r.symbol,  # type: ignore[attr-defined]
            model=model,
            exc_info=True,
        )
        return ""
