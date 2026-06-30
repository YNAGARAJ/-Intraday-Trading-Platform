"""Data models for the instrument master and corporate actions.

`CorporateAction` validates its own shape at construction time: a SPLIT/BONUS row
without a ratio, or a DIVIDEND row without an amount, can't be created at all. This
matters more than usual validation would -- a `CorporateAction` that silently carries
no usable adjustment data is exactly the failure mode this module exists to prevent
(per the spec: "without this, ATR, indicators, and regime classification silently
corrupt around ex-dates"). Parsers (shared/instruments/sources.py) that can't extract
a valid ratio/amount/new_symbol from raw feed text must skip the row and log why,
not construct a half-populated action.
"""

from dataclasses import dataclass
from datetime import date

from shared.core.types import CorporateActionType


@dataclass(frozen=True)
class Instrument:
    """One row of the canonical instrument list."""

    symbol: str
    exchange: str
    name: str
    isin: str | None
    lot_size: int | None
    tick_size: float | None
    """`None` for ASX: tick size there is price-tiered, not a fixed per-instrument
    value -- see NSE_EQUITY_TICK_SIZE's docstring in shared/core/constants.py."""


@dataclass(frozen=True)
class CorporateAction:
    """One corporate action affecting a symbol's historical price series.

    `source` distinguishes a live-fetched row ("NSE_LIVE" / "ASX_LIVE") from a
    `MANUAL` override -- the refresh service always applies manual overrides last, so
    they take precedence on a (symbol, exchange, ex_date, action_type) collision.
    """

    symbol: str
    exchange: str
    ex_date: date
    action_type: CorporateActionType
    source: str
    ratio_numerator: float | None = None
    """SPLIT/BONUS only: new shares per `ratio_denominator` old shares held."""
    ratio_denominator: float | None = None
    dividend_amount: float | None = None
    """DIVIDEND only: cash amount per share, in the exchange's local currency."""
    new_symbol: str | None = None
    """SYMBOL_CHANGE only: the symbol this instrument trades under after ex_date."""

    def __post_init__(self) -> None:
        if self.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS):
            if not self.ratio_numerator or not self.ratio_denominator:
                raise ValueError(
                    f"{self.action_type} requires positive ratio_numerator and "
                    f"ratio_denominator: {self}"
                )
            if self.ratio_numerator <= 0 or self.ratio_denominator <= 0:
                raise ValueError(f"ratio must be positive: {self}")
        elif self.action_type is CorporateActionType.DIVIDEND:
            if not self.dividend_amount or self.dividend_amount <= 0:
                raise ValueError(
                    f"DIVIDEND requires a positive dividend_amount: {self}"
                )
        elif self.action_type is CorporateActionType.SYMBOL_CHANGE:
            if not self.new_symbol:
                raise ValueError(f"SYMBOL_CHANGE requires new_symbol: {self}")
