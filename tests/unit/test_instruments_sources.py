"""Unit tests for the NSE corporate-action subject-text parser -- entirely offline,
using real subject strings captured from a live fetch (see sources.py's module-level
comment above _SPLIT_PATTERN) rather than the network itself. Live reachability is
covered separately in tests/integration/test_instruments_live_sources.py.
"""

from datetime import date

from shared.core.types import CorporateActionType
from shared.instruments.sources import (
    ASXInstrumentSource,
    NSEInstrumentSource,
    _parse_nse_entry,
)


def _entry(symbol: str, subject: str, ex_date: str = "05-Jan-2024") -> dict[str, str]:
    return {"symbol": symbol, "subject": subject, "exDate": ex_date}


class TestParseSplit:
    def test_face_value_split_with_space(self) -> None:
        action = _parse_nse_entry(
            _entry(
                "PGIL",
                "Face Value Split (Sub-Division) - "
                "From Rs 10/- Per Share To Rs 5/- Per Share",
            ),
            "NSE",
        )
        assert action is not None
        assert action.action_type is CorporateActionType.SPLIT
        assert action.ratio_numerator == 10.0
        assert action.ratio_denominator == 5.0

    def test_face_value_split_no_space_and_re_singular(self) -> None:
        action = _parse_nse_entry(
            _entry(
                "NESTLEIND",
                "Face Value Split (Sub-Division) - "
                "From Rs10/- Per Share To Re 1/- Per Share",
            ),
            "NSE",
        )
        assert action is not None
        assert action.action_type is CorporateActionType.SPLIT
        assert action.ratio_numerator == 10.0
        assert action.ratio_denominator == 1.0


class TestParseBonus:
    def test_bonus_one_to_one(self) -> None:
        action = _parse_nse_entry(_entry("ESSENTIA", "Bonus 1:1"), "NSE")
        assert action is not None
        assert action.action_type is CorporateActionType.BONUS
        assert action.ratio_numerator == 2.0
        assert action.ratio_denominator == 1.0

    def test_bonus_three_to_one(self) -> None:
        action = _parse_nse_entry(_entry("ALLCARGO", "Bonus 3:1"), "NSE")
        assert action is not None
        assert action.ratio_numerator == 4.0
        assert action.ratio_denominator == 1.0


class TestParseDividend:
    def test_dividend_with_amount(self) -> None:
        action = _parse_nse_entry(
            _entry("BAJAJHLDNG", "Dividend - Rs 130 Per Share"), "NSE"
        )
        assert action is not None
        assert action.action_type is CorporateActionType.DIVIDEND
        assert action.dividend_amount == 130.0

    def test_dividend_without_amount_is_skipped(self) -> None:
        action = _parse_nse_entry(
            _entry("XYZ", "Annual General Meeting/Dividend"), "NSE"
        )
        assert action is None


class TestParseIgnoredOrInvalid:
    def test_rights_issue_is_ignored(self) -> None:
        action = _parse_nse_entry(_entry("XYZ", "Rights 1:1 @ Premium Rs 15/"), "NSE")
        assert action is None

    def test_agm_only_is_ignored(self) -> None:
        action = _parse_nse_entry(_entry("XYZ", "Annual General Meeting"), "NSE")
        assert action is None

    def test_unparseable_date_is_skipped(self) -> None:
        action = _parse_nse_entry(
            _entry("XYZ", "Bonus 1:1", ex_date="not-a-date"), "NSE"
        )
        assert action is None

    def test_placeholder_dash_date_is_skipped(self) -> None:
        action = _parse_nse_entry(_entry("XYZ", "Bonus 1:1", ex_date="-"), "NSE")
        assert action is None

    def test_missing_symbol_is_skipped(self) -> None:
        action = _parse_nse_entry(
            {"symbol": "", "subject": "Bonus 1:1", "exDate": "05-Jan-2024"}, "NSE"
        )
        assert action is None

    def test_ex_date_parsed_correctly(self) -> None:
        action = _parse_nse_entry(
            _entry("ESSENTIA", "Bonus 1:1", ex_date="11-Jan-2024"), "NSE"
        )
        assert action is not None
        assert action.ex_date == date(2024, 1, 11)


class TestInstrumentSourceUrls:
    """Sanity-check the source classes are wired to the URLs this build confirmed
    reachable -- not a live network test (see ADR-010 / test_instruments_live_sources.py
    for that), just guarding against an accidental URL typo regression."""

    def test_nse_url(self) -> None:
        assert "archives.nseindia.com" in NSEInstrumentSource.URL

    def test_asx_url(self) -> None:
        assert "asx.com.au" in ASXInstrumentSource.URL
