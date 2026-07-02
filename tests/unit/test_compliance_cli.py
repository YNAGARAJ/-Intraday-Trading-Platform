"""Unit tests for M13 compliance CLI — VERIFY 20 scenarios."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from shared.compliance.cli import (
    _SCENARIO_TABLE,
    _run_scenario,
    cmd_verify,
)
from shared.compliance.engine import ComplianceEngine
from shared.compliance.strategy_registry import StrategyRegistry


def _engine() -> ComplianceEngine:
    return ComplianceEngine(registry=StrategyRegistry(use_generic=False))


def _args(scenario: str = "all") -> argparse.Namespace:
    return argparse.Namespace(scenario=scenario)


class TestScenarioTable:
    def test_exactly_20_scenarios(self) -> None:
        assert len(_SCENARIO_TABLE) == 20

    def test_all_names_unique(self) -> None:
        names = [n for (n, _, _) in _SCENARIO_TABLE]
        assert len(names) == len(set(names))

    def test_expected_non_compliant_count(self) -> None:
        blocked = [n for (n, _, e) in _SCENARIO_TABLE if not e]
        assert len(blocked) >= 9, "At least 9 scenarios should be blocked"

    def test_expected_compliant_count(self) -> None:
        approved = [n for (n, _, e) in _SCENARIO_TABLE if e]
        assert len(approved) >= 8


class TestIndividualScenarios:
    def test_01_missing_strategy_id(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("01_missing_strategy_id", eng)
        assert result is False  # should be blocked
        assert extra is True  # NO_STRATEGY_ID code present

    def test_02_ema_vwap_trend(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("02_ema_vwap_trend", eng)
        assert result is True
        assert extra is True  # STRAT001 tag confirmed

    def test_07_generic_algo_id(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("07_generic_algo_id", eng)
        assert result is True
        assert extra is True  # GENALG01 tag confirmed

    def test_08_mpp_buy(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("08_market_order_buy_mpp", eng)
        assert result is True
        assert extra is True

    def test_09_mpp_sell(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("09_market_order_sell_mpp", eng)
        assert result is True
        assert extra is True

    def test_10_leverage(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("10_leverage_exceeded", eng)
        assert result is False
        assert extra is True

    def test_11_mwpl(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("11_mwpl_exceeded", eng)
        assert result is False
        assert extra is True

    def test_12_force_square_off(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("12_force_square_off", eng)
        assert result is False
        assert extra is True

    def test_13_wash_trading(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("13_wash_trading", eng)
        assert result is False
        assert extra is True

    def test_14_layering(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("14_layering", eng)
        assert result is False
        assert extra is True

    def test_15_short_not_approved(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("15_short_sell_not_approved", eng)
        assert result is False
        assert extra is True

    def test_16_short_approved(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("16_short_sell_approved", eng)
        assert result is True
        assert extra is True

    def test_17_staggered_open(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("17_staggered_open", eng)
        assert result is False
        assert extra is True

    def test_18_post_close(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("18_post_close_cutoff", eng)
        assert result is False
        assert extra is True

    def test_19_kill_switch_tier1(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("19_kill_switch_tier1", eng)
        assert result is True
        assert extra is True

    def test_20_kill_switch_tiers23(self) -> None:
        eng = _engine()
        result, extra = _run_scenario("20_kill_switch_tiers_23", eng)
        assert result is True
        assert extra is True


class TestCmdVerify:
    def test_all_scenarios_return_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_verify(_args("all"))
        assert rc == 0

    def test_output_contains_verify_pass(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_verify(_args("all"))
        out = capsys.readouterr().out
        assert "VERIFY PASS" in out

    def test_output_contains_20_scenarios(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_verify(_args("all"))
        out = capsys.readouterr().out
        assert "20/20" in out

    def test_single_scenario_returns_0(self) -> None:
        rc = cmd_verify(_args("01_missing_strategy_id"))
        assert rc == 0

    def test_unknown_scenario_returns_1(self) -> None:
        rc = cmd_verify(_args("nonexistent_scenario"))
        assert rc == 1

    def test_all_pass_zero_exit(self) -> None:
        rc = cmd_verify(_args("all"))
        assert rc == 0


class TestMain:
    def test_no_command_exits_0(self) -> None:
        with patch("sys.argv", ["shared.compliance"]):
            with pytest.raises(SystemExit) as exc_info:
                from shared.compliance.cli import main

                main()
            assert exc_info.value.code == 0

    def test_verify_exits_0(self) -> None:
        with patch("sys.argv", ["shared.compliance", "verify"]):
            with pytest.raises(SystemExit) as exc_info:
                from shared.compliance.cli import main

                main()
            assert exc_info.value.code == 0

    def test_verify_single_scenario_exits_0(self) -> None:
        argv = ["shared.compliance", "verify", "--scenario", "02_ema_vwap_trend"]
        with patch("sys.argv", argv):
            with pytest.raises(SystemExit) as exc_info:
                from shared.compliance.cli import main

                main()
            assert exc_info.value.code == 0
