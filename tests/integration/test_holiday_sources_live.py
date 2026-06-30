"""Live network tests for the real NSE/ASX HolidaySource implementations.

These hit real external endpoints and are expected to be environment-dependent (see
the CAVEAT docstrings on NSEHolidaySource/ASXHolidaySource in shared/session_manager.py
-- NSE blocks bare/bot-like requests in some networks, and ASX has no confirmed stable
public JSON API). A fetch failure here is treated as a skip, not a test failure: the
offline unit suite (tests/unit/test_session_manager.py) is what guarantees
HolidayCalendar's own caching/fail-closed logic is correct. These tests just observe
real external behavior when the network permits it.
"""

from datetime import datetime

import pytest

from shared.core.exceptions import CalendarFetchError
from shared.session_manager import ASXHolidaySource, NSEHolidaySource


def test_nse_live_fetch_returns_plausible_holidays() -> None:
    source = NSEHolidaySource()
    year = datetime.now().year

    try:
        holidays = source.fetch_holidays(year)
    except CalendarFetchError as exc:
        pytest.skip(f"NSE live holiday endpoint unreachable/blocked: {exc}")

    assert len(holidays) > 0
    assert all(d.year == year for d in holidays)


def test_asx_live_fetch_returns_plausible_holidays() -> None:
    source = ASXHolidaySource()
    year = datetime.now().year

    try:
        holidays = source.fetch_holidays(year)
    except CalendarFetchError as exc:
        pytest.skip(f"ASX live holiday endpoint unreachable/blocked: {exc}")

    assert all(d.year == year for d in holidays)
