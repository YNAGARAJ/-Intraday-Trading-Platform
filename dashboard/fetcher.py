"""Data-fetching layer for the Streamlit dashboard.

All functions call the FastAPI REST endpoints. This module is separate from
the Streamlit rendering code so it can be unit-tested without a display.
"""

from __future__ import annotations

import httpx

from shared.core.config import settings

_TIMEOUT = 5.0


def _headers() -> dict[str, str]:
    if settings.api_key:
        return {"X-API-Key": settings.api_key}
    return {}


def _base() -> str:
    return settings.api_dashboard_base_url.rstrip("/")


def fetch_status() -> dict[str, object]:
    """GET /api/v1/status — returns status dict or empty dict on error."""
    try:
        r = httpx.get(
            f"{_base()}/api/v1/status", headers=_headers(), timeout=_TIMEOUT
        )
        r.raise_for_status()
        result: dict[str, object] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return {}


def fetch_positions() -> list[dict[str, object]]:
    """GET /api/v1/positions — returns list of open positions."""
    try:
        r = httpx.get(
            f"{_base()}/api/v1/positions", headers=_headers(), timeout=_TIMEOUT
        )
        r.raise_for_status()
        result: list[dict[str, object]] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return []


def fetch_signals(limit: int = 20) -> list[dict[str, object]]:
    """GET /api/v1/signals — returns recent signals."""
    try:
        r = httpx.get(
            f"{_base()}/api/v1/signals",
            params={"limit": limit},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        result: list[dict[str, object]] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return []


def fetch_pnl() -> dict[str, object]:
    """GET /api/v1/pnl — returns today's P&L summary."""
    try:
        r = httpx.get(
            f"{_base()}/api/v1/pnl", headers=_headers(), timeout=_TIMEOUT
        )
        r.raise_for_status()
        result: dict[str, object] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return {}


def fetch_watchlist(exchange: str = "NSE") -> list[dict[str, object]]:
    """GET /api/v1/watchlist — returns the current watchlist entries."""
    try:
        r = httpx.get(
            f"{_base()}/api/v1/watchlist",
            params={"exchange": exchange},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        result: list[dict[str, object]] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return []


def post_kill(api_key: str) -> dict[str, object]:
    """POST /api/v1/controls/kill — trigger Tier 2 kill switch."""
    try:
        r = httpx.post(
            f"{_base()}/api/v1/controls/kill",
            headers={"X-API-Key": api_key},
            timeout=_TIMEOUT,
        )
        result: dict[str, object] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return {"success": False, "action": "kill", "reason": "Request failed"}


def post_pause(api_key: str) -> dict[str, object]:
    """POST /api/v1/controls/pause — pause new entry signals."""
    try:
        r = httpx.post(
            f"{_base()}/api/v1/controls/pause",
            headers={"X-API-Key": api_key},
            timeout=_TIMEOUT,
        )
        result: dict[str, object] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return {"success": False, "action": "pause", "reason": "Request failed"}


def post_resume(api_key: str) -> dict[str, object]:
    """POST /api/v1/controls/resume — resume new entry signals."""
    try:
        r = httpx.post(
            f"{_base()}/api/v1/controls/resume",
            headers={"X-API-Key": api_key},
            timeout=_TIMEOUT,
        )
        result: dict[str, object] = r.json()
        return result
    except Exception:  # noqa: BLE001
        return {"success": False, "action": "resume", "reason": "Request failed"}
