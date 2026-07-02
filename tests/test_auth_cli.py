"""CLI smoke test for shared.auth (M15)."""

from __future__ import annotations

from shared.auth.cli import run_verify


def test_auth_verify_all_pass() -> None:
    assert run_verify() is True
