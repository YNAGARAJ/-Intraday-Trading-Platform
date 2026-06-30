"""Refresh orchestration and the adjusted-series convenience function downstream
modules (M04/M06/M07/M08) should actually call.
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from shared.core.logging import get_logger
from shared.instruments.adjustment import adjusted_candles
from shared.instruments.manual_overrides import load_manual_overrides
from shared.instruments.models import CorporateAction, Instrument
from shared.instruments.sources import (
    ASXInstrumentSource,
    InstrumentSource,
    NSECorporateActionSource,
    NSEInstrumentSource,
    default_refresh_window,
)
from shared.storage.models import OHLCVCandle

logger = get_logger(__name__)

_INSTRUMENT_SOURCES: dict[str, InstrumentSource] = {
    "NSE": NSEInstrumentSource(),
    "ASX": ASXInstrumentSource(),
}


class InstrumentWriter(Protocol):
    """What `refresh_instrument_master` needs -- structurally satisfied by
    `InstrumentRepository` and by any test double exposing just `upsert_many`."""

    def upsert_many(self, instruments: Sequence[Instrument]) -> int: ...


class CorporateActionStore(Protocol):
    """What `refresh_corporate_actions`/`get_adjusted_series` need -- structurally
    satisfied by `CorporateActionRepository`."""

    def upsert_many(self, actions: Sequence[CorporateAction]) -> int: ...
    def list_for_symbol(self, symbol: str, exchange: str) -> list[CorporateAction]: ...


def refresh_instrument_master(repository: InstrumentWriter, exchange: str) -> int:
    """Fetch `exchange`'s live instrument list and upsert it. Returns rows written.

    Raises:
        InstrumentFetchError: If the live fetch fails -- the table simply keeps
            whatever was written by the last successful refresh (no different from
            M02's holiday-cache fallback: a failed refresh isn't a crash, it's a
            stale-but-still-usable instrument master).
    """
    source = _INSTRUMENT_SOURCES[exchange]
    instruments = source.fetch()
    written = repository.upsert_many(instruments)
    logger.info("instrument_master_refreshed", exchange=exchange, rows=written)
    return written


def refresh_corporate_actions(
    repository: CorporateActionStore, today: date | None = None
) -> int:
    """Refresh NSE corporate actions for the standard daily window, then apply
    manual overrides last so they take precedence on any collision. Returns the
    total number of rows written (live + manual).

    ASX corporate actions aren't refreshed here -- see ASXCorporateActionSource's
    docstring; ASX relies on the manual override table for now (ADR-010).
    """
    today = today or date.today()
    from_date, to_date = default_refresh_window(today)

    live_actions = NSECorporateActionSource().fetch(from_date, to_date)
    live_written = repository.upsert_many(live_actions)

    manual_overrides = load_manual_overrides()
    manual_written = repository.upsert_many(manual_overrides)

    logger.info(
        "corporate_actions_refreshed",
        live_rows=live_written,
        manual_rows=manual_written,
        window_start=from_date.isoformat(),
        window_end=to_date.isoformat(),
    )
    return live_written + manual_written


def get_adjusted_series(
    repository: CorporateActionStore,
    symbol: str,
    exchange: str,
    candles: Sequence[OHLCVCandle],
) -> list[OHLCVCandle]:
    """The function M04/M06/M07/M08 should call instead of reading raw OHLCV: looks
    up `symbol`'s corporate actions and returns a back-adjusted copy of `candles`.
    """
    actions = repository.list_for_symbol(symbol, exchange)
    return adjusted_candles(candles, actions)
