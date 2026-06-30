"""Unit tests for shared.storage.validation.TickSequenceValidator."""

from datetime import datetime, timedelta

import pytest

from shared.core.exceptions import DataValidationError
from shared.storage.models import Tick
from shared.storage.validation import TickSequenceValidator

T0 = datetime(2026, 6, 30, 9, 15, 0)


def _tick(**overrides: object) -> Tick:
    defaults: dict[str, object] = {
        "time": T0,
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "price": 2450.5,
        "volume": 100,
    }
    defaults.update(overrides)
    return Tick(**defaults)  # type: ignore[arg-type]


class TestTickSequenceValidator:
    def test_valid_ascending_sequence_accepted(self) -> None:
        validator = TickSequenceValidator()

        validator.validate(_tick(time=T0))
        validator.validate(_tick(time=T0 + timedelta(seconds=1)))
        validator.validate(_tick(time=T0 + timedelta(seconds=1)))  # equal time is fine

    def test_out_of_sequence_tick_rejected(self) -> None:
        validator = TickSequenceValidator()
        validator.validate(_tick(time=T0))

        with pytest.raises(DataValidationError, match="out-of-sequence"):
            validator.validate(_tick(time=T0 - timedelta(seconds=1)))

    def test_zero_price_tick_rejected(self) -> None:
        validator = TickSequenceValidator()

        with pytest.raises(DataValidationError, match="price"):
            validator.validate(_tick(price=0.0))

    def test_negative_price_tick_rejected(self) -> None:
        validator = TickSequenceValidator()

        with pytest.raises(DataValidationError, match="price"):
            validator.validate(_tick(price=-1.0))

    def test_negative_volume_tick_rejected(self) -> None:
        validator = TickSequenceValidator()

        with pytest.raises(DataValidationError, match="volume"):
            validator.validate(_tick(volume=-10))

    def test_missing_symbol_rejected(self) -> None:
        validator = TickSequenceValidator()

        with pytest.raises(DataValidationError, match="corrupt"):
            validator.validate(_tick(symbol=""))

    def test_missing_exchange_rejected(self) -> None:
        validator = TickSequenceValidator()

        with pytest.raises(DataValidationError, match="corrupt"):
            validator.validate(_tick(exchange=""))

    def test_independent_state_per_symbol_exchange_pair(self) -> None:
        validator = TickSequenceValidator()
        validator.validate(_tick(symbol="RELIANCE", time=T0))

        # A different symbol's out-of-order tick must not be affected by RELIANCE's
        # state.
        validator.validate(_tick(symbol="TCS", time=T0 - timedelta(days=1)))

    def test_reset_clears_all_state(self) -> None:
        validator = TickSequenceValidator()
        validator.validate(_tick(time=T0))
        validator.reset()

        # No longer "out of sequence" since state was cleared.
        validator.validate(_tick(time=T0 - timedelta(seconds=1)))

    def test_reset_specific_pair_only(self) -> None:
        validator = TickSequenceValidator()
        validator.validate(_tick(symbol="RELIANCE", time=T0))
        validator.validate(_tick(symbol="TCS", time=T0))

        validator.reset(symbol="RELIANCE", exchange="NSE")

        validator.validate(_tick(symbol="RELIANCE", time=T0 - timedelta(seconds=1)))
        with pytest.raises(DataValidationError, match="out-of-sequence"):
            validator.validate(_tick(symbol="TCS", time=T0 - timedelta(seconds=1)))

    def test_rejected_tick_does_not_advance_state(self) -> None:
        """A rejected (e.g. zero-price) tick must not update last-seen-time."""
        validator = TickSequenceValidator()
        validator.validate(_tick(time=T0))

        with pytest.raises(DataValidationError):
            validator.validate(_tick(time=T0 + timedelta(seconds=10), price=0.0))

        # The bad tick's timestamp must not have been recorded as "last seen".
        validator.validate(_tick(time=T0 + timedelta(seconds=1)))
