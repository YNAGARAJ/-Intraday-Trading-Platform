"""FastAPI application factory for M22 Dashboard & API."""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from api.routers import controls, health, pnl, positions, signals, status, watchlist, ws

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """Construct and return the configured FastAPI application."""
    app = FastAPI(
        title="Intraday Trading System API",
        description=(
            "Institutional-grade agentic trading system — "
            "positions, signals, P&L, and operator controls."
        ),
        version="1.0.0",
    )

    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(positions.router)
    app.include_router(signals.router)
    app.include_router(pnl.router)
    app.include_router(watchlist.router)
    app.include_router(controls.router)
    app.include_router(ws.router)

    logger.info("api_app_created", routes=len(app.routes))
    return app


app = create_app()
