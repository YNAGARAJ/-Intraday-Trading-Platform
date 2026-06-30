"""Tests for shared.core.exceptions: hierarchy invariants."""

import pytest

from shared.core.exceptions import (
    ComplianceViolationError,
    ConfigValidationError,
    InsufficientMarginError,
    KillSwitchActiveError,
    MarketClosedError,
    NoStopLossError,
    OrderIdempotencyError,
    RateLimitExceededError,
    ReconciliationMismatchError,
    TradingSystemError,
)

ALL_SUBCLASSES = [
    ConfigValidationError,
    MarketClosedError,
    NoStopLossError,
    InsufficientMarginError,
    RateLimitExceededError,
    ComplianceViolationError,
    KillSwitchActiveError,
    ReconciliationMismatchError,
    OrderIdempotencyError,
]


@pytest.mark.parametrize("exc_cls", ALL_SUBCLASSES)
def test_all_exceptions_derive_from_trading_system_error(
    exc_cls: type[TradingSystemError],
) -> None:
    assert issubclass(exc_cls, TradingSystemError)


def test_trading_system_error_is_catchable_broadly() -> None:
    with pytest.raises(TradingSystemError):
        raise NoStopLossError("missing stop-loss metadata")


def test_exceptions_carry_message() -> None:
    exc = NoStopLossError("order rejected: no SL")
    assert str(exc) == "order rejected: no SL"
