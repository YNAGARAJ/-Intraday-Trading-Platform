"""Unit tests for shared.storage.backfill -- offline via an injected fetch_history.

Live yfinance behavior is covered separately in
tests/integration/test_yfinance_backfill_live.py.
"""

import sys
from datetime import datetime

import pandas as pd
import pytest

import shared.storage.backfill as backfill_module
from shared.storage.backfill import (
    COARSE_BACKFILL_INTERVAL,
    ONE_MINUTE_INTERVAL,
    ONE_MINUTE_MAX_BACKFILL_DAYS,
    _exchange_for_symbol,
    backfill,
    candles_from_history,
)
from shared.storage.models import OHLCVCandle


def _history_df(
    rows: list[tuple[datetime, float, float, float, float, int]],
) -> pd.DataFrame:
    index = pd.DatetimeIndex([r[0] for r in rows], name="Datetime")
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=index,
    )


class TestExchangeForSymbol:
    def test_ns_suffix_is_nse(self) -> None:
        assert _exchange_for_symbol("RELIANCE.NS") == "NSE"

    def test_bo_suffix_is_nse(self) -> None:
        assert _exchange_for_symbol("RELIANCE.BO") == "NSE"

    def test_ax_suffix_is_asx(self) -> None:
        assert _exchange_for_symbol("BHP.AX") == "ASX"

    def test_unknown_suffix(self) -> None:
        assert _exchange_for_symbol("AAPL") == "UNKNOWN"


class TestCandlesFromHistory:
    def test_converts_rows_to_candles(self) -> None:
        df = _history_df(
            [
                (datetime(2026, 6, 1, 9, 15), 100.0, 105.0, 99.0, 104.0, 1000),
                (datetime(2026, 6, 1, 9, 16), 104.0, 106.0, 103.0, 105.5, 1200),
            ]
        )

        candles = candles_from_history("RELIANCE.NS", "NSE", df)

        assert candles == [
            OHLCVCandle(
                time=datetime(2026, 6, 1, 9, 15),
                symbol="RELIANCE.NS",
                exchange="NSE",
                open=100.0,
                high=105.0,
                low=99.0,
                close=104.0,
                volume=1000,
            ),
            OHLCVCandle(
                time=datetime(2026, 6, 1, 9, 16),
                symbol="RELIANCE.NS",
                exchange="NSE",
                open=104.0,
                high=106.0,
                low=103.0,
                close=105.5,
                volume=1200,
            ),
        ]

    def test_empty_dataframe_yields_no_candles(self) -> None:
        df = _history_df([])

        assert candles_from_history("RELIANCE.NS", "NSE", df) == []


class FakeOHLCVRepository:
    """Stand-in for OHLCVRepository -- records what would have been written."""

    def __init__(self) -> None:
        self.written: list[OHLCVCandle] = []

    def upsert_1m(self, candles: list[OHLCVCandle]) -> int:
        self.written.extend(candles)
        return len(candles)


class TestBackfill:
    def test_short_range_uses_1m_interval(self) -> None:
        captured: dict[str, str] = {}

        def fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
            captured["interval"] = interval
            return _history_df([(datetime(2026, 6, 1, 9, 15), 1, 1, 1, 1, 1)])

        backfill(
            "RELIANCE.NS",
            days=ONE_MINUTE_MAX_BACKFILL_DAYS,
            repository=FakeOHLCVRepository(),
            fetch_history=fetch,
        )

        assert captured["interval"] == ONE_MINUTE_INTERVAL

    def test_long_range_uses_coarse_interval(self) -> None:
        captured: dict[str, str] = {}

        def fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
            captured["interval"] = interval
            return _history_df([(datetime(2026, 6, 1, 9, 15), 1, 1, 1, 1, 1)])

        backfill(
            "RELIANCE.NS",
            days=30,
            repository=FakeOHLCVRepository(),
            fetch_history=fetch,
        )

        assert captured["interval"] == COARSE_BACKFILL_INTERVAL

    def test_writes_candles_to_repository(self) -> None:
        df = _history_df(
            [
                (datetime(2026, 6, 1, 9, 15), 100.0, 105.0, 99.0, 104.0, 1000),
                (datetime(2026, 6, 1, 9, 20), 104.0, 106.0, 103.0, 105.5, 1200),
            ]
        )
        repo = FakeOHLCVRepository()

        written = backfill(
            "RELIANCE.NS",
            days=30,
            repository=repo,
            fetch_history=lambda symbol, period, interval: df,
        )

        assert written == 2
        assert len(repo.written) == 2
        assert all(
            c.symbol == "RELIANCE.NS" and c.exchange == "NSE" for c in repo.written
        )

    def test_exchange_inferred_from_symbol_when_not_given(self) -> None:
        df = _history_df([(datetime(2026, 6, 1, 10, 0), 1, 1, 1, 1, 1)])
        repo = FakeOHLCVRepository()

        backfill(
            "BHP.AX",
            days=5,
            repository=repo,
            fetch_history=lambda symbol, period, interval: df,
        )

        assert repo.written[0].exchange == "ASX"

    def test_explicit_exchange_overrides_inference(self) -> None:
        df = _history_df([(datetime(2026, 6, 1, 10, 0), 1, 1, 1, 1, 1)])
        repo = FakeOHLCVRepository()

        backfill(
            "RELIANCE.NS",
            days=5,
            repository=repo,
            exchange="OVERRIDDEN",
            fetch_history=lambda symbol, period, interval: df,
        )

        assert repo.written[0].exchange == "OVERRIDDEN"


class TestCli:
    def test_main_parses_args_and_invokes_backfill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class FakeConn:
            def close(self) -> None:
                captured["closed"] = True

        monkeypatch.setattr(
            backfill_module, "get_connection", lambda settings: FakeConn()
        )
        monkeypatch.setattr(
            backfill_module,
            "apply_schema",
            lambda conn: captured.update(schema_applied=True),
        )

        def fake_backfill(symbol: str, days: int, repository: object) -> int:
            captured["symbol"] = symbol
            captured["days"] = days
            return 42

        monkeypatch.setattr(backfill_module, "backfill", fake_backfill)
        monkeypatch.setattr(
            sys, "argv", ["backfill.py", "--symbol", "TCS.NS", "--days", "10"]
        )

        backfill_module.main()

        assert captured["symbol"] == "TCS.NS"
        assert captured["days"] == 10
        assert captured["schema_applied"] is True
        assert captured["closed"] is True

    def test_main_closes_connection_even_if_backfill_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class FakeConn:
            def close(self) -> None:
                captured["closed"] = True

        monkeypatch.setattr(
            backfill_module, "get_connection", lambda settings: FakeConn()
        )
        monkeypatch.setattr(backfill_module, "apply_schema", lambda conn: None)

        def failing_backfill(symbol: str, days: int, repository: object) -> int:
            raise ConnectionError("simulated DB failure")

        monkeypatch.setattr(backfill_module, "backfill", failing_backfill)
        monkeypatch.setattr(sys, "argv", ["backfill.py"])

        with pytest.raises(ConnectionError):
            backfill_module.main()

        assert captured["closed"] is True
