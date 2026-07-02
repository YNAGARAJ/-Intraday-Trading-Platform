"""Unit tests for M12 risk CLI VERIFY scenarios."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.risk.cli import (
    _scenario_circuit_breaker,
    _scenario_correlation,
    _scenario_halted,
    _scenario_normal,
    _scenario_portfolio_heat,
    _scenario_snapshot_window,
    cmd_verify,
)
from shared.risk.models import RiskDecision


class TestScenarios:
    def test_normal_approved(self) -> None:
        d: RiskDecision = _scenario_normal()  # type: ignore[assignment]
        assert d.approved is True
        assert d.position_size is not None

    def test_circuit_breaker_rejected(self) -> None:
        d: RiskDecision = _scenario_circuit_breaker()  # type: ignore[assignment]
        assert d.approved is False
        assert "circuit-breaker" in (d.rejection_reason or "").lower()

    def test_halted_rejected(self) -> None:
        d: RiskDecision = _scenario_halted()  # type: ignore[assignment]
        assert d.approved is False
        assert "halted" in (d.rejection_reason or "").lower()

    def test_portfolio_heat_rejected(self) -> None:
        d: RiskDecision = _scenario_portfolio_heat()  # type: ignore[assignment]
        assert d.approved is False

    def test_snapshot_window_approved(self) -> None:
        d: RiskDecision = _scenario_snapshot_window()  # type: ignore[assignment]
        assert d.approved is True
        assert d.position_size is not None
        assert d.position_size.snapshot_multiplier == 0.5

    def test_snapshot_smaller_than_normal(self) -> None:
        normal: RiskDecision = _scenario_normal()  # type: ignore[assignment]
        snap: RiskDecision = _scenario_snapshot_window()  # type: ignore[assignment]
        assert snap.position_size is not None and normal.position_size is not None
        assert snap.position_size.risk_pct <= normal.position_size.risk_pct * 0.6

    def test_correlation_rejected(self) -> None:
        d: RiskDecision = _scenario_correlation()  # type: ignore[assignment]
        assert d.approved is False


class TestCmdVerify:
    def _make_args(self, scenario: str = "all") -> object:
        import argparse

        return argparse.Namespace(scenario=scenario)

    def test_all_scenarios_return_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_verify(self._make_args("all"))  # type: ignore[arg-type]
        assert rc == 0

    def test_normal_scenario_returns_0(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cmd_verify(self._make_args("normal"))  # type: ignore[arg-type]
        assert rc == 0

    def test_output_contains_approved(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_verify(self._make_args("normal"))  # type: ignore[arg-type]
        out = capsys.readouterr().out
        assert "Approved" in out

    def test_output_contains_verify_pass(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_verify(self._make_args("all"))  # type: ignore[arg-type]
        out = capsys.readouterr().out
        assert "VERIFY PASS" in out

    def test_circuit_breaker_scenario(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cmd_verify(self._make_args("circuit_breaker"))  # type: ignore[arg-type]
        assert rc == 0

    def test_halted_scenario(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_verify(self._make_args("halted"))  # type: ignore[arg-type]
        assert rc == 0


class TestMain:
    def test_no_command_prints_help_exits_0(self) -> None:
        with patch("sys.argv", ["shared.risk"]):
            with pytest.raises(SystemExit) as exc_info:
                from shared.risk.cli import main
                main()
            assert exc_info.value.code == 0

    def test_verify_subcommand_exits_0(self) -> None:
        with patch("sys.argv", ["shared.risk", "verify", "--scenario", "normal"]):
            with pytest.raises(SystemExit) as exc_info:
                from shared.risk.cli import main
                main()
            assert exc_info.value.code == 0

    def test_verify_all_exits_0(self) -> None:
        with patch("sys.argv", ["shared.risk", "verify"]):
            with pytest.raises(SystemExit) as exc_info:
                from shared.risk.cli import main
                main()
            assert exc_info.value.code == 0
