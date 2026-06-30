"""Unit tests for shared.indicators.utils.last_value."""

import numpy as np

from shared.indicators.utils import last_value


class TestLastValue:
    def test_returns_the_final_element(self) -> None:
        assert last_value(np.array([1.0, 2.0, 3.0])) == 3.0

    def test_nan_becomes_none(self) -> None:
        assert last_value(np.array([1.0, np.nan])) is None

    def test_empty_array_returns_none(self) -> None:
        assert last_value(np.array([])) is None
