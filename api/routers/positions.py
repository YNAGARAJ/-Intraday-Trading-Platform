"""GET /api/v1/positions — open positions from orchestrator state."""

from __future__ import annotations

import redis
from fastapi import APIRouter, Depends

from api.auth import optional_api_key
from api.deps import get_redis
from api.models import PositionOut
from api.routers.status import _read_state

router = APIRouter(prefix="/api/v1", tags=["positions"])


@router.get("/positions", response_model=list[PositionOut])
def get_positions(
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(optional_api_key),  # noqa: B008
) -> list[PositionOut]:
    """Return all currently open positions from the orchestrator state blob."""
    state = _read_state(r)
    raw = state.get("open_positions")
    if not isinstance(raw, dict):
        return []

    out: list[PositionOut] = []
    for _order_id, pos in raw.items():
        if not isinstance(pos, dict):
            continue
        try:
            qty = pos.get("quantity", 0)
            price = pos.get("entry_price", 0.0)
            out.append(
                PositionOut(
                    symbol=str(pos.get("symbol", "")),
                    exchange=str(pos.get("exchange", "")),
                    direction=str(pos.get("direction", "")),
                    quantity=int(qty) if isinstance(qty, (int, float)) else 0,
                    entry_price=(
                        float(price) if isinstance(price, (int, float)) else 0.0
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return out
