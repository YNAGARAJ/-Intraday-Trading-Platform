"""The M05 VERIFY command, against real TimescaleDB:

    inject a known historical split -> confirm adjusted price series matches
    expected ratio -> confirm M04 indicators computed on adjusted series, not raw.

Uses a synthetic but realistic split (price halves at the ex-date, as a real 2:1
split does) rather than fetching a real one live -- this proves the adjustment
engine's own correctness deterministically, the same way M03/M04's VERIFY tests use
synthetic data to prove the storage/indicator layers independent of any external
feed's availability. The NSE/ASX parsing logic itself is validated separately
against real captured data in tests/unit/test_instruments_sources.py, and live
reachability in tests/integration/test_instruments_live_sources.py.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.core.types import CorporateActionType
from shared.indicators.engine import compute_all
from shared.instruments.models import CorporateAction
from shared.instruments.repositories import CorporateActionRepository
from shared.instruments.service import get_adjusted_series
from shared.storage.models import OHLCVCandle
from shared.storage.repositories import OHLCVRepository

SYMBOL = "TESTSPLIT"
EXCHANGE = "NSE"
EX_DATE = date(2024, 6, 15)


def _candle(time_: datetime, price: float) -> OHLCVCandle:
    return OHLCVCandle(
        time=time_,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        open=price - 0.2,
        high=price + 0.5,
        low=price - 0.5,
        close=price,
        volume=1000,
    )


class TestInstrumentMasterVerify:
    def test_known_split_adjusts_series_and_changes_m04_indicators(
        self, pg_connection: PGConnection
    ) -> None:
        action_repo = CorporateActionRepository(pg_connection)
        split = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=EX_DATE,
            action_type=CorporateActionType.SPLIT,
            source="MANUAL",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        action_repo.upsert_many([split])

        ohlcv_repo = OHLCVRepository(pg_connection)
        pre_split_start = datetime.combine(
            EX_DATE - timedelta(days=1), time(9, 15), tzinfo=UTC
        )
        post_split_start = datetime.combine(EX_DATE, time(9, 15), tzinfo=UTC)
        candles = [
            _candle(pre_split_start + timedelta(minutes=i), 200.0) for i in range(30)
        ] + [_candle(post_split_start + timedelta(minutes=i), 100.0) for i in range(30)]
        ohlcv_repo.upsert_1m(candles)

        raw = ohlcv_repo.query_candles(
            SYMBOL,
            EXCHANGE,
            "1m",
            pre_split_start,
            post_split_start + timedelta(minutes=30),
        )
        assert len(raw) == 60
        assert raw[0].close == pytest.approx(200.0)
        assert raw[-1].close == pytest.approx(100.0)

        # Step 1: inject a known split -> adjusted price series matches expected ratio.
        adjusted = get_adjusted_series(action_repo, SYMBOL, EXCHANGE, raw)
        assert adjusted[0].close == pytest.approx(100.0)  # 200 halved by the 2:1 split
        assert adjusted[29].close == pytest.approx(100.0)  # last pre-split bar
        assert adjusted[-1].close == pytest.approx(100.0)  # post-split: unchanged
        assert raw[0].close == pytest.approx(200.0)  # raw series itself untouched

        # Step 2: M04 indicators computed on adjusted series, not raw, behave
        # correctly -- raw has an artificial 100-point gap exactly at the split
        # boundary that inflates ATR; the adjusted series is smooth across it.
        # Wilder's smoothing means ATR_14's memory of the gap fades over the 30
        # bars between the gap and the end of the series, so the gap is most
        # visible right after it happens, not 5x-still-visible 30 bars later --
        # confirmed via the actual measured values below before picking 1.5x.
        raw_atr_at_gap = compute_all(raw[:32])["ATR"]["ATR_14"]
        adjusted_atr_at_gap = compute_all(adjusted[:32])["ATR"]["ATR_14"]
        assert raw_atr_at_gap is not None
        assert adjusted_atr_at_gap is not None
        assert raw_atr_at_gap > adjusted_atr_at_gap * 1.5, (
            f"expected raw ATR ({raw_atr_at_gap}) just after the gap to be "
            f"sharply inflated vs adjusted ATR ({adjusted_atr_at_gap})"
        )

        raw_atr_full = compute_all(raw)["ATR"]["ATR_14"]
        adjusted_atr_full = compute_all(adjusted)["ATR"]["ATR_14"]
        assert raw_atr_full is not None
        assert adjusted_atr_full is not None
        assert raw_atr_full != adjusted_atr_full
        assert raw_atr_full > adjusted_atr_full
