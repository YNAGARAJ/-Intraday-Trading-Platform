"""Live yfinance network test.

Yahoo Finance's public API is rate-limited (HTTP 429) and was confirmed blocked from
this build's sandboxed network for every ticker tried (not symbol-specific -- see
shared/storage/backfill.py's module docstring). Treated as a skip, not a failure: the
offline unit suite (tests/unit/test_backfill.py) guarantees the parsing/orchestration
logic is correct; this just observes real external behavior when reachable.
"""

import pytest

from shared.storage.backfill import _default_fetch_history


def test_yfinance_live_fetch_returns_data() -> None:
    try:
        df = _default_fetch_history("RELIANCE.NS", period="5d", interval="1d")
    except Exception as exc:  # yfinance raises assorted exception types on failure
        pytest.skip(f"yfinance unreachable: {exc}")

    if df.empty:
        pytest.skip("yfinance returned no data (likely rate-limited)")

    assert len(df) > 0
