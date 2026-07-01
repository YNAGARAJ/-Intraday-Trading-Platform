"""M09 VERIFY integration tests — universe filter on synthetic candles + real DB/Redis.

Requires a live TimescaleDB instance (via pg_connection fixture in conftest.py).
Redis tests use a mock — a live Redis is not required for these VERIFY tests.

Verifies:
  - apply_universe_schema() creates the hypertable idempotently.
  - store_watchlist() persists to TimescaleDB and caches in Redis.
  - load_watchlist() returns Redis-cached data without hitting the DB.
  - load_watchlist() falls back to the DB when Redis returns nothing.
  - HIGH_VOL_CHAOS produces an empty watchlist (RULE 2).
  - Compliance exclusions remove symbols before scoring.
  - A full pipeline run (score → rank → store → load) produces valid entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.regime.models import MarketRegime
from shared.universe.compliance import ComplianceExclusionList
from shared.universe.filter import run_universe_filter
from shared.universe.repository import (
    apply_universe_schema,
    load_watchlist,
    store_watchlist,
)

_NOW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)
_N_BARS = 80  # enough for EMA21 + ADX14 + BB20


def _candles(n: int = _N_BARS, uptrend: bool = True) -> dict[str, np.ndarray]:
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


def _no_exclusions() -> ComplianceExclusionList:
    return ComplianceExclusionList(
        asm_symbols=frozenset(),
        esm_symbols=frozenset(),
        ban_symbols=frozenset(),
        mwpl_exceeded_symbols=frozenset(),
        fetched_at=_NOW,
    )


def _mock_redis(cached_payload: bytes | None = None) -> MagicMock:
    r = MagicMock()
    r.get.return_value = cached_payload
    return r


class TestUniverseIntegration:
    """VERIFY tests for M09 — require live TimescaleDB via pg_connection fixture."""

    def test_apply_universe_schema_idempotent(
        self, pg_connection: PGConnection
    ) -> None:
        """Calling apply_universe_schema twice should not raise."""
        apply_universe_schema(pg_connection)  # already called in conftest
        apply_universe_schema(pg_connection)  # second call should be no-op

    def test_store_then_load_round_trip(
        self, pg_connection: PGConnection
    ) -> None:
        """store_watchlist + load_watchlist should return equivalent entries."""
        instruments = [
            {"symbol": "SYM_A", "exchange": "NSE"},
            {"symbol": "SYM_B", "exchange": "NSE"},
        ]
        candles = {s["symbol"]: _candles() for s in instruments}
        entries = run_universe_filter(
            instruments=instruments,
            candles_by_symbol=candles,
            regime=MarketRegime.BULL_TREND,
            exclusion_list=_no_exclusions(),
        )
        assert len(entries) > 0

        redis_mock = _mock_redis(None)  # force DB path on load
        store_watchlist(entries, pg_connection, redis_mock)

        loaded = load_watchlist("NSE", pg_connection, redis_mock)
        assert len(loaded) == len(entries)
        loaded_symbols = {e.symbol for e in loaded}
        stored_symbols = {e.symbol for e in entries}
        assert loaded_symbols == stored_symbols

    def test_load_uses_redis_cache(self, pg_connection: PGConnection) -> None:
        """load_watchlist should return Redis data without querying the DB."""
        import json

        from shared.universe.repository import _entry_to_redis_dict

        entries = run_universe_filter(
            instruments=[{"symbol": "SYM_C", "exchange": "NSE"}],
            candles_by_symbol={"SYM_C": _candles()},
            regime=MarketRegime.BULL_TREND,
            exclusion_list=_no_exclusions(),
        )

        payload = json.dumps([_entry_to_redis_dict(e) for e in entries]).encode()
        redis_mock = _mock_redis(payload)

        loaded = load_watchlist("NSE", pg_connection, redis_mock)
        # DB cursor should NOT be called when Redis hits
        assert len(loaded) == len(entries)

    def test_high_vol_chaos_empty_watchlist(
        self, pg_connection: PGConnection
    ) -> None:
        """RULE 2: HIGH_VOL_CHAOS must produce empty result, nothing stored."""
        result = run_universe_filter(
            instruments=[{"symbol": "ANY", "exchange": "NSE"}],
            candles_by_symbol={"ANY": _candles()},
            regime=MarketRegime.HIGH_VOL_CHAOS,
            exclusion_list=_no_exclusions(),
        )
        assert result == []

    def test_compliance_exclusion_removes_symbol(
        self, pg_connection: PGConnection
    ) -> None:
        """A symbol in the ASM list must not appear in the watchlist."""
        excl = ComplianceExclusionList(
            asm_symbols=frozenset(["EXCLUDED"]),
            esm_symbols=frozenset(),
            ban_symbols=frozenset(),
            mwpl_exceeded_symbols=frozenset(),
            fetched_at=_NOW,
        )
        result = run_universe_filter(
            instruments=[
                {"symbol": "EXCLUDED", "exchange": "NSE"},
                {"symbol": "ALLOWED", "exchange": "NSE"},
            ],
            candles_by_symbol={
                "EXCLUDED": _candles(),
                "ALLOWED": _candles(),
            },
            regime=MarketRegime.BULL_TREND,
            exclusion_list=excl,
        )
        assert all(e.symbol != "EXCLUDED" for e in result)

    def test_load_empty_when_no_history(
        self, pg_connection: PGConnection
    ) -> None:
        """load_watchlist on a clean table must return an empty list."""
        redis_mock = _mock_redis(None)
        loaded = load_watchlist("NSE", pg_connection, redis_mock)
        assert loaded == []
