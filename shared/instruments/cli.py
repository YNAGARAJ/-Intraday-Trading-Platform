"""Standalone diagnostic CLI for the instrument master and corporate actions.

    python -m shared.instruments --symbol RELIANCE --exchange NSE

Refreshes both exchanges' instrument master and NSE's corporate actions from live
sources plus the manual override table, then looks up and prints the given
symbol/exchange's instrument record and corporate-action history. A live-fetch
failure for one source is logged and skipped rather than aborting the whole run --
the other sources' refreshes (and the lookup against whatever's already in the table)
still proceed, mirroring M02/M03's graceful-degradation pattern.
"""

import argparse
import sys

import psycopg2

from shared.core.config import load_settings
from shared.core.exceptions import CorporateActionFetchError, InstrumentFetchError
from shared.core.logging import configure_logging, get_logger
from shared.core.types import AppId
from shared.instruments.repositories import (
    CorporateActionRepository,
    InstrumentRepository,
)
from shared.instruments.service import (
    refresh_corporate_actions,
    refresh_instrument_master,
)
from shared.storage.connection import apply_schema, get_connection

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Instrument master diagnostic CLI")
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--exchange", default="NSE", choices=["NSE", "ASX"])
    args = parser.parse_args()

    configure_logging("INFO")
    # app_id is arbitrary here -- only settings.timescale_dsn is used.
    settings = load_settings(app_id=AppId.INDIA)
    try:
        conn = get_connection(settings)
    except psycopg2.OperationalError as exc:
        logger.error("db_connection_failed", error=str(exc))
        sys.exit(1)
    try:
        apply_schema(conn)
        instrument_repo = InstrumentRepository(conn)
        action_repo = CorporateActionRepository(conn)

        for exchange in ("NSE", "ASX"):
            try:
                refresh_instrument_master(instrument_repo, exchange)
            except InstrumentFetchError as exc:
                logger.error(
                    "instrument_master_refresh_failed",
                    exchange=exchange,
                    error=str(exc),
                )

        try:
            refresh_corporate_actions(action_repo)
        except CorporateActionFetchError as exc:
            logger.error("corporate_actions_refresh_failed", error=str(exc))

        instrument = instrument_repo.get(args.symbol, args.exchange)
        if instrument is None:
            logger.info(
                "instrument_not_found", symbol=args.symbol, exchange=args.exchange
            )
        else:
            logger.info(
                "instrument_found",
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                name=instrument.name,
                isin=instrument.isin,
                lot_size=instrument.lot_size,
                tick_size=instrument.tick_size,
            )

        actions = action_repo.list_for_symbol(args.symbol, args.exchange)
        logger.info(
            "corporate_action_history", symbol=args.symbol, action_count=len(actions)
        )
        for action in actions:
            logger.info(
                "corporate_action",
                symbol=action.symbol,
                ex_date=action.ex_date.isoformat(),
                action_type=action.action_type.value,
                source=action.source,
                ratio_numerator=action.ratio_numerator,
                ratio_denominator=action.ratio_denominator,
                dividend_amount=action.dividend_amount,
                new_symbol=action.new_symbol,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
