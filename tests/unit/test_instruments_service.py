"""Unit tests for shared.instruments.service -- offline via monkeypatched sources
and fake repositories.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

import shared.instruments.service as service_module
from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction, Instrument
from shared.storage.models import OHLCVCandle

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"


class FakeInstrumentRepository:
    def __init__(self) -> None:
        self.written: list[Instrument] = []

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        self.written.extend(instruments)
        return len(instruments)


class FakeCorporateActionRepository:
    def __init__(self, existing: list[CorporateAction] | None = None) -> None:
        self.written: list[CorporateAction] = []
        self._existing = existing or []

    def upsert_many(self, actions: Sequence[CorporateAction]) -> int:
        self.written.extend(actions)
        return len(actions)

    def list_for_symbol(self, symbol: str, exchange: str) -> list[CorporateAction]:
        return [
            a for a in self._existing if a.symbol == symbol and a.exchange == exchange
        ]


class FakeInstrumentSource:
    def __init__(self, instruments: list[Instrument]) -> None:
        self._instruments = instruments

    def fetch(self) -> list[Instrument]:
        return self._instruments


class TestRefreshInstrumentMaster:
    def test_writes_fetched_instruments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        instrument = Instrument(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            name="Reliance",
            isin="X",
            lot_size=1,
            tick_size=0.05,
        )
        monkeypatch.setitem(
            service_module._INSTRUMENT_SOURCES,
            "NSE",
            FakeInstrumentSource([instrument]),
        )
        repo = FakeInstrumentRepository()

        written = service_module.refresh_instrument_master(repo, "NSE")

        assert written == 1
        assert repo.written == [instrument]


class TestRefreshCorporateActions:
    def test_manual_overrides_applied_after_live_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        manual_action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="MANUAL",
            ratio_numerator=3,
            ratio_denominator=1,
        )

        class FakeNSESource:
            def fetch(self, from_date: date, to_date: date) -> list[CorporateAction]:
                return [live_action]

        monkeypatch.setattr(service_module, "NSECorporateActionSource", FakeNSESource)
        monkeypatch.setattr(
            service_module, "load_manual_overrides", lambda: [manual_action]
        )
        repo = FakeCorporateActionRepository()

        written = service_module.refresh_corporate_actions(repo, today=date(2024, 6, 1))

        assert written == 2
        # Order matters: manual must be written *after* live so it wins via upsert.
        assert repo.written == [live_action, manual_action]


class TestGetAdjustedSeries:
    def test_applies_actions_from_repository(self) -> None:
        split = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        repo = FakeCorporateActionRepository(existing=[split])
        candles = [
            OHLCVCandle(
                time=datetime(2024, 1, 3, tzinfo=UTC),
                symbol=SYMBOL,
                exchange=EXCHANGE,
                open=200,
                high=201,
                low=199,
                close=200,
                volume=1000,
            )
        ]

        adjusted = service_module.get_adjusted_series(repo, SYMBOL, EXCHANGE, candles)

        assert adjusted[0].close == 100.0
        assert adjusted[0].volume == 2000

    def test_other_symbols_actions_not_applied(self) -> None:
        other_split = CorporateAction(
            symbol="OTHER",
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        repo = FakeCorporateActionRepository(existing=[other_split])
        candles = [
            OHLCVCandle(
                time=datetime(2024, 1, 3, tzinfo=UTC),
                symbol=SYMBOL,
                exchange=EXCHANGE,
                open=200,
                high=201,
                low=199,
                close=200,
                volume=1000,
            )
        ]

        adjusted = service_module.get_adjusted_series(repo, SYMBOL, EXCHANGE, candles)

        assert adjusted[0].close == 200.0
