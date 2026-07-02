"""WebSocket /ws/live — real-time signal and state streaming.

The endpoint accepts an optional `api_key` query parameter. When `settings.api_key`
is non-empty, connections without a matching key are rejected with close code 4001.
"""

from __future__ import annotations

import asyncio
import time
from typing import cast

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from shared.core.config import settings
from shared.core.constants import (
    API_WS_HEARTBEAT_INTERVAL_SECONDS,
    SIGNAL_REDIS_STREAM,
)

router = APIRouter(tags=["ws"])

# Block period for each Redis xread poll — balances latency vs CPU.
_XREAD_BLOCK_MS = 500


@router.websocket("/ws/live")
async def ws_live(
    websocket: WebSocket,
    api_key: str | None = Query(default=None, alias="api_key"),
) -> None:
    """Stream live signal events and periodic heartbeat pings to the client.

    Message types sent by the server:

    - ``{"type": "ping", "ts": <epoch_ms>}`` — heartbeat, every 30 s
    - ``{"type": "signal", "id": <stream_id>, "data": {...}, "ts": <epoch_ms>}``
      — new signal from the signals:generated Redis stream
    """
    if settings.api_key and api_key != settings.api_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    loop = asyncio.get_event_loop()
    last_id = "$"
    last_ping_ts = 0.0

    try:
        now_ms = int(time.time() * 1000)
        await websocket.send_json({"type": "ping", "ts": now_ms})
        last_ping_ts = time.time()

        while True:
            now = time.time()

            if now - last_ping_ts >= API_WS_HEARTBEAT_INTERVAL_SECONDS:
                await websocket.send_json(
                    {"type": "ping", "ts": int(now * 1000)}
                )
                last_ping_ts = now

            # Pass current_id as default arg to avoid B023 closure-capture issue.
            def _poll(stream_id: str = last_id) -> list[object]:
                import redis as _redis_sync  # noqa: PLC0415

                try:
                    r: _redis_sync.Redis = _redis_sync.Redis.from_url(
                        settings.redis_url, decode_responses=True
                    )
                    result = r.xread(
                        {SIGNAL_REDIS_STREAM: stream_id},
                        count=10,
                        block=_XREAD_BLOCK_MS,
                    )
                    r.close()  # type: ignore[no-untyped-call]
                    return cast(list[object], result or [])
                except Exception:  # noqa: BLE001
                    return []

            results = await loop.run_in_executor(None, _poll)

            for stream_entry in results:
                if not isinstance(stream_entry, (list, tuple)):
                    continue
                messages = cast(
                    list[tuple[str, dict[str, str]]], stream_entry[1]
                )
                for msg_id, fields in messages:
                    await websocket.send_json(
                        {
                            "type": "signal",
                            "id": msg_id,
                            "data": dict(fields),
                            "ts": int(time.time() * 1000),
                        }
                    )
                    last_id = msg_id

    except WebSocketDisconnect:
        pass
