"""Live network tests for the real NSE/ASX instrument and corporate-action sources.

Same rationale as test_holiday_sources_live.py (M02): these hit real external
endpoints and are environment-dependent. A fetch failure here is a skip, not a
failure -- the offline unit suite (test_instruments_sources.py) guarantees the
parsing logic itself is correct; this just observes real external behavior when the
network permits it. See ADR-010 for what was confirmed reachable during this build.
"""

from datetime import date, timedelta

import pytest

from shared.core.exceptions import CorporateActionFetchError, InstrumentFetchError
from shared.instruments.sources import (
    ASXInstrumentSource,
    NSECorporateActionSource,
    NSEInstrumentSource,
)


def test_nse_instrument_master_live_fetch_returns_plausible_data() -> None:
    try:
        instruments = NSEInstrumentSource().fetch()
    except InstrumentFetchError as exc:
        pytest.skip(f"NSE instrument master endpoint unreachable: {exc}")

    assert len(instruments) > 1000  # NSE lists thousands of equities
    assert all(i.exchange == "NSE" for i in instruments)
    assert any(i.symbol == "RELIANCE" for i in instruments)


def test_asx_instrument_master_live_fetch_returns_plausible_data() -> None:
    try:
        instruments = ASXInstrumentSource().fetch()
    except InstrumentFetchError as exc:
        pytest.skip(f"ASX instrument master endpoint unreachable: {exc}")

    assert len(instruments) > 500
    assert all(i.exchange == "ASX" for i in instruments)
    assert any(i.symbol == "BHP" for i in instruments)


def test_nse_corporate_actions_live_fetch_returns_plausible_data() -> None:
    today = date.today()
    try:
        actions = NSECorporateActionSource().fetch(today - timedelta(days=365), today)
    except CorporateActionFetchError as exc:
        pytest.skip(f"NSE corporate actions endpoint unreachable: {exc}")

    assert len(actions) > 0
    assert all(a.exchange == "NSE" for a in actions)
    assert all(a.source == "NSE_LIVE" for a in actions)
