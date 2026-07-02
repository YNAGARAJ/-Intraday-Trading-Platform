"""Smoke test for M20 alerts VERIFY harness."""

from __future__ import annotations

from shared.alerts.cli import run_verify


class TestAlertsCliVerify:
    def test_all_scenarios_pass(self) -> None:
        assert run_verify() is True
