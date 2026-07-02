"""POST /api/v1/controls/{kill,pause,resume} — operator control endpoints.

All three endpoints require a valid X-API-Key header (RULE 8 / Tier 2 kill switch).
`is_priority` is set internally by KillSwitchManager.trigger_tier2() — never by
this module or any API caller.
"""

from __future__ import annotations

from typing import cast

import redis
from fastapi import APIRouter, Depends

from api.auth import require_api_key
from api.deps import get_redis
from api.models import ControlResponse
from shared.compliance.kill_switch import KillSwitchManager, RedisClient
from shared.core.constants import API_PAUSE_REDIS_KEY

router = APIRouter(prefix="/api/v1/controls", tags=["controls"])


@router.post("/kill", response_model=ControlResponse)
def kill(
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(require_api_key),  # noqa: B008
) -> ControlResponse:
    """Trigger Tier 2 kill switch: cancel all orders, liquidate positions, halt system.

    Protected by X-API-Key. Delegates to KillSwitchManager.trigger_tier2() which
    sets is_priority=True internally — the API layer never touches that flag (RULE 8).
    """
    try:
        KillSwitchManager(cast(RedisClient, r)).trigger_tier2(source="rest_api")
        return ControlResponse(
            success=True, action="kill", reason="Tier 2 kill switch triggered"
        )
    except Exception as exc:  # noqa: BLE001
        return ControlResponse(success=False, action="kill", reason=str(exc))


@router.post("/pause", response_model=ControlResponse)
def pause(
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(require_api_key),  # noqa: B008
) -> ControlResponse:
    """Pause new entry signals without triggering a full kill switch.

    Sets the `system:status:paused` Redis key. The orchestrator (M18) must
    check this key before forwarding any new-entry signal.
    """
    try:
        r.set(API_PAUSE_REDIS_KEY, "1")
        return ControlResponse(
            success=True, action="pause", reason="New entries paused"
        )
    except Exception as exc:  # noqa: BLE001
        return ControlResponse(success=False, action="pause", reason=str(exc))


@router.post("/resume", response_model=ControlResponse)
def resume(
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    _auth: None = Depends(require_api_key),  # noqa: B008
) -> ControlResponse:
    """Clear the pause flag, allowing new entry signals to flow again."""
    try:
        r.delete(API_PAUSE_REDIS_KEY)
        return ControlResponse(
            success=True, action="resume", reason="New entries resumed"
        )
    except Exception as exc:  # noqa: BLE001
        return ControlResponse(success=False, action="resume", reason=str(exc))
