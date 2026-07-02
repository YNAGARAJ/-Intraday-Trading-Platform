"""Tests for M17 VERIFY CLI."""

from __future__ import annotations

from shared.reconciliation.cli import run_verify


def test_run_verify_all_scenarios_pass() -> None:
    assert run_verify() is True
