"""Back-adjusts a raw OHLCV price series for splits and bonuses.

Scope (see ADR-010): only SPLIT and BONUS actions adjust price/volume here.
DIVIDEND is recorded but not applied as a price adjustment -- a correct cash-dividend
(total-return) adjustment needs the close price on the day before ex-date, which
depends on point-in-time data this pure function deliberately doesn't fetch.
SYMBOL_CHANGE is recorded but doesn't affect price; stitching a renamed symbol's
history into its predecessor's is deferred until a module actually needs it.
"""

from collections.abc import Sequence

from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction
from shared.storage.models import OHLCVCandle

_PRICE_ADJUSTING_TYPES = (CorporateActionType.SPLIT, CorporateActionType.BONUS)


def adjusted_candles(
    candles: Sequence[OHLCVCandle], actions: Sequence[CorporateAction]
) -> list[OHLCVCandle]:
    """Return a back-adjusted copy of `candles`.

    For every SPLIT/BONUS in `actions` whose `ex_date` falls after a candle's date,
    that candle's open/high/low/close are multiplied by
    `ratio_denominator / ratio_numerator` and volume by the inverse, so the series
    reads as if the action had always been in effect -- e.g. a 1:2 split halves every
    pre-split price and doubles every pre-split volume. Multiple actions compound.

    Args:
        candles: Time-ordered candles for a single symbol/exchange.
        actions: Corporate actions for that *same* symbol/exchange -- this function
            does not filter by symbol/exchange identity, so passing actions for a
            different instrument silently produces wrong results. Callers (e.g.
            `shared.instruments.service.get_adjusted_series`) are responsible for
            only passing actions that match.

    Returns:
        A new list of `OHLCVCandle`; `candles` itself is never mutated.
    """
    if not candles:
        return []

    relevant = sorted(
        (a for a in actions if a.action_type in _PRICE_ADJUSTING_TYPES),
        key=lambda a: a.ex_date,
    )

    adjusted = []
    for candle in candles:
        candle_date = candle.time.date()
        price_mult = 1.0
        volume_mult = 1.0
        for action in relevant:
            if candle_date < action.ex_date:
                # mypy can't see __post_init__'s validation guarantees these are
                # non-None/positive for SPLIT/BONUS -- asserted, not re-validated.
                assert action.ratio_numerator is not None
                assert action.ratio_denominator is not None
                price_mult *= action.ratio_denominator / action.ratio_numerator
                volume_mult *= action.ratio_numerator / action.ratio_denominator
        adjusted.append(
            OHLCVCandle(
                time=candle.time,
                symbol=candle.symbol,
                exchange=candle.exchange,
                open=candle.open * price_mult,
                high=candle.high * price_mult,
                low=candle.low * price_mult,
                close=candle.close * price_mult,
                volume=round(candle.volume * volume_mult),
            )
        )
    return adjusted
