"""Market Calendar & Session Manager.

Owns four things, per MASTER_BUILD_PROMPT_FINAL.MD's M02 description:

1. Holiday calendars (`HolidayCalendar` + `HolidaySource` implementations) -- live-fetch
   with local caching, refreshed weekly. Deliberately fails closed (RULE 2): if a
   weekday's holiday status can't be determined from cache or a live fetch, the system
   raises `CalendarUnavailableError` rather than silently assuming the market is open.
   Weekend closure is always known unconditionally, with no fetch required.
2. The session state machine (`SessionStateMachine`): CLOSED -> PRE_MARKET -> OPEN ->
   SNAPSHOT_WINDOW -> APPROACHING_CLOSE -> CLOSED, plus the SEBI snapshot-window flag.
3. The ASX staggered-open ticker group registry (`get_ticker_open_time`).
4. The auto square-off scheduler (`SquareOffScheduler`, fires its warning at T-20min).

Plus the `@market_hours_only` decorator factory used by later modules to gate
entry/exit logic on session state.
"""

import functools
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final, ParamSpec, TypeVar
from zoneinfo import ZoneInfo

import requests

from shared.core.config import RegionConfig, load_region_config
from shared.core.constants import (
    ASX_GROUP_OPEN_TOLERANCE_SECONDS,
    HOLIDAY_CACHE_MAX_AGE_DAYS,
    SQUARE_OFF_WARNING_LEAD_MINUTES,
)
from shared.core.exceptions import (
    CalendarFetchError,
    CalendarUnavailableError,
    MarketClosedError,
)
from shared.core.logging import configure_logging, get_logger
from shared.core.types import AppId, Exchange, SessionState

logger = get_logger(__name__)

DEFAULT_HOLIDAY_CACHE_DIR: Final[Path] = Path("shared/data/holiday_cache")


def _parse_hhmm(value: str) -> time:
    """Parse a "HH:MM" 24h string into a `time`."""
    hour_str, minute_str = value.split(":")
    return time(int(hour_str), int(minute_str))


# ---------------------------------------------------------------------------
# Holiday calendar: sources, cache, fail-closed orchestrator
# ---------------------------------------------------------------------------


class HolidaySource(ABC):
    """Fetches an exchange's trading holidays for a given year from a live source."""

    @abstractmethod
    def fetch_holidays(self, year: int) -> set[date]:
        """Return the set of non-trading holiday dates for `year`.

        Raises:
            CalendarFetchError: If the live fetch or response parsing fails.
        """


class NSEHolidaySource(HolidaySource):
    """Live fetch from NSE's public holiday-master API.

    CAVEAT: NSE's site requires a browser-like session (cookies bootstrapped from the
    main site) and commonly rejects bare requests -- confirmed blocked from this
    build's sandboxed network during M02's build (HTTP/2 stream errors on both the
    main site and the API). The endpoint/payload shape below matches NSE's
    publicly-documented `holiday-master` API as of this build, but must be
    re-verified against the live site before being relied on in production --
    treat this the same as the spec's own regulatory citations: provisional until
    cross-checked.
    """

    SITE_URL: Final[str] = "https://www.nseindia.com"
    HOLIDAY_API_URL: Final[str] = (
        "https://www.nseindia.com/api/holiday-master?type=trading"
    )
    REQUEST_TIMEOUT_SECONDS: Final[int] = 10
    HEADERS: Final[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    def fetch_holidays(self, year: int) -> set[date]:
        try:
            with requests.Session() as session:
                session.headers.update(self.HEADERS)
                session.get(self.SITE_URL, timeout=self.REQUEST_TIMEOUT_SECONDS)
                response = session.get(
                    self.HOLIDAY_API_URL, timeout=self.REQUEST_TIMEOUT_SECONDS
                )
                response.raise_for_status()
                payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CalendarFetchError(f"NSE holiday fetch failed: {exc}") from exc

        try:
            entries = payload["CM"]
            holidays = {
                datetime.strptime(entry["tradingDate"], "%d-%b-%Y").date()
                for entry in entries
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarFetchError(f"NSE holiday response malformed: {exc}") from exc

        return {d for d in holidays if d.year == year}


class ASXHolidaySource(HolidaySource):
    """Live fetch from ASX's published trading-calendar API.

    CAVEAT: unlike NSE, ASX does not publish a single well-documented stable JSON API
    for market holidays at the time of this build -- the endpoint below is a
    best-effort implementation. Re-verify the real endpoint and response shape
    against ASX's current trading-calendar page before relying on this in
    production; until then this is expected to raise `CalendarFetchError`, which
    `HolidayCalendar` handles by failing closed rather than guessing.
    """

    HOLIDAY_API_URL: Final[str] = (
        "https://www.asx.com.au/asx/v2/markets/tradingCalendar.do?format=json"
    )
    REQUEST_TIMEOUT_SECONDS: Final[int] = 10
    HEADERS: Final[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    def fetch_holidays(self, year: int) -> set[date]:
        try:
            response = requests.get(
                self.HOLIDAY_API_URL,
                headers=self.HEADERS,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CalendarFetchError(f"ASX holiday fetch failed: {exc}") from exc

        try:
            entries = payload["holidays"]
            holidays = {
                datetime.strptime(entry["date"], "%Y-%m-%d").date() for entry in entries
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarFetchError(f"ASX holiday response malformed: {exc}") from exc

        return {d for d in holidays if d.year == year}


@dataclass(frozen=True)
class HolidayCalendar:
    """Orchestrates fetch + local cache + fail-closed fallback for one exchange.

    Cache hit (fresh): returns cached data, no network call. Cache miss/stale: tries
    a live fetch, writes the cache on success. Live fetch fails with a stale cache
    present: returns the stale data with a logged warning (better than nothing).
    Live fetch fails with no cache at all: raises `CalendarUnavailableError` --
    deliberately, per RULE 2, rather than guessing.
    """

    exchange: Exchange
    source: HolidaySource
    cache_dir: Path = field(default_factory=lambda: DEFAULT_HOLIDAY_CACHE_DIR)

    def _cache_path(self, year: int) -> Path:
        return self.cache_dir / f"{self.exchange.value}_{year}.json"

    def _read_cache(self, year: int) -> tuple[set[date], datetime] | None:
        path = self._cache_path(year)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            holidays = {date.fromisoformat(d) for d in raw["holidays"]}
            fetched_at = datetime.fromisoformat(raw["fetched_at"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "holiday_cache_read_failed",
                exchange=self.exchange.value,
                year=year,
                error=str(exc),
            )
            return None
        return holidays, fetched_at

    def _write_cache(self, year: int, holidays: set[date]) -> None:
        path = self._cache_path(year)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "holidays": sorted(d.isoformat() for d in holidays),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_holidays(self, year: int) -> set[date]:
        """Return `year`'s holiday set, per the fetch/cache/fail-closed policy above.

        Raises:
            CalendarUnavailableError: No cache and the live fetch also failed.
        """
        cached = self._read_cache(year)
        if cached is not None:
            holidays, fetched_at = cached
            age = datetime.now(UTC) - fetched_at
            if age <= timedelta(days=HOLIDAY_CACHE_MAX_AGE_DAYS):
                return holidays

        try:
            fresh = self.source.fetch_holidays(year)
        except CalendarFetchError as exc:
            if cached is not None:
                logger.warning(
                    "holiday_fetch_failed_using_stale_cache",
                    exchange=self.exchange.value,
                    year=year,
                    error=str(exc),
                )
                return cached[0]
            msg = (
                f"No cached holidays for {self.exchange.value} {year} and the live "
                f"fetch failed: {exc}"
            )
            raise CalendarUnavailableError(msg) from exc

        self._write_cache(year, fresh)
        return fresh

    def is_trading_day(self, day: date) -> bool:
        """True if `day` is a trading day: not a weekend, not a known holiday.

        Weekend closure is always resolvable without any calendar data. Weekday
        holiday status requires calendar data; if none is available, this raises
        `CalendarUnavailableError` rather than assuming the market is open.
        """
        if day.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return day not in self.get_holidays(day.year)


# ---------------------------------------------------------------------------
# ASX staggered open registry
# ---------------------------------------------------------------------------

ASX_TICKER_GROUPS: Final[tuple[tuple[str, str, time], ...]] = (
    ("A", "B", time(10, 0, 0)),
    ("C", "F", time(10, 2, 15)),
    ("G", "M", time(10, 4, 30)),
    ("N", "R", time(10, 6, 45)),
    ("S", "Z", time(10, 9, 0)),
)
"""Per spec: tolerance is +/- ASX_GROUP_OPEN_TOLERANCE_SECONDS around each open time."""


def get_ticker_open_time(
    symbol: str, market_date: date, tz: ZoneInfo
) -> datetime:
    """Return the ASX staggered-open datetime for `symbol`'s alphabetical group.

    The 15-minute opening-noise-filter window (Gate 7) is computed from this
    ticker-specific time, not from the overall 10:00 session open.

    Args:
        symbol: Ticker symbol; only the first letter (case-insensitive) is used.
        market_date: The trading date the open time applies to.
        tz: Timezone to localize the result in (Australia/Sydney in production).

    Returns:
        The group's open datetime on `market_date`, localized to `tz`.

    Raises:
        ValueError: If `symbol` is empty or doesn't start with a letter A-Z.
    """
    if not symbol:
        raise ValueError("symbol must be non-empty")
    first_letter = symbol[0].upper()
    if not ("A" <= first_letter <= "Z"):
        raise ValueError(f"symbol must start with a letter A-Z, got {symbol!r}")
    for start, end, open_time in ASX_TICKER_GROUPS:
        if start <= first_letter <= end:
            return datetime.combine(market_date, open_time, tzinfo=tz)
    raise AssertionError(f"unreachable: no ASX group covers {first_letter!r}")


# ---------------------------------------------------------------------------
# Session state machine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionStateMachine:
    """CLOSED -> PRE_MARKET -> OPEN -> [SNAPSHOT_WINDOW] -> APPROACHING_CLOSE -> CLOSED.

    SNAPSHOT_WINDOW only applies when `region.snapshot_window_start_local` is set
    (India). Australia has no spec equivalent, so its sessions go straight from OPEN
    to APPROACHING_CLOSE at `square_off_local`.
    """

    region: RegionConfig
    holiday_calendar: HolidayCalendar

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.region.timezone)

    def _local_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self.tz)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def get_state(self, now: datetime | None = None) -> SessionState:
        """Return the current session state.

        Args:
            now: Timezone-aware (or naive, assumed local) instant to evaluate at.
                Defaults to the current time in the region's timezone.

        Raises:
            CalendarUnavailableError: Holiday status for today can't be determined.
        """
        local_now = self._local_now(now)
        today = local_now.date()

        if not self.holiday_calendar.is_trading_day(today):
            return SessionState.CLOSED

        t = local_now.time()
        pre_market = _parse_hhmm(self.region.pre_market_local)
        market_open = _parse_hhmm(self.region.market_open_local)
        market_close = _parse_hhmm(self.region.market_close_local)
        square_off = _parse_hhmm(self.region.square_off_local)
        snapshot_start = (
            _parse_hhmm(self.region.snapshot_window_start_local)
            if self.region.snapshot_window_start_local
            else None
        )

        if t < pre_market or t >= market_close:
            return SessionState.CLOSED
        if t < market_open:
            return SessionState.PRE_MARKET
        if t >= square_off:
            return SessionState.APPROACHING_CLOSE
        if snapshot_start is not None and t >= snapshot_start:
            return SessionState.SNAPSHOT_WINDOW
        return SessionState.OPEN

    def is_snapshot_window_active(self, now: datetime | None = None) -> bool:
        """SNAPSHOT_WINDOW_ACTIVE flag (RiskAgent reads this for 0.5x sizing, M12)."""
        return self.get_state(now) is SessionState.SNAPSHOT_WINDOW


# ---------------------------------------------------------------------------
# Auto square-off scheduler
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SquareOffScheduler:
    """Computes the T-20min square-off warning and hard square-off deadline.

    This module only computes *when* those moments occur; actually cancelling
    orders and liquidating positions is the Execution Engine's job (M14) via the
    compliance square-off script (M13). Wiring a callback/daemon to these timestamps
    is the orchestrator's job (M18).
    """

    region: RegionConfig

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.region.timezone)

    def square_off_at(self, market_date: date) -> datetime:
        return datetime.combine(
            market_date, _parse_hhmm(self.region.square_off_local), tzinfo=self.tz
        )

    def warning_at(self, market_date: date) -> datetime:
        return self.square_off_at(market_date) - timedelta(
            minutes=SQUARE_OFF_WARNING_LEAD_MINUTES
        )

    def _local_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self.tz)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def warning_due(self, now: datetime | None = None) -> bool:
        local_now = self._local_now(now)
        return local_now >= self.warning_at(local_now.date())

    def square_off_due(self, now: datetime | None = None) -> bool:
        local_now = self._local_now(now)
        return local_now >= self.square_off_at(local_now.date())


# ---------------------------------------------------------------------------
# @market_hours_only decorator
# ---------------------------------------------------------------------------

P = ParamSpec("P")
T = TypeVar("T")

TRADEABLE_STATES: Final[frozenset[SessionState]] = frozenset(
    {SessionState.OPEN, SessionState.SNAPSHOT_WINDOW}
)
"""Default `market_hours_only` allowlist: entry/exit eligible states. Callers needing
different semantics (e.g. exits also allowed during APPROACHING_CLOSE) pass their own
`allowed_states` explicitly -- be deliberate about which states bypass normal gating,
not rely on a one-size-fits-all default."""


def market_hours_only(
    get_current_state: Callable[[], SessionState],
    allowed_states: frozenset[SessionState] = TRADEABLE_STATES,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator factory: raise `MarketClosedError` outside `allowed_states`.

    Args:
        get_current_state: Callable returning the current `SessionState`, typically
            a bound `SessionStateMachine.get_state`.
        allowed_states: States in which the wrapped function may run. Defaults to
            OPEN and SNAPSHOT_WINDOW.

    Returns:
        A decorator enforcing the session-state check before each call.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            state = get_current_state()
            if state not in allowed_states:
                raise MarketClosedError(
                    f"{func.__name__} not allowed in session state {state.value}"
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# CLI: python -m shared.session_manager
# ---------------------------------------------------------------------------


def _build_session_machine(app_id: AppId) -> tuple[RegionConfig, SessionStateMachine]:
    config_path = (
        Path(__file__).resolve().parent.parent / "apps" / app_id.value / "config.yaml"
    )
    region = load_region_config(config_path)
    source: HolidaySource = (
        ASXHolidaySource() if region.exchange is Exchange.ASX else NSEHolidaySource()
    )
    calendar = HolidayCalendar(exchange=region.exchange, source=source)
    return region, SessionStateMachine(region=region, holiday_calendar=calendar)


def main() -> None:
    """Print the current session state for both apps -- the M02 VERIFY command."""
    configure_logging("INFO")

    for app_id in (AppId.INDIA, AppId.AUSTRALIA):
        region, machine = _build_session_machine(app_id)
        now = datetime.now(machine.tz)

        try:
            state = machine.get_state(now)
        except CalendarUnavailableError as exc:
            logger.error(
                "session_state_unavailable", app_id=app_id.value, error=str(exc)
            )
            continue

        scheduler = SquareOffScheduler(region=region)
        logger.info(
            "session_state",
            app_id=app_id.value,
            exchange=region.exchange.value,
            local_time=now.isoformat(),
            session_state=state.value,
            snapshot_window_active=machine.is_snapshot_window_active(now),
            square_off_warning_due=scheduler.warning_due(now),
            square_off_due=scheduler.square_off_due(now),
        )

    sydney_tz = ZoneInfo("Australia/Sydney")
    today = datetime.now(sydney_tz).date()
    example_symbol = "BHP"
    open_time = get_ticker_open_time(example_symbol, today, sydney_tz)
    logger.info(
        "asx_staggered_open_example",
        symbol=example_symbol,
        group_open_at=open_time.isoformat(),
        tolerance_seconds=ASX_GROUP_OPEN_TOLERANCE_SECONDS,
    )


if __name__ == "__main__":
    main()
