"""Integration tests for InstrumentRepository and CorporateActionRepository against a
real TimescaleDB instance.
"""

from datetime import date

from psycopg2.extensions import connection as PGConnection  # noqa: N812

from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction, Instrument
from shared.instruments.repositories import (
    CorporateActionRepository,
    InstrumentRepository,
)

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"


class TestInstrumentRepository:
    def test_upsert_then_get_round_trips(self, pg_connection: PGConnection) -> None:
        repo = InstrumentRepository(pg_connection)
        instrument = Instrument(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            name="Reliance Industries Limited",
            isin="INE002A01018",
            lot_size=1,
            tick_size=0.05,
        )

        written = repo.upsert_many([instrument])

        assert written == 1
        assert repo.get(SYMBOL, EXCHANGE) == instrument

    def test_upsert_again_overwrites_not_duplicates(
        self, pg_connection: PGConnection
    ) -> None:
        repo = InstrumentRepository(pg_connection)
        original = Instrument(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            name="Old Name",
            isin=None,
            lot_size=1,
            tick_size=0.05,
        )
        updated = Instrument(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            name="New Name",
            isin=None,
            lot_size=1,
            tick_size=0.05,
        )
        repo.upsert_many([original])

        repo.upsert_many([updated])

        assert repo.get(SYMBOL, EXCHANGE) == updated
        assert repo.count(EXCHANGE) == 1

    def test_get_missing_returns_none(self, pg_connection: PGConnection) -> None:
        repo = InstrumentRepository(pg_connection)

        assert repo.get("NOPE", "NSE") is None

    def test_count_scoped_to_exchange(self, pg_connection: PGConnection) -> None:
        repo = InstrumentRepository(pg_connection)
        repo.upsert_many(
            [
                Instrument(
                    symbol="A",
                    exchange="NSE",
                    name="A",
                    isin=None,
                    lot_size=1,
                    tick_size=0.05,
                ),
                Instrument(
                    symbol="B",
                    exchange="NSE",
                    name="B",
                    isin=None,
                    lot_size=1,
                    tick_size=0.05,
                ),
                Instrument(
                    symbol="C",
                    exchange="ASX",
                    name="C",
                    isin=None,
                    lot_size=None,
                    tick_size=None,
                ),
            ]
        )

        assert repo.count("NSE") == 2
        assert repo.count("ASX") == 1


class TestCorporateActionRepository:
    def test_upsert_then_list_round_trips(self, pg_connection: PGConnection) -> None:
        repo = CorporateActionRepository(pg_connection)
        action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=10,
            ratio_denominator=5,
        )

        written = repo.upsert_many([action])

        assert written == 1
        assert repo.list_for_symbol(SYMBOL, EXCHANGE) == [action]

    def test_manual_override_replaces_live_row_same_key(
        self, pg_connection: PGConnection
    ) -> None:
        repo = CorporateActionRepository(pg_connection)
        live = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        manual = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="MANUAL",
            ratio_numerator=3,
            ratio_denominator=1,
        )
        repo.upsert_many([live])

        repo.upsert_many([manual])

        actions = repo.list_for_symbol(SYMBOL, EXCHANGE)
        assert len(actions) == 1
        assert actions[0].source == "MANUAL"
        assert actions[0].ratio_numerator == 3

    def test_list_ordered_by_ex_date(self, pg_connection: PGConnection) -> None:
        repo = CorporateActionRepository(pg_connection)
        later = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 6, 1),
            action_type=CorporateActionType.BONUS,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        earlier = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 1),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        repo.upsert_many([later, earlier])

        actions = repo.list_for_symbol(SYMBOL, EXCHANGE)

        assert [a.ex_date for a in actions] == [date(2024, 1, 1), date(2024, 6, 1)]

    def test_list_for_symbol_with_no_actions_returns_empty(
        self, pg_connection: PGConnection
    ) -> None:
        repo = CorporateActionRepository(pg_connection)

        assert repo.list_for_symbol("NOPE", "NSE") == []
