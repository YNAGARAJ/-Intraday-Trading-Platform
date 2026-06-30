"""Unit tests for shared.indicators.registry -- isolated from the real built-in
indicators so these don't depend on (or permanently clobber, for later test modules
in the same pytest process) the registrations shared/indicators/definitions/ performs
on import.
"""

from collections.abc import Iterator

import pytest

import shared.indicators.registry as registry_module
from shared.core.exceptions import DuplicateIndicatorError
from shared.indicators.models import CandleArrays
from shared.indicators.registry import (
    all_indicators,
    register_indicator,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    # Snapshot and restore rather than reset_registry()'s permanent clear: other test
    # modules in this same pytest process import shared.indicators.engine, which
    # registers the real built-in indicators as an import-time side effect that only
    # runs once per process -- destroying that registration here would break every
    # test that runs afterward, not just this file's own tests.
    original = dict(registry_module._REGISTRY)
    registry_module._REGISTRY.clear()
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


def _fake_compute(candles: CandleArrays) -> dict[str, float | None]:
    return {"FAKE": 1.0}


class TestRegisterIndicator:
    def test_registers_with_name_and_min_candles(self) -> None:
        register_indicator("FAKE", min_candles=5)(_fake_compute)

        specs = all_indicators()

        assert "FAKE" in specs
        assert specs["FAKE"].min_candles == 5
        assert specs["FAKE"].compute is _fake_compute

    def test_duplicate_name_raises(self) -> None:
        register_indicator("FAKE", min_candles=5)(_fake_compute)

        with pytest.raises(DuplicateIndicatorError):
            register_indicator("FAKE", min_candles=10)(_fake_compute)

    def test_returns_the_original_function_unchanged(self) -> None:
        decorated = register_indicator("FAKE", min_candles=5)(_fake_compute)

        assert decorated is _fake_compute


class TestAllIndicators:
    def test_returns_a_copy_not_the_live_registry(self) -> None:
        register_indicator("FAKE", min_candles=5)(_fake_compute)

        snapshot = all_indicators()
        snapshot["INJECTED"] = snapshot["FAKE"]

        assert "INJECTED" not in all_indicators()

    def test_empty_when_nothing_registered(self) -> None:
        assert all_indicators() == {}


class TestResetRegistry:
    def test_clears_all_registrations(self) -> None:
        register_indicator("FAKE", min_candles=5)(_fake_compute)

        reset_registry()

        assert all_indicators() == {}
