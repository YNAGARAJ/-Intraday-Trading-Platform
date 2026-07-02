"""GET /api/v1/watchlist — current universe watchlist from Redis."""

from __future__ import annotations

import json
from typing import cast

import redis
from fastapi import APIRouter, Depends, Query

from api.auth import optional_api_key
from api.deps import get_redis
from api.models import WatchlistOut

router = APIRouter(prefix="/api/v1", tags=["watchlist"])

_WATCHLIST_KEY_PREFIX = "universe:watchlist"


@router.get("/watchlist", response_model=list[WatchlistOut])
def get_watchlist(
    exchange: str = Query(default="NSE", description="Exchange: NSE or ASX"),
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(optional_api_key),  # noqa: B008
) -> list[WatchlistOut]:
    """Return the current watchlist for the given exchange.

    The list is populated by M09 (universe filter) and cached in Redis for 8 hours.
    Returns empty list when no watchlist has been published yet.
    """
    key = f"{_WATCHLIST_KEY_PREFIX}:{exchange.upper()}"
    try:
        raw = cast(str | None, r.get(key))
        if not raw:
            return []
        entries = cast(list[dict[str, object]], json.loads(raw))
    except Exception:  # noqa: BLE001
        return []

    out: list[WatchlistOut] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        exch = entry.get("exchange")
        if not isinstance(sym, str) or not isinstance(exch, str):
            continue
        score_raw = entry.get("composite_score")
        score: float | None = None
        if isinstance(score_raw, (int, float)):
            score = float(score_raw)
        out.append(WatchlistOut(symbol=sym, exchange=exch, composite_score=score))
    return out
