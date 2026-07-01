"""Unit tests for shared.backtesting.cli — offline via monkeypatched DB."""

import sys
from datetime import date, datetime, timezone
from typing import Any

import pytest

import shared.backtesting.cli as cli_module
from shared.backtesting.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    MarkoutPoint,
)
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
_SYMBOL = "RELIANCE"
_EXCHANGE = "NSE"


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _make_candle(m: int) -> OHLCVCandle:
    return OHLCVCandle(
        time=_T0,
        symbol=_SYMBOL,
        exchange=_EXCHANGE,
        open=2500.0,
        high=2510.0,
        low=2490.0,
        close=2505.0 + m,
        volume=10_000,
    )


def _make_result() -> BacktestResult:
    m = BacktestMetrics(
        sharpe_ratio=2.0,
        sortino_ratio=2.5,
        max_drawdown_pct=2.0,
        win_rate_pct=60.0,
        expectancy_per_trade=0.8,
        profit_factor=2.0,
        calmar_ratio=3.0,
        avg_slippage_bps=9.0,
        total_trades=5,
        trading_days=22,
        total_return_pct=12.0,
        annualized_return_pct=15.0,
    )
    return BacktestResult(
        run_id="deadbeef",
        config=BacktestConfig(
            strategy_id="EMA9X21",
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
        ),
        trades=[],
        metrics=m,
        markout_curves=[MarkoutPoint("T+1m", 0.1, 0.08, 0.6, 5)],
        equity_curve=[(_T0, 100_000.0)],
        passed_promotion_gate=True,
        promotion_failures=[],
        report_html_path=None,
        report_csv_path=None,
        completed_at=_T0,
    )


class FakeRepo:
    def __init__(self, candles: list[OHLCVCandle]) -> None:
        self._candles = candles

    def query_candles(self, *a: Any, **kw: Any) -> list[OHLCVCandle]:
        return self._candles


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    candles: list[OHLCVCandle],
) -> None:
    monkeypatch.setattr(cli_module, "load_settings", lambda **_: None)
    monkeypatch.setattr(cli_module, "get_connection", lambda _: conn)
    monkeypatch.setattr(cli_module, "apply_schema", lambda _: None)
    monkeypatch.setattr(cli_module, "apply_backtest_schema", lambda _: None)
    monkeypatch.setattr(cli_module, "OHLCVRepository", lambda _: FakeRepo(candles))


class TestCliNoCandles:
    def test_exits_cleanly_when_no_candles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        _patch(monkeypatch, conn, candles=[])
        monkeypatch.setattr(sys, "argv", ["cli"])
        cli_module.main()  # must not raise
        assert conn.closed

    def test_connection_closed_on_no_candles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        _patch(monkeypatch, conn, candles=[])
        monkeypatch.setattr(sys, "argv", ["cli"])
        cli_module.main()
        assert conn.closed


class TestCliWithCandles:
    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        candles: list[OHLCVCandle],
        extra_argv: list[str] | None = None,
    ) -> FakeConn:
        conn = FakeConn()
        result = _make_result()
        _patch(monkeypatch, conn, candles=candles)
        monkeypatch.setattr(cli_module, "run_backtest", lambda *a, **kw: result)
        monkeypatch.setattr(cli_module, "generate_reports", lambda r, _: r)
        monkeypatch.setattr(cli_module, "save_result", lambda *a, **kw: None)
        base_argv = ["cli", "--symbol", _SYMBOL, "--exchange", _EXCHANGE]
        argv = base_argv + (extra_argv or [])
        monkeypatch.setattr(sys, "argv", argv)
        cli_module.main()
        return conn

    def test_connection_closed_after_successful_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candles = [_make_candle(i) for i in range(5)]
        conn = self._run(monkeypatch, candles)
        assert conn.closed

    def test_no_db_flag_skips_save(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_called: list[bool] = []
        candles = [_make_candle(i) for i in range(5)]
        conn = FakeConn()
        result = _make_result()
        _patch(monkeypatch, conn, candles=candles)
        monkeypatch.setattr(cli_module, "run_backtest", lambda *a, **kw: result)
        monkeypatch.setattr(cli_module, "generate_reports", lambda r, _: r)
        monkeypatch.setattr(
            cli_module,
            "save_result",
            lambda *a, **kw: save_called.append(True),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["cli", "--symbol", _SYMBOL, "--no-db"],
        )
        cli_module.main()
        assert save_called == []

    def test_connection_closed_on_unexpected_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()

        class BrokenRepo:
            def query_candles(self, *a: Any, **kw: Any) -> list[OHLCVCandle]:
                raise RuntimeError("DB exploded")

        monkeypatch.setattr(cli_module, "load_settings", lambda **_: None)
        monkeypatch.setattr(cli_module, "get_connection", lambda _: conn)
        monkeypatch.setattr(cli_module, "apply_schema", lambda _: None)
        monkeypatch.setattr(cli_module, "apply_backtest_schema", lambda _: None)
        monkeypatch.setattr(cli_module, "OHLCVRepository", lambda _: BrokenRepo())
        monkeypatch.setattr(sys, "argv", ["cli"])
        with pytest.raises(RuntimeError):
            cli_module.main()
        assert conn.closed
