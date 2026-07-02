"""Unit tests for M13 StrategyRegistry."""

from __future__ import annotations

import os
from unittest.mock import patch

from shared.compliance.strategy_registry import (
    GENERIC_ALGO_TAG,
    STRATEGY_EMA_VWAP_TREND,
    STRATEGY_GENERIC,
    STRATEGY_MEAN_REVERT_PIVOT,
    STRATEGY_MOMENTUM_RSI,
    STRATEGY_ORB_BREAKOUT,
    STRATEGY_ORDER_FLOW_ABSORPTION,
    StrategyRegistry,
)


class TestStrategyRegistry:
    def test_default_tags(self) -> None:
        reg = StrategyRegistry(use_generic=False)
        assert reg.resolve(STRATEGY_EMA_VWAP_TREND) == "STRAT001"
        assert reg.resolve(STRATEGY_ORB_BREAKOUT) == "STRAT002"
        assert reg.resolve(STRATEGY_MOMENTUM_RSI) == "STRAT003"
        assert reg.resolve(STRATEGY_MEAN_REVERT_PIVOT) == "STRAT004"
        assert reg.resolve(STRATEGY_ORDER_FLOW_ABSORPTION) == "STRAT005"

    def test_generic_mode_all_return_genalg01(self) -> None:
        reg = StrategyRegistry(use_generic=True)
        assert reg.resolve(STRATEGY_EMA_VWAP_TREND) == GENERIC_ALGO_TAG
        assert reg.resolve(STRATEGY_ORB_BREAKOUT) == GENERIC_ALGO_TAG
        assert reg.resolve(STRATEGY_ORDER_FLOW_ABSORPTION) == GENERIC_ALGO_TAG

    def test_unknown_strategy_returns_none(self) -> None:
        reg = StrategyRegistry(use_generic=False)
        assert reg.resolve("UNKNOWN_ALGO") is None

    def test_generic_tag_exactly_8_chars(self) -> None:
        assert len(GENERIC_ALGO_TAG) == 8

    def test_all_default_tags_at_most_8_chars(self) -> None:
        reg = StrategyRegistry(use_generic=False)
        for tag in reg.all_tags().values():
            assert len(tag) <= 8

    def test_env_override(self) -> None:
        env = {"STRATEGY_ID_EMA_VWAP_TREND": "CUSTOM01"}
        with patch.dict(os.environ, env):
            reg = StrategyRegistry(use_generic=False)
        assert reg.resolve(STRATEGY_EMA_VWAP_TREND) == "CUSTOM01"

    def test_env_override_too_long_truncated(self) -> None:
        env = {"STRATEGY_ID_MOMENTUM_RSI": "TOOLONGNAME"}
        with patch.dict(os.environ, env):
            reg = StrategyRegistry(use_generic=False)
        tag = reg.resolve(STRATEGY_MOMENTUM_RSI)
        assert tag is not None
        assert len(tag) <= 8

    def test_all_strategies_returns_all_names(self) -> None:
        reg = StrategyRegistry(use_generic=False)
        names = reg.all_strategies()
        assert STRATEGY_EMA_VWAP_TREND in names
        assert STRATEGY_GENERIC in names
        assert len(names) == 6

    def test_use_generic_property(self) -> None:
        reg = StrategyRegistry(use_generic=True)
        assert reg.use_generic is True
        reg2 = StrategyRegistry(use_generic=False)
        assert reg2.use_generic is False

    def test_env_use_generic_algo_id(self) -> None:
        with patch.dict(os.environ, {"USE_GENERIC_ALGO_ID": "true"}):
            reg = StrategyRegistry()
        assert reg.use_generic is True
        assert reg.resolve(STRATEGY_EMA_VWAP_TREND) == GENERIC_ALGO_TAG

    def test_all_tags_returns_copy(self) -> None:
        reg = StrategyRegistry(use_generic=False)
        tags = reg.all_tags()
        tags["EXTRA"] = "XXXXX"
        assert "EXTRA" not in reg.all_tags()
