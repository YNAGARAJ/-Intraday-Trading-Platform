"""Smoke test for M19 monitor VERIFY harness."""

from __future__ import annotations

from shared.monitor.cli import run_verify


class TestMonitorCliVerify:
    def test_all_scenarios_pass(self) -> None:
        assert run_verify() is True
