"""M09 watchlist storage: TimescaleDB `watchlist_history` table + Redis TTL cache.

Public API
----------
apply_universe_schema(conn)   — idempotent DDL, call once per connection.
store_watchlist(entries, conn, redis_client)
                              — write to both Postgres and Redis.
load_watchlist(exchange, conn, redis_client)
                              — read from Redis first, fall back to Postgres.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import cast

import psycopg2
import psycopg2.extensions
import psycopg2.extras
import redis
import structlog

from shared.core.constants import (
    WATCHLIST_REDIS_TTL_SECONDS,
    WATCHLIST_TOP_N,
)
from shared.regime.models import MarketRegime
from shared.universe.models import AlphaComponents, WatchlistEntry

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Redis key pattern: universe:watchlist:<EXCHANGE>
_REDIS_KEY_PREFIX = "universe:watchlist"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS watchlist_history (
    id              BIGSERIAL       PRIMARY KEY,
    symbol          TEXT            NOT NULL,
    exchange        TEXT            NOT NULL,
    rank            INTEGER         NOT NULL,
    composite_score DOUBLE PRECISION NOT NULL,
    trend_score     DOUBLE PRECISION NOT NULL,
    vol_score       DOUBLE PRECISION NOT NULL,
    liq_score       DOUBLE PRECISION NOT NULL,
    sent_score      DOUBLE PRECISION NOT NULL,
    regime          TEXT            NOT NULL,
    strategy_id     TEXT            NOT NULL,
    scored_at       TIMESTAMPTZ     NOT NULL
);
SELECT create_hypertable(
    'watchlist_history', 'scored_at',
    if_not_exists => TRUE,
    migrate_data   => TRUE
);
CREATE INDEX IF NOT EXISTS watchlist_history_exchange_scored_at
    ON watchlist_history (exchange, scored_at DESC);
CREATE INDEX IF NOT EXISTS watchlist_history_symbol_scored_at
    ON watchlist_history (symbol, scored_at DESC);
"""

_INSERT_SQL = """
INSERT INTO watchlist_history (
    symbol, exchange, rank, composite_score,
    trend_score, vol_score, liq_score, sent_score,
    regime, strategy_id, scored_at
) VALUES (
    %(symbol)s, %(exchange)s, %(rank)s, %(composite_score)s,
    %(trend_score)s, %(vol_score)s, %(liq_score)s, %(sent_score)s,
    %(regime)s, %(strategy_id)s, %(scored_at)s
)
"""

_LOAD_LATEST_SQL = """
SELECT
    symbol, exchange, rank, composite_score,
    trend_score, vol_score, liq_score, sent_score,
    regime, strategy_id, scored_at
FROM watchlist_history
WHERE exchange = %(exchange)s
  AND scored_at = (
      SELECT MAX(scored_at) FROM watchlist_history WHERE exchange = %(exchange)s
  )
ORDER BY rank
LIMIT %(top_n)s
"""


def apply_universe_schema(
    conn: psycopg2.extensions.connection,
) -> None:
    """Create the ``watchlist_history`` hypertable if it does not exist.

    Idempotent — safe to call on every startup.
    """
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)
    conn.commit()
    logger.info("universe_schema_applied")


def _entry_to_redis_dict(entry: WatchlistEntry) -> dict[str, object]:
    """Serialise a WatchlistEntry to a JSON-serialisable dict."""
    return {
        "symbol": entry.symbol,
        "exchange": entry.exchange,
        "rank": entry.rank,
        "composite_score": entry.composite_score,
        "trend_score": entry.components.trend_score,
        "vol_score": entry.components.vol_score,
        "liq_score": entry.components.liq_score,
        "sent_score": entry.components.sent_score,
        "regime": entry.regime.value,
        "strategy_id": entry.strategy_id,
        "scored_at": entry.scored_at.isoformat(),
    }


def _redis_dict_to_entry(data: dict[str, object]) -> WatchlistEntry:
    """Deserialise a dict (from Redis JSON) back to a WatchlistEntry."""
    scored_at_raw = cast(str, data["scored_at"])
    scored_at = datetime.fromisoformat(scored_at_raw)
    if scored_at.tzinfo is None:
        scored_at = scored_at.replace(tzinfo=timezone.utc)
    return WatchlistEntry(
        symbol=cast(str, data["symbol"]),
        exchange=cast(str, data["exchange"]),
        rank=int(cast(int, data["rank"])),
        composite_score=float(cast(float, data["composite_score"])),
        components=AlphaComponents(
            trend_score=float(cast(float, data["trend_score"])),
            vol_score=float(cast(float, data["vol_score"])),
            liq_score=float(cast(float, data["liq_score"])),
            sent_score=float(cast(float, data["sent_score"])),
        ),
        regime=MarketRegime(cast(str, data["regime"])),
        strategy_id=cast(str, data["strategy_id"]),
        scored_at=scored_at,
    )


def _redis_key(exchange: str) -> str:
    return f"{_REDIS_KEY_PREFIX}:{exchange.upper()}"


def store_watchlist(
    entries: list[WatchlistEntry],
    conn: psycopg2.extensions.connection,
    redis_client: redis.Redis,  # type: ignore[type-arg]
) -> None:
    """Persist watchlist entries to TimescaleDB and cache them in Redis.

    Args:
        entries:      Ranked WatchlistEntry list from run_universe_filter().
        conn:         Active psycopg2 connection (caller retains ownership).
        redis_client: Redis client for TTL caching.
    """
    if not entries:
        return

    rows = [
        {
            "symbol": e.symbol,
            "exchange": e.exchange,
            "rank": e.rank,
            "composite_score": e.composite_score,
            "trend_score": e.components.trend_score,
            "vol_score": e.components.vol_score,
            "liq_score": e.components.liq_score,
            "sent_score": e.components.sent_score,
            "regime": e.regime.value,
            "strategy_id": e.strategy_id,
            "scored_at": e.scored_at,
        }
        for e in entries
    ]

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_SQL, rows)
    conn.commit()
    logger.info(
        "universe_stored_postgres",
        exchange=entries[0].exchange,
        count=len(entries),
    )

    # Redis: store as a JSON list under the exchange key with TTL
    exchange = entries[0].exchange
    key = _redis_key(exchange)
    payload = json.dumps([_entry_to_redis_dict(e) for e in entries])
    redis_client.set(key, payload, ex=WATCHLIST_REDIS_TTL_SECONDS)
    logger.info(
        "universe_cached_redis",
        key=key,
        ttl_seconds=WATCHLIST_REDIS_TTL_SECONDS,
        count=len(entries),
    )


def load_watchlist(
    exchange: str,
    conn: psycopg2.extensions.connection,
    redis_client: redis.Redis,  # type: ignore[type-arg]
    top_n: int = WATCHLIST_TOP_N,
) -> list[WatchlistEntry]:
    """Load the latest watchlist for an exchange, Redis-first with DB fallback.

    Args:
        exchange:     Exchange code (``"NSE"`` or ``"ASX"``).
        conn:         Active psycopg2 connection.
        redis_client: Redis client.
        top_n:        Maximum entries to return.

    Returns:
        List of WatchlistEntry sorted by rank ascending.  Empty list if no data.
    """
    key = _redis_key(exchange)
    cached = redis_client.get(key)
    if cached is not None:
        try:
            raw: list[dict[str, object]] = json.loads(
                cached if isinstance(cached, str) else cached.decode()
            )
            entries = [_redis_dict_to_entry(d) for d in raw[:top_n]]
            logger.info(
                "universe_loaded_redis", exchange=exchange, count=len(entries)
            )
            return entries
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "universe_redis_deserialise_failed",
                exchange=exchange,
                error=str(exc),
            )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_LOAD_LATEST_SQL, {"exchange": exchange.upper(), "top_n": top_n})
        rows = cur.fetchall()

    if not rows:
        logger.info("universe_load_empty", exchange=exchange)
        return []

    entries = []
    for row in rows:
        scored_at = row["scored_at"]
        if isinstance(scored_at, str):
            scored_at = datetime.fromisoformat(scored_at)
        if scored_at.tzinfo is None:
            scored_at = scored_at.replace(tzinfo=timezone.utc)
        entries.append(
            WatchlistEntry(
                symbol=str(row["symbol"]),
                exchange=str(row["exchange"]),
                rank=int(row["rank"]),
                composite_score=float(row["composite_score"]),
                components=AlphaComponents(
                    trend_score=float(row["trend_score"]),
                    vol_score=float(row["vol_score"]),
                    liq_score=float(row["liq_score"]),
                    sent_score=float(row["sent_score"]),
                ),
                regime=MarketRegime(str(row["regime"])),
                strategy_id=str(row["strategy_id"]),
                scored_at=scored_at,
            )
        )

    logger.info(
        "universe_loaded_postgres", exchange=exchange, count=len(entries)
    )
    return entries
