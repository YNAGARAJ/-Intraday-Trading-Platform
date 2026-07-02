"""Zerodha Kite Connect broker adapter — interface stub (M14).

Authentication and token management are provided by M15.  This stub
implements the ``BrokerAdapter`` interface so M14's execution engine can
type-check against it, but all methods raise ``NotImplementedError`` until
M15 wires up the authenticated ``KiteConnect`` instance.

Key constraints:
- ``client_order_id`` mapped to Kite's ``tag`` field (≤ 8 chars: uses the
  compliance-resolved ``strategy_tag`` from the ``TaggedOrder``).
- All live orders require ``TRADING_MODE=LIVE`` + valid session token from M15.
- Paper mode uses ``PaperBroker`` — this class is only active in live mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from shared.compliance.models import TaggedOrder
    from shared.execution.models import FillReport

logger = structlog.get_logger(__name__)


class KiteBroker:
    """Zerodha Kite Connect broker adapter (requires M15 session token).

    Args:
        kite_client: Authenticated ``kiteconnect.KiteConnect`` instance
            (provided by M15 ``TokenManager``).  Pass ``None`` during
            construction — M15 injects it before first use.
    """

    def __init__(self, kite_client: object | None = None) -> None:
        self._kite = kite_client

    def _require_auth(self) -> None:
        if self._kite is None:
            raise NotImplementedError(
                "KiteBroker requires a live KiteConnect session from M15. "
                "Inject via kite_client parameter after M15 authentication."
            )

    def place_order(self, tagged: TaggedOrder) -> FillReport:
        """Submit order to Kite Connect API (requires M15 auth token).

        Raises:
            NotImplementedError: Until M15 provides a live session token.
        """
        self._require_auth()
        raise NotImplementedError("KiteBroker.place_order requires M15 auth")

    def query_order(self, client_order_id: str) -> FillReport | None:
        """Query Kite order book by client_order_id before any retry.

        Raises:
            NotImplementedError: Until M15 provides a live session token.
        """
        self._require_auth()
        raise NotImplementedError("KiteBroker.query_order requires M15 auth")

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a live Kite order.

        Raises:
            NotImplementedError: Until M15 provides a live session token.
        """
        self._require_auth()
        raise NotImplementedError("KiteBroker.cancel_order requires M15 auth")

    def inject_client(self, kite_client: object) -> None:
        """Inject the authenticated KiteConnect client from M15."""
        self._kite = kite_client
        logger.info("kite_broker_client_injected")
