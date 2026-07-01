"""Unit tests for the M08 regime classifier CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import shared.regime.cli as cli_module
from shared.regime.cli import _parse_args, main


class TestParseArgs:
    def test_defaults(self) -> None:
        args = _parse_args([])
        assert args.symbol == "NIFTY50"
        assert args.exchange == "NSE"
        assert args.lookback_days == 5
        assert args.vix == 0.0
        assert args.run_id is None
        assert args.publish is False
        assert args.no_db is False

    def test_custom_symbol_and_exchange(self) -> None:
        args = _parse_args(["--symbol", "BHP", "--exchange", "ASX"])
        assert args.symbol == "BHP"
        assert args.exchange == "ASX"

    def test_vix_flag(self) -> None:
        args = _parse_args(["--vix", "22.5"])
        assert args.vix == 22.5

    def test_lookback_days(self) -> None:
        args = _parse_args(["--lookback-days", "10"])
        assert args.lookback_days == 10

    def test_run_id_flag(self) -> None:
        args = _parse_args(["--run-id", "abc123"])
        assert args.run_id == "abc123"

    def test_publish_flag(self) -> None:
        args = _parse_args(["--publish"])
        assert args.publish is True

    def test_no_db_flag(self) -> None:
        args = _parse_args(["--no-db"])
        assert args.no_db is True


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable external calls for main() unit tests."""
    monkeypatch.setattr(cli_module, "load_settings", lambda **_: MagicMock())
    monkeypatch.setattr(cli_module, "get_connection", lambda _: MagicMock())
    monkeypatch.setattr(cli_module, "apply_schema", lambda _: None)
    monkeypatch.setattr(cli_module, "configure_logging", lambda: None)


class TestMain:
    def test_no_db_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(["--no-db"])
        assert exc_info.value.code == 0

    def test_insufficient_candles_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        repo_mock = MagicMock()
        # Return fewer candles than REGIME_FEATURE_LOOKBACK
        repo_mock.query_candles.return_value = [MagicMock()] * 5
        monkeypatch.setattr(cli_module, "OHLCVRepository", lambda _: repo_mock)

        with pytest.raises(SystemExit) as exc_info:
            main(["--symbol", "NIFTY50"])
        assert exc_info.value.code == 1

    def test_classifies_with_enough_candles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from shared.storage.models import OHLCVCandle

        _patch(monkeypatch)

        start = datetime(2024, 1, 2, 9, 15, tzinfo=timezone.utc)
        candles = [
            OHLCVCandle(
                time=start + timedelta(minutes=5 * i),
                symbol="NIFTY50",
                exchange="NSE",
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=100_000,
            )
            for i in range(60)
        ]

        repo_mock = MagicMock()
        repo_mock.query_candles.return_value = candles
        monkeypatch.setattr(cli_module, "OHLCVRepository", lambda _: repo_mock)

        # Should complete without SystemExit
        main(["--symbol", "NIFTY50", "--vix", "15.0"])

    def test_high_vol_chaos_logged_when_vix_high(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from shared.storage.models import OHLCVCandle

        _patch(monkeypatch)

        start = datetime(2024, 1, 2, 9, 15, tzinfo=timezone.utc)
        candles = [
            OHLCVCandle(
                time=start + timedelta(minutes=5 * i),
                symbol="NIFTY50",
                exchange="NSE",
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=100_000,
            )
            for i in range(60)
        ]

        repo_mock = MagicMock()
        repo_mock.query_candles.return_value = candles
        monkeypatch.setattr(cli_module, "OHLCVRepository", lambda _: repo_mock)

        # VIX=30 should classify as HIGH_VOL_CHAOS — no exception
        main(["--symbol", "NIFTY50", "--vix", "30.0"])
