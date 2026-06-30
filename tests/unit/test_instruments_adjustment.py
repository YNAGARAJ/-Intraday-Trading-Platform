"""Unit tests for shared.instruments.adjustment.adjusted_candles."""

from datetime import UTC, date, datetime

from shared.core.types import CorporateActionType
from shared.instruments.adjustment import adjusted_candles
from shared.instruments.models import CorporateAction
from shared.storage.models import OHLCVCandle

SYMBOL = "PGIL"
EXCHANGE = "NSE"


def _candle(day: int, price: float, volume: int) -> OHLCVCandle:
    return OHLCVCandle(
        time=datetime(2024, 1, day, tzinfo=UTC),
        symbol=SYMBOL,
        exchange=EXCHANGE,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=volume,
    )


def _split(ex_date: date, numerator: float, denominator: float) -> CorporateAction:
    return CorporateAction(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        ex_date=ex_date,
        action_type=CorporateActionType.SPLIT,
        source="NSE_LIVE",
        ratio_numerator=numerator,
        ratio_denominator=denominator,
    )


class TestAdjustedCandles:
    def test_empty_candles_returns_empty(self) -> None:
        assert adjusted_candles([], [_split(date(2024, 1, 5), 2, 1)]) == []

    def test_no_actions_returns_unchanged_values(self) -> None:
        candles = [_candle(3, 200.0, 1000)]

        adjusted = adjusted_candles(candles, [])

        assert adjusted[0].close == 200.0
        assert adjusted[0].volume == 1000

    def test_real_pgil_split_halves_pre_split_price_doubles_volume(self) -> None:
        # Real NSE event: PGIL face value split 10 -> 5, ex_date 2024-01-05.
        candles = [
            _candle(3, 200.0, 1000),  # before ex_date
            _candle(4, 204.0, 1100),  # before ex_date
            _candle(5, 101.0, 2200),  # on ex_date -- not adjusted (< comparison)
            _candle(8, 103.0, 2300),  # after ex_date
        ]
        split = _split(date(2024, 1, 5), numerator=10, denominator=5)

        adjusted = adjusted_candles(candles, [split])

        assert adjusted[0].close == 100.0
        assert adjusted[0].volume == 2000
        assert adjusted[1].close == 102.0
        assert adjusted[1].volume == 2200
        assert adjusted[2].close == 101.0  # ex_date bar itself: unchanged
        assert adjusted[2].volume == 2200
        assert adjusted[3].close == 103.0  # after: unchanged
        assert adjusted[3].volume == 2300

    def test_two_splits_compound(self) -> None:
        # A 1:2 split (ratio 2:1) then later another 1:2 split -- a bar before both
        # should be quartered.
        candles = [_candle(1, 400.0, 100)]
        actions = [
            _split(date(2024, 2, 1), numerator=2, denominator=1),
            _split(date(2024, 3, 1), numerator=2, denominator=1),
        ]

        adjusted = adjusted_candles(candles, actions)

        assert adjusted[0].close == 100.0
        assert adjusted[0].volume == 400

    def test_dividend_and_symbol_change_do_not_adjust_price(self) -> None:
        candles = [_candle(3, 200.0, 1000)]
        actions = [
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=date(2024, 1, 5),
                action_type=CorporateActionType.DIVIDEND,
                source="NSE_LIVE",
                dividend_amount=10.0,
            ),
            CorporateAction(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                ex_date=date(2024, 1, 5),
                action_type=CorporateActionType.SYMBOL_CHANGE,
                source="MANUAL",
                new_symbol="NEWNAME",
            ),
        ]

        adjusted = adjusted_candles(candles, actions)

        assert adjusted[0].close == 200.0
        assert adjusted[0].volume == 1000

    def test_original_candles_not_mutated(self) -> None:
        candles = [_candle(3, 200.0, 1000)]
        split = _split(date(2024, 1, 5), numerator=2, denominator=1)

        adjusted_candles(candles, [split])

        assert candles[0].close == 200.0
        assert candles[0].volume == 1000

    def test_preserves_time_symbol_exchange(self) -> None:
        candles = [_candle(3, 200.0, 1000)]
        split = _split(date(2024, 1, 5), numerator=2, denominator=1)

        adjusted = adjusted_candles(candles, [split])

        assert adjusted[0].time == candles[0].time
        assert adjusted[0].symbol == SYMBOL
        assert adjusted[0].exchange == EXCHANGE
