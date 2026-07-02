"""Data models for M15 Authentication & Token Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AuthMode(str, Enum):
    """Authentication mode — controls which credentials are required."""

    PAPER = "PAPER"
    """No real credentials required; paper token used for simulation."""

    LIVE = "LIVE"
    """Live broker credentials required; real access tokens used."""


@dataclass(frozen=True)
class TokenRecord:
    """A broker access token with metadata.

    Args:
        broker: Broker identifier (``"kite"`` or ``"ibkr"``).
        access_token: The raw token string.  Never logged.
        issued_at_ms: Unix epoch milliseconds when the token was obtained.
        expires_at_ms: Unix epoch milliseconds when the token expires.
        user_id: Broker user/account ID.
        mode: Auth mode at the time the token was issued.
    """

    broker: str
    access_token: str
    issued_at_ms: int
    expires_at_ms: int
    user_id: str
    mode: AuthMode

    def is_valid(self, now_ms: int) -> bool:
        """Return True if the token has not yet expired."""
        return now_ms < self.expires_at_ms

    def __repr__(self) -> str:
        return (
            f"TokenRecord(broker={self.broker!r}, user_id={self.user_id!r}, "
            f"mode={self.mode.value!r}, expires_at_ms={self.expires_at_ms})"
        )


@dataclass
class IBKRClientSlot:
    """One clientId slot in the IBKR connection pool.

    Args:
        client_id: The IBKR clientId integer (0-31).
        host: TWS host address.
        port: TWS port (7497 paper / 7496 live).
        in_use: Whether this slot is currently checked out.
        connection: Live EClient object (``None`` until connected).
    """

    client_id: int
    host: str
    port: int
    in_use: bool = False
    connection: object | None = field(default=None, repr=False)

    def acquire(self) -> None:
        """Mark this slot as in use."""
        self.in_use = True

    def release(self) -> None:
        """Mark this slot as available."""
        self.in_use = False
