"""CLI smoke test for shared.ingestion (M16)."""

from __future__ import annotations

from shared.ingestion.cli import run_verify


def test_ingestion_verify_all_pass() -> None:
    assert run_verify() is True
