"""Exercise apps/india/main.py and apps/australia/main.py end to end.

Patches time.sleep to raise KeyboardInterrupt after the first heartbeat so the
otherwise-infinite loop exits immediately and main() returns normally, the same way it
would on a real shutdown signal.
"""

import time

import pytest

import apps.australia.main as australia_main
import apps.india.main as india_main


def _interrupt_after_one_beat(_seconds: float) -> None:
    raise KeyboardInterrupt


def test_india_main_boots_and_shuts_down_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "sleep", _interrupt_after_one_beat)
    india_main.main()  # must not raise


def test_australia_main_boots_and_shuts_down_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "sleep", _interrupt_after_one_beat)
    australia_main.main()  # must not raise


def test_india_main_logs_live_warning_when_live_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", "true")
    monkeypatch.setattr(time, "sleep", _interrupt_after_one_beat)
    india_main.main()  # must not raise; exercises the is_live_trading_enabled branch
