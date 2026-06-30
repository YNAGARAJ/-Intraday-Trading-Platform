"""Unit tests for shared.session_manager.

All tests here are fully deterministic and offline -- holiday data comes from an
injected FakeHolidaySource, never a real network call. Live-network behavior of the
real NSEHolidaySource/ASXHolidaySource is covered separately in
tests/integration/test_holiday_sources_live.py.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

import shared.session_manager as session_manager
from shared.core.config import RegionConfig
from shared.core.exceptions import (
    CalendarFetchError,
    CalendarUnavailableError,
    MarketClosedError,
)
from shared.core.types import AppId, Exchange, SessionState
from shared.session_manager import (
    ASX_TICKER_GROUPS,
    ASXHolidaySource,
    HolidayCalendar,
    HolidaySource,
    NSEHolidaySource,
    SessionStateMachine,
    SquareOffScheduler,
    get_ticker_group_open_time,
    market_hours_only,
)

IST = ZoneInfo("Asia/Kolkata")
AEST = ZoneInfo("Australia/Sydney")


class FakeHolidaySource(HolidaySource):
    """Deterministic, offline stand-in for a live HolidaySource."""

    def __init__(
        self, holidays: set[date] | None = None, raise_error: bool = False
    ) -> None:
        self._holidays = holidays or set()
        self._raise_error = raise_error
        self.call_count = 0

    def fetch_holidays(self, year: int) -> set[date]:
        self.call_count += 1
        if self._raise_error:
            raise CalendarFetchError("fake source failure")
        return {d for d in self._holidays if d.year == year}


def _nse_calendar(source: HolidaySource, cache_dir: Path) -> HolidayCalendar:
    return HolidayCalendar(exchange=Exchange.NSE, source=source, cache_dir=cache_dir)


def _india_region(**overrides: object) -> RegionConfig:
    defaults: dict[str, object] = {
        "app_id": AppId.INDIA,
        "exchange": Exchange.NSE,
        "broker_name": "zerodha_kite",
        "timezone": "Asia/Kolkata",
        "pre_market_local": "08:45",
        "market_open_local": "09:15",
        "market_close_local": "15:30",
        "square_off_local": "15:10",
        "snapshot_window_start_local": "14:45",
    }
    defaults.update(overrides)
    return RegionConfig.model_validate(defaults)


def _australia_region(**overrides: object) -> RegionConfig:
    defaults: dict[str, object] = {
        "app_id": AppId.AUSTRALIA,
        "exchange": Exchange.ASX,
        "broker_name": "interactive_brokers",
        "timezone": "Australia/Sydney",
        "pre_market_local": "09:15",
        "market_open_local": "10:00",
        "market_close_local": "16:00",
        "square_off_local": "15:50",
    }
    defaults.update(overrides)
    return RegionConfig.model_validate(defaults)


# A known Tuesday with no holidays configured, used as the "ordinary trading day" base.
TRADING_TUESDAY = date(2026, 6, 30)
# A known Saturday.
WEEKEND_SATURDAY = date(2026, 7, 4)


# ---------------------------------------------------------------------------
# HolidayCalendar
# ---------------------------------------------------------------------------


class TestHolidayCalendar:
    def test_fetches_and_caches_on_first_call(self, tmp_path: Path) -> None:
        source = FakeHolidaySource({date(2026, 1, 26)})
        calendar = _nse_calendar(source, tmp_path)

        holidays = calendar.get_holidays(2026)

        assert holidays == {date(2026, 1, 26)}
        assert source.call_count == 1
        assert (tmp_path / "NSE_2026.json").exists()

    def test_uses_fresh_cache_without_refetching(self, tmp_path: Path) -> None:
        source = FakeHolidaySource({date(2026, 1, 26)})
        calendar = _nse_calendar(source, tmp_path)
        calendar.get_holidays(2026)
        assert source.call_count == 1

        holidays = calendar.get_holidays(2026)

        assert holidays == {date(2026, 1, 26)}
        assert source.call_count == 1, "fresh cache must not trigger a second fetch"

    def test_refetches_when_cache_is_stale(self, tmp_path: Path) -> None:
        source = FakeHolidaySource({date(2026, 1, 26)})
        calendar = _nse_calendar(source, tmp_path)
        calendar.get_holidays(2026)

        # Backdate the cache file's fetched_at past the staleness threshold.
        import json

        cache_path = tmp_path / "NSE_2026.json"
        payload = json.loads(cache_path.read_text())
        stale_time = datetime.now().astimezone() - timedelta(days=30)
        payload["fetched_at"] = stale_time.isoformat()
        cache_path.write_text(json.dumps(payload))

        calendar.get_holidays(2026)

        assert source.call_count == 2, "stale cache must trigger a refetch"

    def test_falls_back_to_stale_cache_on_fetch_failure(self, tmp_path: Path) -> None:
        source = FakeHolidaySource({date(2026, 1, 26)})
        calendar = _nse_calendar(source, tmp_path)
        calendar.get_holidays(2026)

        import json

        cache_path = tmp_path / "NSE_2026.json"
        payload = json.loads(cache_path.read_text())
        stale_time = datetime.now().astimezone() - timedelta(days=30)
        payload["fetched_at"] = stale_time.isoformat()
        cache_path.write_text(json.dumps(payload))

        failing_source = FakeHolidaySource(raise_error=True)
        calendar_with_failing_source = _nse_calendar(failing_source, tmp_path)

        holidays = calendar_with_failing_source.get_holidays(2026)

        # Must fall back to the stale cache rather than raise on fetch failure.
        assert holidays == {date(2026, 1, 26)}

    def test_raises_calendar_unavailable_when_no_cache_and_fetch_fails(
        self, tmp_path: Path
    ) -> None:
        source = FakeHolidaySource(raise_error=True)
        calendar = _nse_calendar(source, tmp_path)

        with pytest.raises(CalendarUnavailableError):
            calendar.get_holidays(2026)

    def test_corrupted_cache_file_treated_as_missing(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "NSE_2026.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not valid json")
        source = FakeHolidaySource({date(2026, 1, 26)})
        calendar = _nse_calendar(source, tmp_path)

        holidays = calendar.get_holidays(2026)

        assert holidays == {date(2026, 1, 26)}
        assert source.call_count == 1

    def test_is_trading_day_weekend_is_always_false_without_any_calendar_data(
        self, tmp_path: Path
    ) -> None:
        source = FakeHolidaySource(raise_error=True)
        calendar = _nse_calendar(source, tmp_path)

        assert calendar.is_trading_day(WEEKEND_SATURDAY) is False
        assert source.call_count == 0, "weekend closure must not require calendar data"

    def test_is_trading_day_weekday_holiday_is_false(self, tmp_path: Path) -> None:
        source = FakeHolidaySource({TRADING_TUESDAY})
        calendar = _nse_calendar(source, tmp_path)

        assert calendar.is_trading_day(TRADING_TUESDAY) is False

    def test_is_trading_day_ordinary_weekday_is_true(self, tmp_path: Path) -> None:
        source = FakeHolidaySource(set())
        calendar = _nse_calendar(source, tmp_path)

        assert calendar.is_trading_day(TRADING_TUESDAY) is True

    def test_is_trading_day_weekday_raises_when_calendar_unavailable(
        self, tmp_path: Path
    ) -> None:
        source = FakeHolidaySource(raise_error=True)
        calendar = _nse_calendar(source, tmp_path)

        with pytest.raises(CalendarUnavailableError):
            calendar.is_trading_day(TRADING_TUESDAY)


# ---------------------------------------------------------------------------
# SessionStateMachine -- India
# ---------------------------------------------------------------------------


def _india_machine(holidays: set[date] | None = None, tmp_path: Path | None = None):  # type: ignore[no-untyped-def]
    source = FakeHolidaySource(holidays or set())
    calendar = HolidayCalendar(
        exchange=Exchange.NSE, source=source, cache_dir=tmp_path or Path("/tmp")
    )
    return SessionStateMachine(region=_india_region(), holiday_calendar=calendar)


class TestSessionStateMachineIndia:
    @pytest.mark.parametrize(
        ("hhmm", "expected"),
        [
            ("00:00", SessionState.CLOSED),
            ("08:00", SessionState.CLOSED),
            ("08:44", SessionState.CLOSED),
            ("08:45", SessionState.PRE_MARKET),
            ("09:00", SessionState.PRE_MARKET),
            ("09:14", SessionState.PRE_MARKET),
            ("09:15", SessionState.OPEN),
            ("12:00", SessionState.OPEN),
            ("14:44", SessionState.OPEN),
            ("14:45", SessionState.SNAPSHOT_WINDOW),
            ("15:00", SessionState.SNAPSHOT_WINDOW),
            ("15:09", SessionState.SNAPSHOT_WINDOW),
            ("15:10", SessionState.APPROACHING_CLOSE),
            ("15:29", SessionState.APPROACHING_CLOSE),
            ("15:30", SessionState.CLOSED),
            ("23:59", SessionState.CLOSED),
        ],
    )
    def test_state_transitions_across_the_day(
        self, tmp_path: Path, hhmm: str, expected: SessionState
    ) -> None:
        machine = _india_machine(tmp_path=tmp_path)
        hour, minute = (int(x) for x in hhmm.split(":"))
        now = datetime(2026, 6, 30, hour, minute, tzinfo=IST)

        assert machine.get_state(now) is expected

    def test_holiday_is_closed_regardless_of_time(self, tmp_path: Path) -> None:
        machine = _india_machine(holidays={TRADING_TUESDAY}, tmp_path=tmp_path)
        now = datetime(2026, 6, 30, 11, 0, tzinfo=IST)  # would be OPEN on a normal day

        assert machine.get_state(now) is SessionState.CLOSED

    def test_weekend_is_closed_regardless_of_time(self, tmp_path: Path) -> None:
        machine = _india_machine(tmp_path=tmp_path)
        now = datetime(2026, 7, 4, 11, 0, tzinfo=IST)  # Saturday

        assert machine.get_state(now) is SessionState.CLOSED

    def test_snapshot_window_flag_true_only_during_snapshot_window(
        self, tmp_path: Path
    ) -> None:
        machine = _india_machine(tmp_path=tmp_path)

        during = datetime(2026, 6, 30, 15, 0, tzinfo=IST)
        before = datetime(2026, 6, 30, 12, 0, tzinfo=IST)

        assert machine.is_snapshot_window_active(during) is True
        assert machine.is_snapshot_window_active(before) is False

    def test_naive_datetime_assumed_local(self, tmp_path: Path) -> None:
        machine = _india_machine(tmp_path=tmp_path)
        naive_now = datetime(2026, 6, 30, 12, 0)  # no tzinfo

        assert machine.get_state(naive_now) is SessionState.OPEN


# ---------------------------------------------------------------------------
# SessionStateMachine -- Australia (no snapshot window)
# ---------------------------------------------------------------------------


def _australia_machine(holidays: set[date] | None = None, tmp_path: Path | None = None):  # type: ignore[no-untyped-def]
    source = FakeHolidaySource(holidays or set())
    calendar = HolidayCalendar(
        exchange=Exchange.ASX, source=source, cache_dir=tmp_path or Path("/tmp")
    )
    return SessionStateMachine(region=_australia_region(), holiday_calendar=calendar)


class TestSessionStateMachineAustralia:
    @pytest.mark.parametrize(
        ("hhmm", "expected"),
        [
            ("09:00", SessionState.CLOSED),
            ("09:15", SessionState.PRE_MARKET),
            ("09:59", SessionState.PRE_MARKET),
            ("10:00", SessionState.OPEN),
            ("15:00", SessionState.OPEN),
            ("15:49", SessionState.OPEN),
            ("15:50", SessionState.APPROACHING_CLOSE),
            ("15:59", SessionState.APPROACHING_CLOSE),
            ("16:00", SessionState.CLOSED),
        ],
    )
    def test_state_transitions_skip_snapshot_window(
        self, tmp_path: Path, hhmm: str, expected: SessionState
    ) -> None:
        machine = _australia_machine(tmp_path=tmp_path)
        hour, minute = (int(x) for x in hhmm.split(":"))
        now = datetime(2026, 6, 30, hour, minute, tzinfo=AEST)

        assert machine.get_state(now) is expected

    def test_snapshot_window_never_active(self, tmp_path: Path) -> None:
        machine = _australia_machine(tmp_path=tmp_path)
        now = datetime(2026, 6, 30, 12, 0, tzinfo=AEST)

        assert machine.is_snapshot_window_active(now) is False


# ---------------------------------------------------------------------------
# ASX staggered open registry
# ---------------------------------------------------------------------------


class TestAsxStaggeredOpen:
    @pytest.mark.parametrize(
        ("symbol", "expected_hhmmss"),
        [
            ("AGL", "10:00:00"),
            ("BHP", "10:00:00"),
            ("CBA", "10:02:15"),
            ("FMG", "10:02:15"),
            ("GMG", "10:04:30"),
            ("MQG", "10:04:30"),
            ("NAB", "10:06:45"),
            ("RIO", "10:06:45"),
            ("STO", "10:09:00"),
            ("ZIP", "10:09:00"),
        ],
    )
    def test_group_open_time_by_symbol(self, symbol: str, expected_hhmmss: str) -> None:
        market_date = date(2026, 6, 30)
        result = get_ticker_group_open_time(symbol, market_date, AEST)

        assert result.strftime("%H:%M:%S") == expected_hhmmss
        assert result.date() == market_date
        assert result.tzinfo is not None

    def test_lowercase_symbol_normalized(self) -> None:
        market_date = date(2026, 6, 30)
        upper = get_ticker_group_open_time("BHP", market_date, AEST)
        lower = get_ticker_group_open_time("bhp", market_date, AEST)

        assert upper == lower

    def test_all_letters_covered(self) -> None:
        market_date = date(2026, 6, 30)
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            # Must not raise for any single letter.
            get_ticker_group_open_time(letter, market_date, AEST)

    def test_empty_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            get_ticker_group_open_time("", date(2026, 6, 30), AEST)

    def test_non_letter_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="A-Z"):
            get_ticker_group_open_time("1ABC", date(2026, 6, 30), AEST)

    def test_groups_cover_full_alphabet_contiguously(self) -> None:
        covered = "".join(f"{start}-{end} " for start, end, _ in ASX_TICKER_GROUPS)
        assert covered == "A-B C-F G-M N-R S-Z "


# ---------------------------------------------------------------------------
# SquareOffScheduler
# ---------------------------------------------------------------------------


class TestSquareOffScheduler:
    def test_warning_is_20_minutes_before_square_off(self) -> None:
        scheduler = SquareOffScheduler(region=_india_region())
        market_date = date(2026, 6, 30)

        square_off = scheduler.square_off_at(market_date)
        warning = scheduler.warning_at(market_date)

        assert square_off - warning == timedelta(minutes=20)
        assert square_off.strftime("%H:%M") == "15:10"
        assert warning.strftime("%H:%M") == "14:50"

    def test_warning_due_false_before_warning_time(self) -> None:
        scheduler = SquareOffScheduler(region=_india_region())
        now = datetime(2026, 6, 30, 14, 49, tzinfo=IST)

        assert scheduler.warning_due(now) is False

    def test_warning_due_true_at_and_after_warning_time(self) -> None:
        scheduler = SquareOffScheduler(region=_india_region())
        now = datetime(2026, 6, 30, 14, 50, tzinfo=IST)

        assert scheduler.warning_due(now) is True

    def test_square_off_due_false_before_deadline(self) -> None:
        scheduler = SquareOffScheduler(region=_india_region())
        now = datetime(2026, 6, 30, 15, 9, tzinfo=IST)

        assert scheduler.square_off_due(now) is False

    def test_square_off_due_true_at_deadline(self) -> None:
        scheduler = SquareOffScheduler(region=_india_region())
        now = datetime(2026, 6, 30, 15, 10, tzinfo=IST)

        assert scheduler.square_off_due(now) is True

    def test_australia_square_off_timing(self) -> None:
        scheduler = SquareOffScheduler(region=_australia_region())
        market_date = date(2026, 6, 30)

        assert scheduler.square_off_at(market_date).strftime("%H:%M") == "15:50"
        assert scheduler.warning_at(market_date).strftime("%H:%M") == "15:30"


# ---------------------------------------------------------------------------
# @market_hours_only decorator
# ---------------------------------------------------------------------------


class TestMarketHoursOnly:
    def test_allows_call_in_allowed_state(self) -> None:
        @market_hours_only(lambda: SessionState.OPEN)
        def place_order() -> str:
            return "placed"

        assert place_order() == "placed"

    def test_raises_market_closed_outside_allowed_states(self) -> None:
        calls = []

        @market_hours_only(lambda: SessionState.CLOSED)
        def place_order() -> str:
            calls.append(1)
            return "placed"

        with pytest.raises(MarketClosedError, match="CLOSED"):
            place_order()
        assert calls == [], "wrapped function must not run when market is closed"

    def test_snapshot_window_allowed_by_default(self) -> None:
        @market_hours_only(lambda: SessionState.SNAPSHOT_WINDOW)
        def place_order() -> str:
            return "placed"

        assert place_order() == "placed"

    def test_custom_allowed_states_override_default(self) -> None:
        @market_hours_only(
            lambda: SessionState.APPROACHING_CLOSE,
            allowed_states=frozenset({SessionState.APPROACHING_CLOSE}),
        )
        def close_position() -> str:
            return "closed"

        assert close_position() == "closed"

    def test_preserves_function_metadata(self) -> None:
        @market_hours_only(lambda: SessionState.OPEN)
        def my_function() -> None:
            """My docstring."""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_passes_through_args_and_kwargs(self) -> None:
        @market_hours_only(lambda: SessionState.OPEN)
        def add(a: int, b: int = 0) -> int:
            return a + b

        assert add(2, b=3) == 5


# ---------------------------------------------------------------------------
# NSEHolidaySource / ASXHolidaySource -- HTTP parsing, mocked offline
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, json_data: object, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self) -> object:
        return self._json_data


class _FakeNSESession:
    """Stand-in for requests.Session covering NSEHolidaySource's bootstrap+fetch."""

    def __init__(self, holiday_payload: object) -> None:
        self.headers: dict[str, str] = {}
        self._holiday_payload = holiday_payload

    def __enter__(self) -> "_FakeNSESession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def get(self, url: str, timeout: int) -> _FakeResponse:
        if "holiday-master" in url:
            return _FakeResponse(self._holiday_payload)
        return _FakeResponse({})


class TestNSEHolidaySource:
    def test_successful_fetch_parses_trading_dates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            "CM": [
                {"tradingDate": "26-Jan-2026"},
                {"tradingDate": "15-Aug-2026"},
            ]
        }
        monkeypatch.setattr(requests, "Session", lambda: _FakeNSESession(payload))

        holidays = NSEHolidaySource().fetch_holidays(2026)

        assert holidays == {date(2026, 1, 26), date(2026, 8, 15)}

    def test_filters_to_requested_year_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            "CM": [{"tradingDate": "26-Jan-2026"}, {"tradingDate": "01-Jan-2027"}]
        }
        monkeypatch.setattr(requests, "Session", lambda: _FakeNSESession(payload))

        holidays = NSEHolidaySource().fetch_holidays(2026)

        assert holidays == {date(2026, 1, 26)}

    def test_request_exception_raises_calendar_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FailingSession(_FakeNSESession):
            def get(self, url: str, timeout: int) -> _FakeResponse:
                raise requests.ConnectionError("boom")

        monkeypatch.setattr(requests, "Session", lambda: _FailingSession({}))

        with pytest.raises(CalendarFetchError, match="fetch failed"):
            NSEHolidaySource().fetch_holidays(2026)

    def test_malformed_response_raises_calendar_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            requests,
            "Session",
            lambda: _FakeNSESession({"unexpected": "shape"}),
        )

        with pytest.raises(CalendarFetchError, match="malformed"):
            NSEHolidaySource().fetch_holidays(2026)


class TestASXHolidaySource:
    def test_successful_fetch_parses_dates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {"holidays": [{"date": "2026-01-01"}, {"date": "2026-12-25"}]}

        def _fake_get(url: str, headers: dict[str, str], timeout: int) -> _FakeResponse:
            return _FakeResponse(payload)

        monkeypatch.setattr(requests, "get", _fake_get)

        holidays = ASXHolidaySource().fetch_holidays(2026)

        assert holidays == {date(2026, 1, 1), date(2026, 12, 25)}

    def test_request_exception_raises_calendar_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_get(url: str, headers: dict[str, str], timeout: int) -> _FakeResponse:
            raise requests.ConnectionError("boom")

        monkeypatch.setattr(requests, "get", _fake_get)

        with pytest.raises(CalendarFetchError, match="fetch failed"):
            ASXHolidaySource().fetch_holidays(2026)

    def test_malformed_response_raises_calendar_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_get(url: str, headers: dict[str, str], timeout: int) -> _FakeResponse:
            return _FakeResponse({"unexpected": "shape"})

        monkeypatch.setattr(requests, "get", _fake_get)

        with pytest.raises(CalendarFetchError, match="malformed"):
            ASXHolidaySource().fetch_holidays(2026)


# ---------------------------------------------------------------------------
# CLI: _build_session_machine / main()
# ---------------------------------------------------------------------------


class TestCli:
    def test_build_session_machine_india(self) -> None:
        region, machine = session_manager._build_session_machine(AppId.INDIA)

        assert region.app_id is AppId.INDIA
        assert isinstance(machine.holiday_calendar.source, NSEHolidaySource)

    def test_build_session_machine_australia(self) -> None:
        region, machine = session_manager._build_session_machine(AppId.AUSTRALIA)

        assert region.app_id is AppId.AUSTRALIA
        assert isinstance(machine.holiday_calendar.source, ASXHolidaySource)

    def test_main_prints_session_state_for_both_apps(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _fake_build(app_id: AppId) -> tuple[RegionConfig, SessionStateMachine]:
            region = _india_region() if app_id is AppId.INDIA else _australia_region()
            calendar = _nse_calendar(FakeHolidaySource(set()), tmp_path)
            return region, SessionStateMachine(region=region, holiday_calendar=calendar)

        monkeypatch.setattr(session_manager, "_build_session_machine", _fake_build)

        session_manager.main()

        captured = capsys.readouterr()
        assert '"event": "session_state"' in captured.out
        assert '"event": "asx_staggered_open_example"' in captured.out

    def test_main_handles_calendar_unavailable_gracefully(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _fake_build(app_id: AppId) -> tuple[RegionConfig, SessionStateMachine]:
            region = _india_region() if app_id is AppId.INDIA else _australia_region()
            calendar = _nse_calendar(FakeHolidaySource(raise_error=True), tmp_path)
            return region, SessionStateMachine(region=region, holiday_calendar=calendar)

        monkeypatch.setattr(session_manager, "_build_session_machine", _fake_build)

        session_manager.main()  # must not raise

        captured = capsys.readouterr()
        assert '"event": "session_state_unavailable"' in captured.out
