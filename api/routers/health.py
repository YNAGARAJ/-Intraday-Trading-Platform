"""GET /health — unauthenticated liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a simple OK response for load-balancer / container health checks."""
    return {"status": "ok"}
