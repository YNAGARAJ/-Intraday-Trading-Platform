"""Unit tests for M11 signal CLI (covers replay command and VERIFY scenario)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.signals.cli import _build_mock_context, cmd_replay, main


class TestBuildMockContext:
    def test_returns_signal_context(self) -> None:
        from shared.signals.models import SignalContext

        ctx = _build_mock_context("RELIANCE.NS", "NSE", "LONG", chaos=False)
        assert isinstance(ctx, SignalContext)

    def test_chaos_context_has_chaos_regime(self) -> None:
        from shared.regime.models import MarketRegime

        ctx = _build_mock_context("RELIANCE.NS", "NSE", "LONG", chaos=True)
        assert ctx.regime.regime == MarketRegime.HIGH_VOL_CHAOS  # type: ignore[attr-defined]

    def test_long_context_bull_trend(self) -> None:
        from shared.regime.models import MarketRegime

        ctx = _build_mock_context("RELIANCE.NS", "NSE", "LONG", chaos=False)
        assert ctx.regime.regime == MarketRegime.BULL_TREND  # type: ignore[attr-defined]

    def test_short_context_bear_trend(self) -> None:
        from shared.regime.models import MarketRegime

        ctx = _build_mock_context("RELIANCE.NS", "NSE", "SHORT", chaos=False)
        assert ctx.regime.regime == MarketRegime.BEAR_TREND  # type: ignore[attr-defined]

    def test_symbol_and_exchange_stored(self) -> None:
        ctx = _build_mock_context("RELIANCE.NS", "ASX", "LONG", chaos=False)
        assert ctx.symbol == "RELIANCE.NS"
        assert ctx.exchange == "ASX"


class TestCmdReplay:
    def _make_args(
        self,
        symbol: str = "RELIANCE.NS",
        exchange: str = "NSE",
        direction: str | None = None,
        chaos_only: bool = False,
    ) -> object:
        import argparse

        ns = argparse.Namespace(
            symbol=symbol,
            exchange=exchange,
            direction=direction,
            chaos_only=chaos_only,
        )
        return ns

    def test_replay_long_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = self._make_args(direction="LONG")
        rc = cmd_replay(args)  # type: ignore[arg-type]
        assert rc == 0

    def test_replay_short_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = self._make_args(direction="SHORT")
        rc = cmd_replay(args)  # type: ignore[arg-type]
        assert rc == 0

    def test_replay_both_directions(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = self._make_args(direction=None)
        rc = cmd_replay(args)  # type: ignore[arg-type]
        assert rc == 0

    def test_chaos_only_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = self._make_args(chaos_only=True)
        rc = cmd_replay(args)  # type: ignore[arg-type]
        assert rc == 0

    def test_chaos_only_prints_pass(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = self._make_args(chaos_only=True)
        cmd_replay(args)  # type: ignore[arg-type]
        out = capsys.readouterr().out
        assert "PASS" in out

    def test_replay_output_contains_generated(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = self._make_args(direction="LONG")
        cmd_replay(args)  # type: ignore[arg-type]
        out = capsys.readouterr().out
        assert "Generated" in out


class TestMain:
    def test_main_no_args_exits_0(self) -> None:
        with patch("sys.argv", ["shared.signals"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_replay_runs(self) -> None:
        with patch(
            "sys.argv", ["shared.signals", "replay", "RELIANCE.NS", "--exchange", "NSE"]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_chaos_only(self) -> None:
        with patch(
            "sys.argv",
            ["shared.signals", "replay", "RELIANCE.NS", "--chaos-only"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
