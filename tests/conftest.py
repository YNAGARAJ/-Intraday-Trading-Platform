"""Shared pytest fixtures for unit tests.

Redis-backed integration fixtures live in tests/integration/conftest.py, scoped to
that directory only, so the unit test suite stays runnable on a bare host with no
Docker/Redis available.
"""

from pathlib import Path

import pytest

from shared.core.types import AppId, Exchange


@pytest.fixture
def valid_region_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid config.yaml and return its path."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "app_id: india\n"
        "exchange: NSE\n"
        "broker_name: zerodha_kite\n"
        "timezone: Asia/Kolkata\n"
        'pre_market_local: "08:45"\n'
        'market_open_local: "09:15"\n'
        'market_close_local: "15:30"\n'
        'square_off_local: "15:10"\n'
        'snapshot_window_start_local: "14:45"\n'
    )
    return path


@pytest.fixture
def region_yaml_factory(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Factory for a config.yaml with overrides, for parametrized validation tests."""

    def _make(**overrides: object) -> Path:
        defaults: dict[str, object] = {
            "app_id": AppId.AUSTRALIA.value,
            "exchange": Exchange.ASX.value,
            "broker_name": "interactive_brokers",
            "timezone": "Australia/Sydney",
            "pre_market_local": "09:15",
            "market_open_local": "10:00",
            "market_close_local": "16:00",
            "square_off_local": "15:50",
        }
        defaults.update(overrides)
        path = tmp_path / "config.yaml"
        # Quoted: unquoted "HH:MM" is YAML 1.1 sexagesimal (e.g. "10:00" -> 600).
        lines = [f'{key}: "{value}"' for key, value in defaults.items()]
        path.write_text("\n".join(lines) + "\n")
        return path

    return _make
