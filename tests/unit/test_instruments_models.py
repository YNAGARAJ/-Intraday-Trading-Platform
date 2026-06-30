"""Unit tests for CorporateAction's __post_init__ validation -- the invariant that a
SPLIT/BONUS/DIVIDEND/SYMBOL_CHANGE action can never be constructed without the data
it needs to actually be applied. See shared/instruments/models.py's module docstring
for why this matters more than typical validation.
"""

from datetime import date

import pytest

from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
EX_DATE = date(2024, 1, 5)


class TestSplitValidation:
    def test_valid_split_constructs(self) -> None:
        action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=EX_DATE,
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2.0,
            ratio_denominator=1.0,
        )
        assert action.ratio_numerator == 2.0

    def test_missing_ratio_numerator_raises(self) -> None:
        with pytest.raises(ValueError, match="requires positive ratio"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.SPLIT,
                source="NSE_LIVE",
                ratio_denominator=1.0,
            )

    def test_missing_ratio_denominator_raises(self) -> None:
        with pytest.raises(ValueError, match="requires positive ratio"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.SPLIT,
                source="NSE_LIVE",
                ratio_numerator=2.0,
            )

    def test_negative_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.SPLIT,
                source="NSE_LIVE",
                ratio_numerator=-2.0,
                ratio_denominator=1.0,
            )

    def test_zero_ratio_raises(self) -> None:
        with pytest.raises(ValueError):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.SPLIT,
                source="NSE_LIVE",
                ratio_numerator=0.0,
                ratio_denominator=1.0,
            )


class TestBonusValidation:
    def test_valid_bonus_constructs(self) -> None:
        action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=EX_DATE,
            action_type=CorporateActionType.BONUS,
            source="NSE_LIVE",
            ratio_numerator=2.0,
            ratio_denominator=1.0,
        )
        assert action.action_type is CorporateActionType.BONUS

    def test_missing_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="requires positive ratio"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.BONUS,
                source="NSE_LIVE",
            )


class TestDividendValidation:
    def test_valid_dividend_constructs(self) -> None:
        action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=EX_DATE,
            action_type=CorporateActionType.DIVIDEND,
            source="NSE_LIVE",
            dividend_amount=15.0,
        )
        assert action.dividend_amount == 15.0

    def test_missing_amount_raises(self) -> None:
        with pytest.raises(ValueError, match="requires a positive dividend_amount"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.DIVIDEND,
                source="NSE_LIVE",
            )

    def test_zero_amount_raises(self) -> None:
        with pytest.raises(ValueError, match="requires a positive dividend_amount"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.DIVIDEND,
                source="NSE_LIVE",
                dividend_amount=0.0,
            )


class TestSymbolChangeValidation:
    def test_valid_symbol_change_constructs(self) -> None:
        action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=EX_DATE,
            action_type=CorporateActionType.SYMBOL_CHANGE,
            source="MANUAL",
            new_symbol="NEWNAME",
        )
        assert action.new_symbol == "NEWNAME"

    def test_missing_new_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="requires new_symbol"):
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=EX_DATE,
                action_type=CorporateActionType.SYMBOL_CHANGE,
                source="MANUAL",
            )
