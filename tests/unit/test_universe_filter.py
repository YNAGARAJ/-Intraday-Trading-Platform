"""Unit tests for M09 run_universe_filter(): RULE 2, compliance, scoring, ranking."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from shared.core.constants import WATCHLIST_MIN_CANDLES, WATCHLIST_TOP_N
from shared.regime.models import MarketRegime
from shared.universe.compliance import ComplianceExclusionList
from shared.universe.filter import run_universe_filter

_NOW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)


def _make_exclusion_list(
    asm: frozenset[str] = frozenset(),
    esm: frozenset[str] = frozenset(),
    ban: frozenset[str] = frozenset(),
    mwpl: frozenset[str] = frozenset(),
) -> ComplianceExclusionList:
    return ComplianceExclusionList(
        asm_symbols=asm,
        esm_symbols=esm,
        ban_symbols=ban,
        mwpl_exceeded_symbols=mwpl,
        fetched_at=_NOW,
    )


def _candles(
    n: int = WATCHLIST_MIN_CANDLES + 10,
    uptrend: bool = True,
) -> dict[str, np.ndarray]:
    if uptrend:
        close = np.linspace(80.0, 120.0, n, dtype=np.float64)
    else:
        close = np.linspace(120.0, 80.0, n, dtype=np.float64)
    return {
        "close": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "volume": np.full(n, 1_000_000.0, dtype=np.float64),
    }


def _instruments(*symbols: str, exchange: str = "NSE") -> list[dict[str, str]]:
    return [{"symbol": s, "exchange": exchange} for s in symbols]


def _no_exclusions() -> ComplianceExclusionList:
    return _make_exclusion_list()


# ---------------------------------------------------------------------------
# RULE 2 — HIGH_VOL_CHAOS returns empty list immediately
# ---------------------------------------------------------------------------


class TestRule2HighVolChaos:
    def test_high_vol_chaos_returns_empty(self) -> None:
        instr = _instruments("RELIANCE", "INFY", "TCS")
        candles = {s: _candles() for s in ("RELIANCE", "INFY", "TCS")}
        result = run_universe_filter(
            instruments=instr,
            candles_by_symbol=candles,
            regime=MarketRegime.HIGH_VOL_CHAOS,
            exclusion_list=_no_exclusions(),
        )
        assert result == []

    def test_high_vol_chaos_ignores_instruments(self) -> None:
        """Even with valid candles and no exclusions, must return empty."""
        result = run_universe_filter(
            instruments=[{"symbol": "X", "exchange": "NSE"}],
            candles_by_symbol={"X": _candles()},
            regime=MarketRegime.HIGH_VOL_CHAOS,
            exclusion_list=_no_exclusions(),
        )
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Compliance filtering
# ---------------------------------------------------------------------------


class TestComplianceFiltering:
    def test_asm_symbol_excluded(self) -> None:
        instr = _instruments("ASM_STOCK", "CLEAN_STOCK")
        candles = {
            "ASM_STOCK": _candles(),
            "CLEAN_STOCK": _candles(),
        }
        excl = _make_exclusion_list(asm=frozenset(["ASM_STOCK"]))
        result = run_universe_filter(instr, candles, MarketRegime.BULL_TREND, excl)
        symbols = [e.symbol for e in result]
        assert "ASM_STOCK" not in symbols
        assert "CLEAN_STOCK" in symbols

    def test_ban_symbol_excluded(self) -> None:
        instr = _instruments("BANNED", "OK")
        candles = {"BANNED": _candles(), "OK": _candles()}
        excl = _make_exclusion_list(ban=frozenset(["BANNED"]))
        result = run_universe_filter(instr, candles, MarketRegime.BULL_TREND, excl)
        assert all(e.symbol != "BANNED" for e in result)

    def test_all_excluded_returns_empty(self) -> None:
        instr = _instruments("A", "B")
        candles = {"A": _candles(), "B": _candles()}
        excl = _make_exclusion_list(asm=frozenset(["A", "B"]))
        result = run_universe_filter(instr, candles, MarketRegime.BULL_TREND, excl)
        assert result == []


# ---------------------------------------------------------------------------
# Missing / insufficient candles
# ---------------------------------------------------------------------------


class TestCandleGating:
    def test_missing_candles_symbol_skipped(self) -> None:
        instr = _instruments("HAS_DATA", "NO_DATA")
        candles = {"HAS_DATA": _candles()}  # NO_DATA absent
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        assert len(result) == 1
        assert result[0].symbol == "HAS_DATA"

    def test_insufficient_candles_skipped(self) -> None:
        instr = _instruments("SHORT", "LONG")
        candles = {
            "SHORT": _candles(n=WATCHLIST_MIN_CANDLES - 1),
            "LONG": _candles(n=WATCHLIST_MIN_CANDLES + 10),
        }
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        symbols = [e.symbol for e in result]
        assert "SHORT" not in symbols
        assert "LONG" in symbols

    def test_no_candles_at_all_returns_empty(self) -> None:
        instr = _instruments("A", "B")
        result = run_universe_filter(
            instr, {}, MarketRegime.BULL_TREND, _no_exclusions()
        )
        assert result == []


# ---------------------------------------------------------------------------
# Ranking and top-N
# ---------------------------------------------------------------------------


class TestRankingAndTopN:
    def test_results_sorted_by_score_descending(self) -> None:
        symbols = [f"SYM{i}" for i in range(5)]
        instr = _instruments(*symbols)
        candles = {s: _candles() for s in symbols}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        scores = [e.composite_score for e in result]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_are_one_based_sequential(self) -> None:
        instr = _instruments("A", "B", "C")
        candles = {s: _candles() for s in ("A", "B", "C")}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        assert [e.rank for e in result] == list(range(1, len(result) + 1))

    def test_top_n_limits_output(self) -> None:
        symbols = [f"SYM{i}" for i in range(10)]
        instr = _instruments(*symbols)
        candles = {s: _candles() for s in symbols}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions(), top_n=3
        )
        assert len(result) <= 3

    def test_default_top_n_applied(self) -> None:
        symbols = [f"SYM{i:03d}" for i in range(30)]
        instr = _instruments(*symbols)
        candles = {s: _candles() for s in symbols}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        assert len(result) <= WATCHLIST_TOP_N


# ---------------------------------------------------------------------------
# Entry fields
# ---------------------------------------------------------------------------


class TestEntryFields:
    def test_entry_has_correct_exchange(self) -> None:
        instr = [{"symbol": "BHP", "exchange": "ASX"}]
        candles = {"BHP": _candles()}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        if result:
            assert result[0].exchange == "ASX"

    def test_entry_regime_matches_input(self) -> None:
        instr = _instruments("X")
        candles = {"X": _candles()}
        result = run_universe_filter(
            instr, candles, MarketRegime.MEAN_REVERTING, _no_exclusions()
        )
        if result:
            assert result[0].regime == MarketRegime.MEAN_REVERTING

    def test_entry_strategy_id_is_string(self) -> None:
        instr = _instruments("X")
        candles = {"X": _candles()}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        if result:
            assert isinstance(result[0].strategy_id, str)
            assert len(result[0].strategy_id) > 0

    def test_entry_scored_at_is_utc(self) -> None:
        instr = _instruments("X")
        candles = {"X": _candles()}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        if result:
            assert result[0].scored_at.tzinfo is not None

    def test_entry_composite_score_in_range(self) -> None:
        instr = _instruments("X", "Y")
        candles = {s: _candles() for s in ("X", "Y")}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        for e in result:
            assert 0.0 <= e.composite_score <= 1.0


# ---------------------------------------------------------------------------
# Regime-specific strategy assignment
# ---------------------------------------------------------------------------


class TestStrategyAssignment:
    def test_mean_reverting_gets_mean_revert_pivot(self) -> None:
        instr = _instruments("X")
        candles = {"X": _candles(uptrend=False)}
        result = run_universe_filter(
            instr, candles, MarketRegime.MEAN_REVERTING, _no_exclusions()
        )
        if result:
            assert result[0].strategy_id == "MEAN_REVERT_PIVOT"

    def test_bull_trend_gets_valid_strategy(self) -> None:
        instr = _instruments("X")
        candles = {"X": _candles(uptrend=True)}
        result = run_universe_filter(
            instr, candles, MarketRegime.BULL_TREND, _no_exclusions()
        )
        if result:
            assert result[0].strategy_id in ("EMA_VWAP_TREND", "MOMENTUM_RSI")
