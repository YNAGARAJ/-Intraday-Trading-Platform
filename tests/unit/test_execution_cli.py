"""Unit tests for M14 CLI — verifies the 20-scenario VERIFY output."""

from __future__ import annotations

from shared.execution.cli import run_verify


class TestVerifyScenarios:
    def test_all_20_scenarios_pass(self) -> None:
        assert run_verify() is True
