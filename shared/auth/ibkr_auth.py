"""IBKR TWS connection pool with clientId management and heartbeat (M15).

Manages a fixed pool of ``IBKRClientSlot`` instances.  Each slot holds one
clientId and (when connected) an ``ibapi.client.EClient`` connection.  The
pool is safe for concurrent use: slot acquisition and release use a lock.

Heartbeat:
    A background thread calls ``reqCurrentTime()`` every
    ``IBKR_HEARTBEAT_INTERVAL_SECONDS`` on each live connection to prevent TWS
    from dropping the socket.

Port assignment:
    - Paper account: ``IBKR_PAPER_PORT`` (7497) — env-controlled.
    - Live account:  ``IBKR_LIVE_PORT``  (7496) — env-controlled.
    Never hardcoded in logic — always read from constants (sourced from env).
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from shared.auth.models import AuthMode, IBKRClientSlot
from shared.auth.token_store import AuthError
from shared.core.constants import (
    IBKR_CLIENT_ID_POOL_MAX,
    IBKR_CONNECTION_TIMEOUT_SECONDS,
    IBKR_HEARTBEAT_INTERVAL_SECONDS,
    IBKR_LIVE_PORT,
    IBKR_PAPER_PORT,
)

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


@runtime_checkable
class _EClientProto(Protocol):
    """Structural interface used to type IBKR EClient connections."""

    def connect(self, host: str, port: int, client_id: int) -> None:
        ...

    def isConnected(self) -> bool:  # noqa: N802
        ...

    def run(self) -> None:
        ...

    def reqCurrentTime(self) -> None:  # noqa: N802
        ...

    def disconnect(self) -> None:
        ...


class IBKRConnectionPool:
    """Fixed-size pool of IBKR TWS clientId slots.

    Args:
        host: TWS host address (default ``"127.0.0.1"``).
        mode: ``AuthMode.PAPER`` uses port 7497; ``AuthMode.LIVE`` uses 7496.
        pool_size: Number of clientId slots (max ``IBKR_CLIENT_ID_POOL_MAX``).
        start_client_id: First clientId in the pool (typically 0).
        enable_heartbeat: Start background heartbeat thread on construction.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        mode: AuthMode = AuthMode.PAPER,
        pool_size: int = 4,
        start_client_id: int = 0,
        enable_heartbeat: bool = False,
    ) -> None:
        if pool_size > IBKR_CLIENT_ID_POOL_MAX:
            raise ValueError(
                f"pool_size={pool_size} exceeds IBKR_CLIENT_ID_POOL_MAX="
                f"{IBKR_CLIENT_ID_POOL_MAX}"
            )
        self._host = host
        self._port = IBKR_PAPER_PORT if mode == AuthMode.PAPER else IBKR_LIVE_PORT
        self._mode = mode
        self._lock = threading.Lock()
        self._slots: list[IBKRClientSlot] = [
            IBKRClientSlot(
                client_id=start_client_id + i,
                host=host,
                port=self._port,
            )
            for i in range(pool_size)
        ]
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        if enable_heartbeat:
            self._start_heartbeat()

    @property
    def port(self) -> int:
        """Return the TWS port configured for this pool."""
        return self._port

    def acquire(self) -> IBKRClientSlot:
        """Check out a free slot from the pool.

        Returns:
            An ``IBKRClientSlot`` with ``in_use=True``.

        Raises:
            AuthError: If all slots are currently in use.
        """
        with self._lock:
            for slot in self._slots:
                if not slot.in_use:
                    slot.acquire()
                    logger.info(
                        "ibkr_slot_acquired",
                        client_id=slot.client_id,
                        host=slot.host,
                        port=slot.port,
                    )
                    return slot
        raise AuthError(
            f"IBKR connection pool exhausted (all {len(self._slots)} slots in use)"
        )

    def release(self, slot: IBKRClientSlot) -> None:
        """Return a slot to the pool.

        Args:
            slot: The slot previously returned by ``acquire()``.
        """
        with self._lock:
            slot.release()
        logger.info("ibkr_slot_released", client_id=slot.client_id)

    def connect(self, slot: IBKRClientSlot) -> bool:
        """Attempt to connect the slot's EClient to TWS.

        If ``ibapi`` is not installed, logs a warning and returns ``False``
        (paper mode doesn't require a real TWS connection).

        Args:
            slot: Slot to connect (must be acquired first).

        Returns:
            ``True`` on success, ``False`` if ibapi is unavailable.
        """
        try:
            from ibapi.client import EClient  # noqa: PLC0415
            from ibapi.wrapper import EWrapper  # noqa: PLC0415

            class _Wrapper(EWrapper):  # type: ignore[misc]
                pass

            wrapper = _Wrapper()
            client = EClient(wrapper)
            client.connect(slot.host, slot.port, slot.client_id)
            deadline = time.time() + IBKR_CONNECTION_TIMEOUT_SECONDS
            while not client.isConnected() and time.time() < deadline:
                client.run()
            if not client.isConnected():
                logger.warning(
                    "ibkr_connect_timeout",
                    client_id=slot.client_id,
                    timeout_s=IBKR_CONNECTION_TIMEOUT_SECONDS,
                )
                return False
            slot.connection = client
            logger.info(
                "ibkr_connected",
                client_id=slot.client_id,
                host=slot.host,
                port=slot.port,
            )
            return True
        except ImportError:
            logger.warning(
                "ibapi_not_installed_skipping_real_connection",
                client_id=slot.client_id,
            )
            return False

    def _heartbeat_loop(self) -> None:
        """Background loop: pings each live TWS connection every N seconds."""
        while not self._heartbeat_stop.is_set():
            with self._lock:
                live = [s for s in self._slots if s.connection is not None]
            for slot in live:
                conn = slot.connection
                if conn is None:
                    continue
                eclient = conn if isinstance(conn, _EClientProto) else None
                try:
                    if eclient is not None:
                        eclient.reqCurrentTime()
                    logger.debug("ibkr_heartbeat_sent", client_id=slot.client_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ibkr_heartbeat_error",
                        client_id=slot.client_id,
                        error=str(exc),
                    )
            self._heartbeat_stop.wait(timeout=IBKR_HEARTBEAT_INTERVAL_SECONDS)

    def _start_heartbeat(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="ibkr-heartbeat"
        )
        self._heartbeat_thread.start()
        logger.info(
            "ibkr_heartbeat_started",
            interval_s=IBKR_HEARTBEAT_INTERVAL_SECONDS,
        )

    def shutdown(self) -> None:
        """Stop the heartbeat thread and disconnect all slots."""
        self._heartbeat_stop.set()
        with self._lock:
            for slot in self._slots:
                if slot.connection is not None:
                    conn = slot.connection
                    eclient = conn if isinstance(conn, _EClientProto) else None
                    try:
                        if eclient is not None:
                            eclient.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                    slot.connection = None
                slot.release()
        logger.info("ibkr_pool_shutdown")

    def available_count(self) -> int:
        """Return the number of free slots."""
        with self._lock:
            return sum(1 for s in self._slots if not s.in_use)

    def pool_size(self) -> int:
        """Return the total number of slots."""
        return len(self._slots)
