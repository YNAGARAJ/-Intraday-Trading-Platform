"""M10 Sentiment & News Agent — CLI entry point.

Usage
-----
    python -m shared.sentiment [options]

Examples
---------
    # Score NSE headlines with Groq (requires GROQ_API_KEY)
    python -m shared.sentiment --exchange NSE

    # Score only, no cache, print aggregate and per-headline scores
    python -m shared.sentiment --exchange ASX --no-cache --verbose

    # Score custom headlines (for VERIFY testing)
    python -m shared.sentiment --exchange NSE --headlines \
        "NIFTY rises 1%" "Inflation data beats"

    # Print daily LLM cost total
    python -m shared.sentiment --cost-report
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import structlog

from shared.core.config import load_settings
from shared.core.logging import configure_logging
from shared.sentiment.agent import SentimentAgent
from shared.sentiment.cost_tracker import CostTracker
from shared.sentiment.models import MarketSentiment

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m shared.sentiment",
        description="M10: score intraday news sentiment for NSE or ASX",
    )
    p.add_argument(
        "--exchange",
        default="NSE",
        choices=["NSE", "ASX"],
        help="Exchange to fetch feeds for (default: NSE)",
    )
    p.add_argument(
        "--model",
        default=None,
        help="LiteLLM model string (default: SENTIMENT_DEFAULT_MODEL from constants)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        dest="api_key",
        help="LLM provider API key (default: read from environment)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable semantic dedup cache (forces live LLM calls)",
    )
    p.add_argument(
        "--headlines",
        nargs="+",
        default=None,
        metavar="HEADLINE",
        help="Score custom headline strings instead of fetching RSS feeds",
    )
    p.add_argument(
        "--cost-report",
        action="store_true",
        help="Print today's LLM cost total and exit",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-headline scores in addition to the aggregate",
    )
    p.add_argument(
        "--output-json",
        action="store_true",
        help="Emit the full MarketSentiment as JSON to stdout",
    )
    return p.parse_args(argv)


def _print_result(result: MarketSentiment, verbose: bool, output_json: bool) -> None:
    """Log or print the sentiment result."""
    if output_json:
        data = {
            "exchange": result.exchange,
            "aggregate_score": result.aggregate_score,
            "cache_hit_rate": result.cache_hit_rate,
            "total_tokens_used": result.total_tokens_used,
            "total_cost_usd": result.total_cost_usd,
            "cache_hits": result.cache_hits,
            "cache_misses": result.cache_misses,
            "scored_at": result.scored_at.isoformat(),
            "fii_net_crore": result.fii_dii.fii_net_crore if result.fii_dii else None,
            "dii_net_crore": result.fii_dii.dii_net_crore if result.fii_dii else None,
            "vix": result.vix_data.vix if result.vix_data else None,
            "put_call_ratio": (
                result.vix_data.put_call_ratio if result.vix_data else None
            ),
            "scores": [
                {
                    "headline": s.headline[:100],
                    "score": s.score,
                    "label": s.label,
                    "confidence": s.confidence,
                    "from_cache": s.from_cache,
                }
                for s in result.scores
            ],
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return

    logger.info(
        "sentiment_result",
        exchange=result.exchange,
        aggregate_score=round(result.aggregate_score, 4),
        headlines=len(result.headlines),
        cache_hits=result.cache_hits,
        cache_misses=result.cache_misses,
        cache_hit_rate=round(result.cache_hit_rate, 4),
        total_tokens=result.total_tokens_used,
        cost_usd=round(result.total_cost_usd, 6),
        vix=result.vix_data.vix if result.vix_data else None,
        fii_net=result.fii_dii.fii_net_crore if result.fii_dii else None,
        dii_net=result.fii_dii.dii_net_crore if result.fii_dii else None,
    )

    if verbose:
        for s in result.scores:
            logger.info(
                "headline_score",
                label=s.label,
                score=round(s.score, 3),
                confidence=round(s.confidence, 3),
                from_cache=s.from_cache,
                headline=s.headline[:100],
            )


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``python -m shared.sentiment``.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.
    """
    configure_logging()
    args = _parse_args(argv)

    settings = load_settings()

    # --cost-report path
    if args.cost_report:
        redis_client = None
        try:
            import redis as redis_lib  # noqa: PLC0415

            redis_client = redis_lib.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url,
                decode_responses=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis_connect_failed", error=str(exc))

        tracker = CostTracker(redis_client)
        logger.info(
            "llm_daily_cost_report",
            date=datetime.now(tz=timezone.utc).date().isoformat(),
            total_usd=round(tracker.get_daily_total_usd(), 6),
        )
        return

    # Determine model
    from shared.core.constants import SENTIMENT_DEFAULT_MODEL

    model = args.model or SENTIMENT_DEFAULT_MODEL

    # Optionally wire Redis (cache + cost tracking)
    redis_client = None
    if not args.no_cache:
        try:
            import redis as redis_lib  # noqa: PLC0415

            redis_client = redis_lib.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url,
                decode_responses=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis_connect_failed_no_cache", error=str(exc))

    agent = SentimentAgent(
        model=model,
        api_key=args.api_key,
        redis_client=redis_client,
    )

    result = agent.run(
        exchange=args.exchange,
        custom_headlines=args.headlines,
    )

    _print_result(result, verbose=args.verbose, output_json=args.output_json)
