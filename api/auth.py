"""API-key authentication dependencies for the M22 FastAPI layer.

Control endpoints (kill, pause, resume) always enforce the key.
Read endpoints enforce the key only when `settings.api_key` is non-empty.

RULE 8 note: `is_priority` is never set by the API layer. Control endpoints
delegate to `KillSwitchManager.trigger_tier2()`, which sets it internally.
"""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from shared.core.config import settings
from shared.core.constants import API_KEY_HEADER

_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


async def require_api_key(api_key: str | None = Security(_scheme)) -> None:
    """Reject the request unless a valid X-API-Key header is present.

    Used on all control endpoints (kill, pause, resume). Returns 403 if the
    server has no key configured — operators must set one before using controls.
    """
    if not settings.api_key:
        raise HTTPException(
            status_code=403, detail="API key not configured on server"
        )
    if api_key is None:
        raise HTTPException(
            status_code=401, detail=f"{API_KEY_HEADER} header required"
        )
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


async def optional_api_key(api_key: str | None = Security(_scheme)) -> None:
    """Enforce the key on read endpoints only when `settings.api_key` is set.

    If the server has no key configured (empty string), all reads are open —
    convenient for local paper-trading dev. When a key is configured, reads
    are protected the same way as controls.
    """
    if not settings.api_key:
        return
    if api_key is None:
        raise HTTPException(
            status_code=401, detail=f"{API_KEY_HEADER} header required"
        )
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
