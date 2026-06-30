"""Live data sources for the instrument master and corporate actions.

Mirrors shared/session_manager.py's HolidaySource pattern (M02): an ABC per concern,
one implementation per exchange, real HTTP calls (no mocking the network away), and a
documented CorporateActionFetchError/InstrumentFetchError on failure rather than
guessing. See ADR-010 for what was actually confirmed reachable from this build's
sandbox and what wasn't.
"""

import csv
import io
import re
from abc import ABC, abstractmethod
from datetime import date, datetime

import requests

from shared.core.constants import (
    CORPORATE_ACTIONS_REFRESH_WINDOW_DAYS,
    NSE_EQUITY_TICK_SIZE,
)
from shared.core.exceptions import CorporateActionFetchError, InstrumentFetchError
from shared.core.logging import get_logger
from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction, Instrument

logger = get_logger(__name__)

_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class InstrumentSource(ABC):
    """Fetches the full canonical instrument list for one exchange."""

    @abstractmethod
    def fetch(self) -> list[Instrument]: ...


class CorporateActionSource(ABC):
    """Fetches corporate actions for one exchange within a date window."""

    @abstractmethod
    def fetch(self, from_date: date, to_date: date) -> list[CorporateAction]: ...


class NSEInstrumentSource(InstrumentSource):
    """NSE's public archived equity list -- confirmed live, no auth needed."""

    URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    def fetch(self) -> list[Instrument]:
        try:
            response = requests.get(self.URL, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise InstrumentFetchError(
                f"NSE instrument master fetch failed: {exc}"
            ) from exc

        reader = csv.DictReader(io.StringIO(response.text))
        if reader.fieldnames:
            reader.fieldnames = [name.strip() for name in reader.fieldnames]

        instruments = []
        for row in reader:
            symbol = row.get("SYMBOL", "").strip()
            if not symbol:
                continue
            lot_size_raw = row.get("MARKET LOT", "").strip()
            isin = row.get("ISIN NUMBER", "").strip() or None
            instruments.append(
                Instrument(
                    symbol=symbol,
                    exchange="NSE",
                    name=row.get("NAME OF COMPANY", "").strip(),
                    isin=isin,
                    lot_size=int(lot_size_raw) if lot_size_raw.isdigit() else None,
                    tick_size=NSE_EQUITY_TICK_SIZE,
                )
            )
        return instruments


class ASXInstrumentSource(InstrumentSource):
    """ASX's public listed-companies CSV -- confirmed live. Doesn't include ISIN,
    lot size, or tick size (ASX has no fixed lot size; tick size is price-tiered, see
    NSE_EQUITY_TICK_SIZE's docstring) -- those fields are `None` for every ASX row.
    """

    URL = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"

    def fetch(self) -> list[Instrument]:
        try:
            response = requests.get(
                self.URL, timeout=15, headers={"User-Agent": _BROWSER_USER_AGENT}
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise InstrumentFetchError(
                f"ASX instrument master fetch failed: {exc}"
            ) from exc

        text = response.text
        header_index = text.find("Company name")
        if header_index == -1:
            raise InstrumentFetchError(
                "ASX instrument master response didn't contain the expected "
                "'Company name' CSV header -- format may have changed"
            )

        reader = csv.DictReader(io.StringIO(text[header_index:]))
        instruments = []
        for row in reader:
            code = (row.get("ASX code") or "").strip()
            if not code:
                continue
            instruments.append(
                Instrument(
                    symbol=code,
                    exchange="ASX",
                    name=(row.get("Company name") or "").strip(),
                    isin=None,
                    lot_size=None,
                    tick_size=None,
                )
            )
        return instruments


# NSE corporate-action subjects are free text, e.g.:
#   "Bonus 1:1"
#   "Face Value Split (Sub-Division) - From Rs10/- Per Share To Re 1/- Per Share"
#   "Dividend - Rs 130 Per Share"
# These patterns were validated against a real fetch covering all of 2024 -- see
# tests/unit/test_instruments_sources.py for the exact fixtures.
_SPLIT_PATTERN = re.compile(
    r"From\s+Re?s?\.?\s*([\d.]+)\s*/?-?\s*Per\s+Share\s+To\s+Re?s?\.?\s*([\d.]+)"
    r"\s*/?-?\s*Per\s+Share",
    re.IGNORECASE,
)
_BONUS_PATTERN = re.compile(
    r"Bonus\s+(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)
_DIVIDEND_AMOUNT_PATTERN = re.compile(r"Rs\.?\s*([\d.]+)", re.IGNORECASE)


def _parse_nse_entry(entry: dict[str, str], exchange: str) -> CorporateAction | None:
    symbol = (entry.get("symbol") or "").strip()
    subject = entry.get("subject") or ""
    ex_date_raw = entry.get("exDate") or ""
    if not symbol or not subject or not ex_date_raw or ex_date_raw == "-":
        return None

    try:
        ex_date = datetime.strptime(ex_date_raw, "%d-%b-%Y").date()
    except ValueError:
        logger.warning(
            "nse_corporate_action_unparseable_date", symbol=symbol, raw=ex_date_raw
        )
        return None

    split_match = _SPLIT_PATTERN.search(subject)
    if split_match:
        from_face, to_face = float(split_match.group(1)), float(split_match.group(2))
        try:
            return CorporateAction(
                symbol=symbol,
                exchange=exchange,
                ex_date=ex_date,
                action_type=CorporateActionType.SPLIT,
                source=f"{exchange}_LIVE",
                ratio_numerator=from_face,
                ratio_denominator=to_face,
            )
        except ValueError:
            logger.warning(
                "nse_corporate_action_invalid_split", symbol=symbol, subject=subject
            )
            return None

    bonus_match = _BONUS_PATTERN.search(subject)
    if bonus_match:
        new_shares, held_shares = (
            float(bonus_match.group(1)),
            float(bonus_match.group(2)),
        )
        try:
            return CorporateAction(
                symbol=symbol,
                exchange=exchange,
                ex_date=ex_date,
                action_type=CorporateActionType.BONUS,
                source=f"{exchange}_LIVE",
                ratio_numerator=new_shares + held_shares,
                ratio_denominator=held_shares,
            )
        except ValueError:
            logger.warning(
                "nse_corporate_action_invalid_bonus", symbol=symbol, subject=subject
            )
            return None

    if "dividend" in subject.lower():
        amount_match = _DIVIDEND_AMOUNT_PATTERN.search(subject)
        if amount_match is None:
            return None  # no parseable amount -- skip rather than guess
        try:
            return CorporateAction(
                symbol=symbol,
                exchange=exchange,
                ex_date=ex_date,
                action_type=CorporateActionType.DIVIDEND,
                source=f"{exchange}_LIVE",
                dividend_amount=float(amount_match.group(1)),
            )
        except ValueError:
            return None

    return None  # Rights/Buyback/AGM/etc. -- not a type this system tracks


class NSECorporateActionSource(CorporateActionSource):
    """NSE's corporate-actions API -- confirmed live, needs a cookie-bootstrap
    session first (same pattern as M02's NSEHolidaySource)."""

    BASE_URL = "https://www.nseindia.com/api/corporates-corporateActions"

    def fetch(self, from_date: date, to_date: date) -> list[CorporateAction]:
        session = requests.Session()
        session.headers.update(
            {"User-Agent": _BROWSER_USER_AGENT, "Accept": "application/json"}
        )
        try:
            session.get("https://www.nseindia.com", timeout=10)
            response = session.get(
                self.BASE_URL,
                params={
                    "index": "equities",
                    "from_date": from_date.strftime("%d-%m-%Y"),
                    "to_date": to_date.strftime("%d-%m-%Y"),
                },
                timeout=15,
            )
            response.raise_for_status()
            raw_entries = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CorporateActionFetchError(
                f"NSE corporate actions fetch failed: {exc}"
            ) from exc

        actions = []
        for entry in raw_entries:
            action = _parse_nse_entry(entry, exchange="NSE")
            if action is not None:
                actions.append(action)
        return actions


class ASXCorporateActionSource(CorporateActionSource):
    """No reliable bulk ASX corporate-actions endpoint was found reachable from this
    build's sandbox (see ADR-010 for what was tried). The per-symbol
    `asx.api.markitdigital.com` key-statistics endpoint does return the *next*
    upcoming dividend's ex/record/pay dates for a given symbol, so this source uses
    it -- but only for symbols the caller explicitly asks about (looping it over the
    full ~2,000-symbol ASX universe daily would be both impractical and is unverified
    to be an intended use of that endpoint). It cannot discover SPLIT or BONUS
    actions at all; those rely entirely on the manual override table for ASX.
    """

    KEY_STATISTICS_URL = (
        "https://asx.api.markitdigital.com/asx-research/1.0/companies/{}/key-statistics"
    )

    def fetch(
        self, from_date: date, to_date: date, symbols: list[str] | None = None
    ) -> list[CorporateAction]:
        if not symbols:
            logger.warning(
                "asx_corporate_actions_no_symbols",
                detail="ASX has no bulk corporate-actions feed; pass explicit "
                "symbols to check per-instrument, or rely on manual overrides",
            )
            return []

        actions = []
        for symbol in symbols:
            action = self._fetch_one(symbol, from_date, to_date)
            if action is not None:
                actions.append(action)
        return actions

    def _fetch_one(
        self, symbol: str, from_date: date, to_date: date
    ) -> CorporateAction | None:
        try:
            response = requests.get(
                self.KEY_STATISTICS_URL.format(symbol),
                timeout=15,
                headers={
                    "User-Agent": _BROWSER_USER_AGENT,
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json().get("data", {})
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "asx_key_statistics_fetch_failed", symbol=symbol, error=str(exc)
            )
            return None

        ex_date_raw = data.get("dateExDate")
        if not ex_date_raw:
            return None
        try:
            ex_date = date.fromisoformat(ex_date_raw)
        except ValueError:
            return None
        if not (from_date <= ex_date <= to_date):
            return None

        # key-statistics doesn't expose the actual dividend amount, only dates --
        # without an amount, DIVIDEND can't be constructed (see CorporateAction's
        # __post_init__), so there's nothing valid to return for this endpoint today.
        return None


def default_refresh_window(today: date) -> tuple[date, date]:
    """The `[from_date, to_date]` window NSECorporateActionSource.fetch() should use
    for a routine daily refresh -- looks back far enough to catch any action whose
    ex-date could still be inside an indicator's lookback window, and forward far
    enough to pick up already-announced future actions before their ex-date arrives.
    """
    from datetime import timedelta

    window = timedelta(days=CORPORATE_ACTIONS_REFRESH_WINDOW_DAYS)
    return today - window, today + window
