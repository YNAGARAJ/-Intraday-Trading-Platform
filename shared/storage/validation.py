"""Tick data validation: reject out-of-sequence, corrupt, or zero-price ticks before
they reach storage.

`TickSequenceValidator` is stateful (tracks the last-seen timestamp per symbol+exchange)
because "out-of-sequence" is inherently a relative check -- one instance per ingestion
stream, not a free function.
"""

from datetime import datetime

from shared.core.exceptions import DataValidationError
from shared.storage.models import Tick


def _validate_tick_shape(tick: Tick) -> None:
    """Stateless checks: corrupt fields, zero/negative price, negative volume."""
    if not tick.symbol or not tick.exchange:
        raise DataValidationError(f"corrupt tick: missing symbol/exchange ({tick!r})")
    if tick.price <= 0:
        raise DataValidationError(f"non-positive price tick rejected: {tick!r}")
    if tick.volume < 0:
        raise DataValidationError(f"negative volume tick rejected: {tick!r}")


class TickSequenceValidator:
    """Validates ticks are well-formed and arrive in non-decreasing time order, per
    (symbol, exchange) pair.
    """

    def __init__(self) -> None:
        self._last_seen: dict[tuple[str, str], datetime] = {}

    def validate(self, tick: Tick) -> None:
        """Validate `tick`.

        Raises:
            DataValidationError: If the tick is corrupt, zero/negative price,
                negative volume, or older than the last tick seen for this symbol.
        """
        _validate_tick_shape(tick)

        key = (tick.symbol, tick.exchange)
        last_seen = self._last_seen.get(key)
        if last_seen is not None and tick.time < last_seen:
            raise DataValidationError(
                f"out-of-sequence tick for {tick.symbol}/{tick.exchange}: "
                f"{tick.time.isoformat()} precedes last-seen {last_seen.isoformat()}"
            )
        self._last_seen[key] = tick.time

    def reset(self, symbol: str | None = None, exchange: str | None = None) -> None:
        """Clear sequence state, e.g. at the start of a new trading session.

        Args:
            symbol: If given (with `exchange`), clear only that pair's state.
            exchange: If given (with `symbol`), clear only that pair's state.
        """
        if symbol is not None and exchange is not None:
            self._last_seen.pop((symbol, exchange), None)
        else:
            self._last_seen.clear()
