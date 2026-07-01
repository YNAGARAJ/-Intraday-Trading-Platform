"""Unit tests for M09 repository: serialisation round-trip, Redis cache logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from shared.regime.models import MarketRegime
from shared.universe.models import AlphaComponents, WatchlistEntry
from shared.universe.repository import (
    _entry_to_redis_dict,
    _redis_dict_to_entry,
    _redis_key,
    load_watchlist,
    store_watchlist,
)

_NOW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)


def _make_entry(
    symbol: str = "RELIANCE",
    rank: int = 1,
    composite_score: float = 0.75,
    strategy_id: str = "EMA_VWAP_TREND",
    regime: MarketRegime = MarketRegime.BULL_TREND,
) -> WatchlistEntry:
    return WatchlistEntry(
        symbol=symbol,
        exchange="NSE",
        rank=rank,
        composite_score=composite_score,
        components=AlphaComponents(
            trend_score=0.8,
            vol_score=0.6,
            liq_score=0.5,
            sent_score=0.0,
        ),
        regime=regime,
        strategy_id=strategy_id,
        scored_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Redis key
# ---------------------------------------------------------------------------


class TestRedisKey:
    def test_key_format(self) -> None:
        assert _redis_key("NSE") == "universe:watchlist:NSE"

    def test_key_uppercases_exchange(self) -> None:
        assert _redis_key("nse") == "universe:watchlist:NSE"
        assert _redis_key("asx") == "universe:watchlist:ASX"


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisationRoundTrip:
    def test_entry_to_redis_dict_keys(self) -> None:
        e = _make_entry()
        d = _entry_to_redis_dict(e)
        for key in (
            "symbol",
            "exchange",
            "rank",
            "composite_score",
            "trend_score",
            "vol_score",
            "liq_score",
            "sent_score",
            "regime",
            "strategy_id",
            "scored_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_round_trip_preserves_all_fields(self) -> None:
        e = _make_entry()
        d = _entry_to_redis_dict(e)
        recovered = _redis_dict_to_entry(d)
        assert recovered.symbol == e.symbol
        assert recovered.exchange == e.exchange
        assert recovered.rank == e.rank
        assert abs(recovered.composite_score - e.composite_score) < 1e-9
        assert abs(recovered.components.trend_score - e.components.trend_score) < 1e-9
        assert recovered.regime == e.regime
        assert recovered.strategy_id == e.strategy_id
        assert recovered.scored_at == e.scored_at

    def test_scored_at_is_utc_after_round_trip(self) -> None:
        e = _make_entry()
        d = _entry_to_redis_dict(e)
        recovered = _redis_dict_to_entry(d)
        assert recovered.scored_at.tzinfo is not None

    def test_json_serialisable(self) -> None:
        e = _make_entry()
        d = _entry_to_redis_dict(e)
        payload = json.dumps(d)
        assert isinstance(payload, str)

    def test_regime_preserved_as_enum(self) -> None:
        for regime in (
            MarketRegime.BULL_TREND,
            MarketRegime.BEAR_TREND,
            MarketRegime.MEAN_REVERTING,
        ):
            e = _make_entry(regime=regime)
            d = _entry_to_redis_dict(e)
            recovered = _redis_dict_to_entry(d)
            assert recovered.regime == regime


# ---------------------------------------------------------------------------
# store_watchlist
# ---------------------------------------------------------------------------


class TestStoreWatchlist:
    def test_empty_entries_no_db_call(self) -> None:
        mock_conn = MagicMock()
        mock_redis = MagicMock()
        store_watchlist([], mock_conn, mock_redis)
        mock_conn.cursor.assert_not_called()
        mock_redis.set.assert_not_called()

    @patch("shared.universe.repository.psycopg2.extras.execute_batch")
    def test_redis_set_called_with_ttl(self, _mock_batch: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_redis = MagicMock()
        entries = [_make_entry()]
        store_watchlist(entries, mock_conn, mock_redis)
        mock_redis.set.assert_called_once()
        _, kwargs = mock_redis.set.call_args
        assert "ex" in kwargs

    @patch("shared.universe.repository.psycopg2.extras.execute_batch")
    def test_redis_key_matches_exchange(self, _mock_batch: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_redis = MagicMock()
        entries = [_make_entry()]
        store_watchlist(entries, mock_conn, mock_redis)
        args, _ = mock_redis.set.call_args
        assert args[0] == "universe:watchlist:NSE"

    @patch("shared.universe.repository.psycopg2.extras.execute_batch")
    def test_db_commit_called(self, _mock_batch: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_redis = MagicMock()
        entries = [_make_entry()]
        store_watchlist(entries, mock_conn, mock_redis)
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# load_watchlist — Redis hit
# ---------------------------------------------------------------------------


class TestLoadWatchlistRedisHit:
    def _make_redis_payload(self, entries: list[WatchlistEntry]) -> bytes:
        return json.dumps(
            [_entry_to_redis_dict(e) for e in entries]
        ).encode()

    def test_returns_entries_from_redis(self) -> None:
        entries = [_make_entry("RELIANCE", rank=1), _make_entry("INFY", rank=2)]
        mock_conn = MagicMock()
        mock_redis = MagicMock()
        mock_redis.get.return_value = self._make_redis_payload(entries)

        result = load_watchlist("NSE", mock_conn, mock_redis)
        assert len(result) == 2
        assert result[0].symbol == "RELIANCE"

    def test_redis_hit_skips_db(self) -> None:
        mock_conn = MagicMock()
        mock_redis = MagicMock()
        mock_redis.get.return_value = self._make_redis_payload([_make_entry()])

        load_watchlist("NSE", mock_conn, mock_redis)
        mock_conn.cursor.assert_not_called()

    def test_bad_redis_payload_falls_through_to_db(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"not-json-at-all"

        result = load_watchlist("NSE", mock_conn, mock_redis)
        mock_conn.cursor.assert_called()
        assert result == []


# ---------------------------------------------------------------------------
# load_watchlist — Redis miss, DB fallback
# ---------------------------------------------------------------------------


class TestLoadWatchlistDBFallback:
    def _make_db_row(
        self,
        symbol: str = "TCS",
        rank: int = 1,
    ) -> dict[str, object]:
        return {
            "symbol": symbol,
            "exchange": "NSE",
            "rank": rank,
            "composite_score": 0.65,
            "trend_score": 0.7,
            "vol_score": 0.5,
            "liq_score": 0.4,
            "sent_score": 0.0,
            "regime": "BULL_TREND",
            "strategy_id": "EMA_VWAP_TREND",
            "scored_at": _NOW,
        }

    def test_returns_entries_from_db(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [self._make_db_row()]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        result = load_watchlist("NSE", mock_conn, mock_redis)
        assert len(result) == 1
        assert result[0].symbol == "TCS"
        assert result[0].regime == MarketRegime.BULL_TREND

    def test_empty_db_returns_empty_list(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        result = load_watchlist("NSE", mock_conn, mock_redis)
        assert result == []
