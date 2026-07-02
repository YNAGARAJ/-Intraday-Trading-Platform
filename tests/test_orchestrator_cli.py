"""Smoke test for M18 orchestrator VERIFY harness."""

from __future__ import annotations

from shared.orchestrator.cli import run_verify


class TestOrchestatorCliVerify:
    def test_all_scenarios_pass(self) -> None:
        assert run_verify() is True
