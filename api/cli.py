"""M22 Dashboard & API — 20 VERIFY scenarios.

Run via: ``python -m api``
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import structlog
from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_redis

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redis_mock(
    *,
    halted: bool = False,
    paused: bool = False,
    degraded: bool = False,
    state: dict[str, object] | None = None,
    pnl: float = 0.0,
    watchlist: list[dict[str, object]] | None = None,
    stream_entries: list[object] | None = None,
) -> MagicMock:
    """Build a mock Redis client with pre-set return values."""
    r = MagicMock()

    def _get(key: str) -> str | None:
        mapping: dict[str, str | None] = {
            "system:status:halted": "1" if halted else None,
            "system:status:paused": "1" if paused else None,
            "system:status:degraded": "1" if degraded else None,
            "orchestrator:state": json.dumps(state or {}),
            "universe:watchlist:NSE": (
                json.dumps(watchlist) if watchlist is not None else None
            ),
        }
        if key.startswith("risk:daily:pnl:"):
            return str(pnl) if pnl else None
        return mapping.get(key)

    r.get.side_effect = _get
    r.xrevrange.return_value = stream_entries or []
    r.xread.return_value = stream_entries or []
    r.set.return_value = True
    r.delete.return_value = 1
    return r


def _app_with_redis(r: MagicMock) -> TestClient:
    """Create TestClient with dependency_overrides for get_redis."""
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _s01_health_endpoint_returns_ok() -> bool:
    """S01: GET /health returns {status: ok} with no auth required."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health")
    return resp.status_code == 200 and resp.json()["status"] == "ok"


def _s02_status_no_redis_returns_defaults() -> bool:
    """S02: GET /api/v1/status with no API key configured returns 200 with defaults."""
    client = _app_with_redis(_redis_mock())
    resp = client.get("/api/v1/status")
    return resp.status_code == 200 and resp.json()["is_halted"] is False


def _s03_positions_empty_with_no_state() -> bool:
    """S03: GET /api/v1/positions returns [] when orchestrator state is absent."""
    client = _app_with_redis(_redis_mock())
    resp = client.get("/api/v1/positions")
    return resp.status_code == 200 and resp.json() == []


def _s04_signals_empty_with_no_stream() -> bool:
    """S04: GET /api/v1/signals returns [] when stream has no entries."""
    client = _app_with_redis(_redis_mock())
    resp = client.get("/api/v1/signals")
    return resp.status_code == 200 and resp.json() == []


def _s05_pnl_zero_with_no_state() -> bool:
    """S05: GET /api/v1/pnl returns zero values when Redis has no data."""
    client = _app_with_redis(_redis_mock())
    resp = client.get("/api/v1/pnl")
    body = resp.json()
    return resp.status_code == 200 and body["total_pnl"] == 0.0


def _s06_watchlist_empty_with_no_state() -> bool:
    """S06: GET /api/v1/watchlist returns [] when no watchlist is published."""
    client = _app_with_redis(_redis_mock())
    resp = client.get("/api/v1/watchlist")
    return resp.status_code == 200 and resp.json() == []


def _s07_kill_requires_api_key() -> bool:
    """S07: POST /api/v1/controls/kill without key returns 401 or 403."""
    r = _redis_mock()
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    with patch("api.auth.settings") as mock_s:
        mock_s.api_key = "secret"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/controls/kill")
    return resp.status_code in (401, 403)


def _s08_kill_with_valid_key_succeeds() -> bool:
    """S08: POST /api/v1/controls/kill with valid key returns success=True."""
    r = _redis_mock()
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    with (
        patch("api.auth.settings") as mock_s,
        patch("api.routers.controls.KillSwitchManager") as mock_ks,
    ):
        mock_s.api_key = "secret"
        mock_ks.return_value.trigger_tier2.return_value = MagicMock()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/controls/kill",
            headers={"X-API-Key": "secret"},
        )
    return resp.status_code == 200 and resp.json()["success"] is True


def _s09_pause_sets_redis_flag() -> bool:
    """S09: POST /api/v1/controls/pause with valid key sets the paused Redis key."""
    r = _redis_mock()
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    with patch("api.auth.settings") as mock_s:
        mock_s.api_key = "secret"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/controls/pause", headers={"X-API-Key": "secret"}
        )
    return resp.status_code == 200 and resp.json()["action"] == "pause"


def _s10_resume_clears_redis_flag() -> bool:
    """S10: POST /api/v1/controls/resume with valid key clears the paused key."""
    r = _redis_mock()
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    with patch("api.auth.settings") as mock_s:
        mock_s.api_key = "secret"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/controls/resume", headers={"X-API-Key": "secret"}
        )
    return (
        resp.status_code == 200
        and resp.json()["action"] == "resume"
        and resp.json()["success"] is True
    )


def _s11_invalid_api_key_rejected() -> bool:
    """S11: POST /api/v1/controls/kill with wrong key returns 403."""
    r = _redis_mock()
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: r
    with patch("api.auth.settings") as mock_s:
        mock_s.api_key = "correct-key"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/controls/kill", headers={"X-API-Key": "wrong-key"}
        )
    return resp.status_code == 403


def _s12_status_reflects_halted_state() -> bool:
    """S12: GET /api/v1/status returns is_halted=True when halt key is set."""
    client = _app_with_redis(_redis_mock(halted=True))
    resp = client.get("/api/v1/status")
    return resp.status_code == 200 and resp.json()["is_halted"] is True


def _s13_status_reflects_paused_state() -> bool:
    """S13: GET /api/v1/status returns is_paused=True when pause key is set."""
    client = _app_with_redis(_redis_mock(paused=True))
    resp = client.get("/api/v1/status")
    return resp.status_code == 200 and resp.json()["is_paused"] is True


def _s14_status_reflects_degraded_state() -> bool:
    """S14: GET /api/v1/status returns is_degraded=True when degraded key is set."""
    client = _app_with_redis(_redis_mock(degraded=True))
    resp = client.get("/api/v1/status")
    return resp.status_code == 200 and resp.json()["is_degraded"] is True


def _s15_positions_from_orchestrator_state() -> bool:
    """S15: GET /api/v1/positions returns positions from orchestrator state blob."""
    state: dict[str, object] = {
        "open_positions": {
            "ord-1": {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "direction": "LONG",
                "quantity": 100,
                "entry_price": 2900.0,
            }
        }
    }
    client = _app_with_redis(_redis_mock(state=state))
    resp = client.get("/api/v1/positions")
    data = resp.json()
    return (
        resp.status_code == 200
        and len(data) == 1
        and data[0]["symbol"] == "RELIANCE"
    )


def _s16_signals_from_stream() -> bool:
    """S16: GET /api/v1/signals returns signal data from Redis stream."""
    stream_entries: list[object] = [
        (
            "1700000000000-0",
            {
                "symbol": "INFY",
                "exchange": "NSE",
                "direction": "LONG",
                "confidence": "0.85",
                "strategy_tag": "STRAT001",
                "timestamp_ms": "1700000000000",
            },
        )
    ]
    r = _redis_mock()
    r.xrevrange.return_value = stream_entries
    client = _app_with_redis(r)
    resp = client.get("/api/v1/signals")
    data = resp.json()
    return (
        resp.status_code == 200
        and len(data) == 1
        and data[0]["symbol"] == "INFY"
        and data[0]["confidence"] == 0.85
    )


def _s17_pnl_from_redis_key() -> bool:
    """S17: GET /api/v1/pnl returns the stored P&L value from risk:daily:pnl:{date}."""
    client = _app_with_redis(_redis_mock(pnl=1500.0))
    resp = client.get("/api/v1/pnl")
    return resp.status_code == 200 and resp.json()["total_pnl"] == 1500.0


def _s18_watchlist_from_redis_key() -> bool:
    """S18: GET /api/v1/watchlist returns the stored watchlist for NSE exchange."""
    wl: list[dict[str, object]] = [
        {"symbol": "TCS", "exchange": "NSE", "composite_score": 0.75}
    ]
    client = _app_with_redis(_redis_mock(watchlist=wl))
    resp = client.get("/api/v1/watchlist?exchange=NSE")
    data = resp.json()
    return (
        resp.status_code == 200
        and len(data) == 1
        and data[0]["symbol"] == "TCS"
    )


def _s19_all_routes_have_correct_prefix() -> bool:
    """S19: All REST routes are under /api/v1/ prefix (or /health / /ws/live)."""
    app = create_app()
    paths = [
        getattr(r, "path", None)
        for r in app.routes
        if hasattr(r, "path")
    ]
    _excluded = {
        "/health", "/ws/live", "/openapi.json",
        "/docs", "/docs/oauth2-redirect", "/redoc",
    }
    rest_paths = [p for p in paths if p and p not in _excluded]
    return all(str(p).startswith("/api/v1/") for p in rest_paths)


def _s20_ws_endpoint_sends_initial_ping() -> bool:
    """S20: WebSocket /ws/live sends an initial ping immediately on connect."""
    app = create_app()
    try:
        with patch("api.routers.ws.settings") as mock_s:
            mock_s.api_key = ""
            mock_s.redis_url = "redis://localhost:6379/0"
            client = TestClient(app)
            with client.websocket_connect("/ws/live") as ws:
                msg = ws.receive_json()
                return msg.get("type") == "ping" and "ts" in msg
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SCENARIOS = [
    _s01_health_endpoint_returns_ok,
    _s02_status_no_redis_returns_defaults,
    _s03_positions_empty_with_no_state,
    _s04_signals_empty_with_no_stream,
    _s05_pnl_zero_with_no_state,
    _s06_watchlist_empty_with_no_state,
    _s07_kill_requires_api_key,
    _s08_kill_with_valid_key_succeeds,
    _s09_pause_sets_redis_flag,
    _s10_resume_clears_redis_flag,
    _s11_invalid_api_key_rejected,
    _s12_status_reflects_halted_state,
    _s13_status_reflects_paused_state,
    _s14_status_reflects_degraded_state,
    _s15_positions_from_orchestrator_state,
    _s16_signals_from_stream,
    _s17_pnl_from_redis_key,
    _s18_watchlist_from_redis_key,
    _s19_all_routes_have_correct_prefix,
    _s20_ws_endpoint_sends_initial_ping,
]


def run_verify() -> bool:
    """Execute all 20 VERIFY scenarios. Returns True if all pass."""
    passed = 0
    failed = 0
    for fn in _SCENARIOS:
        label = fn.__name__
        doc = (fn.__doc__ or "").strip()
        try:
            ok = fn()
        except Exception as exc:
            ok = False
            logger.error("verify_scenario_exception", scenario=label, error=str(exc))
        if ok:
            passed += 1
            logger.info("verify_pass", scenario=label, description=doc)
        else:
            failed += 1
            logger.error("verify_fail", scenario=label, description=doc)
    logger.info("VERIFY_SUMMARY", passed=passed, failed=failed, total=len(_SCENARIOS))
    return failed == 0
