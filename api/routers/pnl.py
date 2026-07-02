"""GET /api/v1/pnl — daily P&L summary."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import cast

import redis
from fastapi import APIRouter, Depends

from api.auth import optional_api_key
from api.deps import get_redis
from api.models import PnLOut
from api.routers.status import _read_state, _state_dict_len
from shared.core.constants import KILL_SWITCH_HALTED_KEY, RISK_DAILY_PNL_REDIS_KEY

router = APIRouter(prefix="/api/v1", tags=["pnl"])


@router.get("/pnl", response_model=PnLOut)
def get_pnl(
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(optional_api_key),  # noqa: B008
) -> PnLOut:
    """Return today's P&L figures, sourced from the M12 risk-engine Redis key
    and the orchestrator state blob.

    Returns zeroed values when Redis is unavailable.
    """
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    pnl_key = RISK_DAILY_PNL_REDIS_KEY.format(date=today)

    total_pnl = 0.0
    starting_capital = 0.0

    try:
        raw_pnl = cast(str | None, r.get(pnl_key))
        if raw_pnl:
            v = float(raw_pnl)
            total_pnl = v if math.isfinite(v) else 0.0
    except (ValueError, TypeError, Exception):  # noqa: BLE001
        pass

    state = _read_state(r)
    sc = state.get("starting_capital")
    if isinstance(sc, (int, float)) and math.isfinite(float(sc)) and float(sc) > 0:
        starting_capital = float(sc)

    total_pnl_pct = (
        (total_pnl / starting_capital * 100) if starting_capital else 0.0
    )

    try:
        halted_raw = cast(str | None, r.get(KILL_SWITCH_HALTED_KEY))
        is_halted = bool(
            halted_raw and halted_raw not in ("0", "false", "False")
        )
    except Exception:  # noqa: BLE001
        is_halted = False

    return PnLOut(
        date=today,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        starting_capital=starting_capital,
        open_positions_count=_state_dict_len(state, "open_positions"),
        is_halted=is_halted,
    )
