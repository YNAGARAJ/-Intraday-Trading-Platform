"""GET /api/v1/status — system status snapshot."""

from __future__ import annotations

import json
import time
from typing import cast

import redis
from fastapi import APIRouter, Depends

from api.auth import optional_api_key
from api.deps import get_redis
from api.models import SystemStatus
from shared.core.config import settings
from shared.core.constants import (
    API_PAUSE_REDIS_KEY,
    INGESTION_DEGRADED_REDIS_KEY,
    KILL_SWITCH_HALTED_KEY,
    ORCHESTRATOR_STATE_REDIS_KEY,
)

router = APIRouter(prefix="/api/v1", tags=["status"])


def _read_state(r: redis.Redis) -> dict[str, object]:
    """Read the orchestrator state blob from Redis; return empty dict on error."""
    try:
        raw = cast(str | None, r.get(ORCHESTRATOR_STATE_REDIS_KEY))
        if raw:
            return cast(dict[str, object], json.loads(raw))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _bool_key(r: redis.Redis, key: str) -> bool:
    """Return True if the Redis key exists and is non-empty / non-zero."""
    try:
        v = cast(str | None, r.get(key))
        return bool(v and v not in ("0", "false", "False"))
    except Exception:  # noqa: BLE001
        return False


def _state_bool(state: dict[str, object], key: str) -> bool:
    v = state.get(key)
    return bool(v)


def _state_float(state: dict[str, object], key: str) -> float:
    v = state.get(key, 0.0)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _state_int(state: dict[str, object], key: str) -> int:
    v = state.get(key, 0)
    return int(v) if isinstance(v, (int, float)) else 0


def _state_str_opt(state: dict[str, object], key: str) -> str | None:
    v = state.get(key)
    return str(v) if v is not None else None


def _state_dict_len(state: dict[str, object], key: str) -> int:
    v = state.get(key)
    return len(v) if isinstance(v, dict) else 0


@router.get("/status", response_model=SystemStatus)
def get_status(
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(optional_api_key),  # noqa: B008
) -> SystemStatus:
    """Return a real-time snapshot of trading system state.

    Reads from Redis keys set by the orchestrator, compliance engine, and
    ingestion agent. Returns safe defaults when Redis is unavailable.
    """
    state = _read_state(r)
    halted_key = _bool_key(r, KILL_SWITCH_HALTED_KEY)
    paused = _bool_key(r, API_PAUSE_REDIS_KEY)
    degraded = _bool_key(r, INGESTION_DEGRADED_REDIS_KEY)

    ks_active = _state_bool(state, "kill_switch_active")
    cb_active = _state_bool(state, "circuit_breaker_active")

    return SystemStatus(
        trading_mode=settings.trading_mode.value,
        is_halted=halted_key or ks_active or cb_active,
        is_paused=paused,
        is_degraded=degraded,
        kill_switch_active=ks_active,
        circuit_breaker_active=cb_active,
        regime=_state_str_opt(state, "regime"),
        pnl_today=_state_float(state, "pnl_today"),
        pnl_today_pct=_state_float(state, "pnl_today_pct"),
        open_positions_count=_state_dict_len(state, "open_positions"),
        signals_today=_state_int(state, "signals_today"),
        trades_today=_state_int(state, "trades_today"),
        reconciliation_mismatches=_state_int(
            state, "reconciliation_mismatches_today"
        ),
        timestamp_ms=int(time.time() * 1000),
    )
