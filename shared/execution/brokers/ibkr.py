"""Interactive Brokers TWS broker adapter — interface stub (M14).

Authentication and connection pool are provided by M15.  All methods raise
``NotImplementedError`` until M15 wires up the ``ibapi.client.EClient``
connection with a valid ``clientId``.

Key constraints:
- Paper account port: 7497 (env-controlled, never hardcoded).
- Live account port: 7496 (env-controlled, never hardcoded).
- IBKR short-sell: symbol must appear on IBKR's locate-available list
  (verified by M13 compliance ``approved_short_list``).
- 7-year trade log retention: S3 lifecycle policy (M23 infra/).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from shared.compliance.models import TaggedOrder
    from shared.execution.models import FillReport

logger = structlog.get_logger(__name__)


class IBKRBroker:
    """Interactive Brokers TWS broker adapter (requires M15 connection pool).

    Args:
        tws_client: Authenticated ``ibapi`` EClient/EWrapper instance
            (provided by M15 ``IBKRConnectionPool``).  Pass ``None`` during
            construction — M15 injects it before first use.
    """

    def __init__(self, tws_client: object | None = None) -> None:
        self._tws = tws_client

    def _require_auth(self) -> None:
        if self._tws is None:
            raise NotImplementedError(
                "IBKRBroker requires a live TWS connection from M15. "
                "Inject via tws_client parameter after M15 authentication."
            )

    def place_order(self, tagged: TaggedOrder) -> FillReport:
        """Submit order to IBKR TWS (requires M15 connection).

        Raises:
            NotImplementedError: Until M15 provides a live TWS connection.
        """
        self._require_auth()
        raise NotImplementedError("IBKRBroker.place_order requires M15 connection")

    def query_order(self, client_order_id: str) -> FillReport | None:
        """Query IBKR order book by client_order_id before any retry.

        Raises:
            NotImplementedError: Until M15 provides a live TWS connection.
        """
        self._require_auth()
        raise NotImplementedError("IBKRBroker.query_order requires M15 connection")

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a live IBKR order.

        Raises:
            NotImplementedError: Until M15 provides a live TWS connection.
        """
        self._require_auth()
        raise NotImplementedError("IBKRBroker.cancel_order requires M15 connection")

    def inject_client(self, tws_client: object) -> None:
        """Inject the authenticated TWS client from M15."""
        self._tws = tws_client
        logger.info("ibkr_broker_client_injected")
