"""Repository pattern for the instrument master and corporate actions tables --
all reads/writes against `instruments`/`corporate_actions` go through these two
classes, mirroring `shared.storage.repositories`'s rule for `ticks`/`ohlcv_1m`.
"""

from collections.abc import Sequence
from datetime import date

from psycopg2.extensions import connection as PGConnection  # noqa: N812
from psycopg2.extras import execute_values

from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction, Instrument


class InstrumentRepository:
    """Reads and writes the `instruments` table."""

    def __init__(self, conn: PGConnection) -> None:
        self._conn = conn

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        """Insert or update `instruments` rows. Returns the number of rows written."""
        if not instruments:
            return 0
        rows = [
            (i.symbol, i.exchange, i.name, i.isin, i.lot_size, i.tick_size)
            for i in instruments
        ]
        with self._conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO instruments
                    (symbol, exchange, name, isin, lot_size, tick_size)
                VALUES %s
                ON CONFLICT (symbol, exchange) DO UPDATE SET
                    name = EXCLUDED.name,
                    isin = EXCLUDED.isin,
                    lot_size = EXCLUDED.lot_size,
                    tick_size = EXCLUDED.tick_size,
                    updated_at = now()
                """,
                rows,
            )
        self._conn.commit()
        return len(rows)

    def get(self, symbol: str, exchange: str) -> Instrument | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, exchange, name, isin, lot_size, tick_size "
                "FROM instruments WHERE symbol = %s AND exchange = %s",
                (symbol, exchange),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Instrument(
            symbol=row[0],
            exchange=row[1],
            name=row[2],
            isin=row[3],
            lot_size=row[4],
            tick_size=row[5],
        )

    def count(self, exchange: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM instruments WHERE exchange = %s", (exchange,)
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0


class CorporateActionRepository:
    """Reads and writes the `corporate_actions` table."""

    def __init__(self, conn: PGConnection) -> None:
        self._conn = conn

    def upsert_many(self, actions: Sequence[CorporateAction]) -> int:
        """Insert or update `corporate_actions` rows. A later call with the same
        (symbol, exchange, ex_date, action_type) replaces the earlier row -- this is
        how a MANUAL override takes precedence over a previously live-fetched action;
        see this table's UNIQUE constraint comment in shared/storage/schema.sql.
        """
        if not actions:
            return 0
        rows = [
            (
                a.symbol,
                a.exchange,
                a.ex_date,
                a.action_type.value,
                a.ratio_numerator,
                a.ratio_denominator,
                a.dividend_amount,
                a.new_symbol,
                a.source,
            )
            for a in actions
        ]
        with self._conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO corporate_actions
                    (symbol, exchange, ex_date, action_type, ratio_numerator,
                     ratio_denominator, dividend_amount, new_symbol, source)
                VALUES %s
                ON CONFLICT (symbol, exchange, ex_date, action_type) DO UPDATE SET
                    ratio_numerator = EXCLUDED.ratio_numerator,
                    ratio_denominator = EXCLUDED.ratio_denominator,
                    dividend_amount = EXCLUDED.dividend_amount,
                    new_symbol = EXCLUDED.new_symbol,
                    source = EXCLUDED.source,
                    created_at = now()
                """,
                rows,
            )
        self._conn.commit()
        return len(rows)

    def list_for_symbol(self, symbol: str, exchange: str) -> list[CorporateAction]:
        """All corporate actions for `symbol`, oldest ex_date first."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, exchange, ex_date, action_type, ratio_numerator, "
                "ratio_denominator, dividend_amount, new_symbol, source "
                "FROM corporate_actions "
                "WHERE symbol = %s AND exchange = %s "
                "ORDER BY ex_date",
                (symbol, exchange),
            )
            rows = cur.fetchall()
        return [
            CorporateAction(
                symbol=row[0],
                exchange=row[1],
                ex_date=row[2]
                if isinstance(row[2], date)
                else date.fromisoformat(row[2]),
                action_type=CorporateActionType(row[3]),
                ratio_numerator=row[4],
                ratio_denominator=row[5],
                dividend_amount=row[6],
                new_symbol=row[7],
                source=row[8],
            )
            for row in rows
        ]
