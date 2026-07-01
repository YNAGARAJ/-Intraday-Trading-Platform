"""Unit tests for shared.patterns.cli -- offline via monkeypatched connections,
mirroring tests/unit/test_indicators_cli.py's pattern from M04.
"""

import sys
from datetime import datetime, timezone
from typing import Any

import pytest

import shared.patterns.cli as cli_module
from shared.patterns.models import (
    PatternSnapshot,
)
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
SYMBOL = "RELIANCE"
EXCHANGE = "NSE"


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _make_snapshot(symbol: str = SYMBOL, exchange: str = EXCHANGE) -> PatternSnapshot:
    return PatternSnapshot(
        symbol=symbol,
        exchange=exchange,
        timeframe="5m",
        computed_at=_T0,
        candle_time=_T0,
        candlestick_signals=[],
        orb_state=None,
        sr_levels=[],
    )


class FakeOHLCVRepository:
    def __init__(self, candles: list[OHLCVCandle] | None = None) -> None:
        self._candles = candles or []

    def query_candles(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVCandle]:
        return self._candles


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    candles: list[OHLCVCandle] | None = None,
    snapshot: PatternSnapshot | None = None,
) -> None:
    monkeypatch.setattr(cli_module, "get_connection", lambda settings: conn)
    monkeypatch.setattr(cli_module, "apply_schema", lambda conn: None)
    monkeypatch.setattr(
        cli_module,
        "OHLCVRepository",
        lambda conn: FakeOHLCVRepository(candles),
    )
    if snapshot is not None:
        monkeypatch.setattr(cli_module, "compute_snapshot", lambda *a, **kw: snapshot)
        monkeypatch.setattr(
            cli_module,
            "compute_multi_timeframe",
            lambda *a, **kw: _make_mtf_result(),
        )


def _make_mtf_result() -> Any:
    from shared.patterns.models import MultiTimeframePatterns

    return MultiTimeframePatterns(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        computed_at=_T0,
        snapshots={"5m": _make_snapshot()},
        confirmed_bullish_patterns=[],
        confirmed_bearish_patterns=[],
    )


class TestCli:
    def test_no_candles_exits_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = FakeConn()
        _patch_common(monkeypatch, conn, candles=[])
        monkeypatch.setattr(
            sys, "argv", ["cli.py", "--symbol", SYMBOL, "--exchange", EXCHANGE]
        )

        cli_module.main()  # must not raise

        assert conn.closed is True

    def test_with_candles_calls_compute_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        fake_candle = OHLCVCandle(
            time=_T0,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=1000,
        )
        snap = _make_snapshot()
        _patch_common(monkeypatch, conn, candles=[fake_candle], snapshot=snap)
        monkeypatch.setattr(
            sys, "argv", ["cli.py", "--symbol", SYMBOL, "--exchange", EXCHANGE]
        )
        compute_called: list[bool] = []

        def fake_compute(*a: Any, **kw: Any) -> PatternSnapshot:
            compute_called.append(True)
            return snap

        monkeypatch.setattr(cli_module, "compute_snapshot", fake_compute)

        cli_module.main()

        assert conn.closed is True
        assert compute_called

    def test_connection_closed_on_normal_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        _patch_common(monkeypatch, conn, candles=[])
        monkeypatch.setattr(sys, "argv", ["cli.py"])

        cli_module.main()

        assert conn.closed is True

    def test_multi_timeframe_mode_with_timeframes_arg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        _patch_common(monkeypatch, conn, candles=[])
        monkeypatch.setattr(
            sys,
            "argv",
            ["cli.py", "--timeframes", "5m,15m", "--symbol", SYMBOL],
        )

        cli_module.main()  # no crash even when candles are empty

        assert conn.closed is True

    def test_connection_closed_even_on_unexpected_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()

        class RaisingRepo:
            def query_candles(self, *a: Any, **kw: Any) -> list[OHLCVCandle]:
                raise RuntimeError("simulated DB failure")

        monkeypatch.setattr(cli_module, "get_connection", lambda settings: conn)
        monkeypatch.setattr(cli_module, "apply_schema", lambda conn: None)
        monkeypatch.setattr(cli_module, "OHLCVRepository", lambda conn: RaisingRepo())
        monkeypatch.setattr(sys, "argv", ["cli.py"])

        with pytest.raises(RuntimeError):
            cli_module.main()

        assert conn.closed is True
