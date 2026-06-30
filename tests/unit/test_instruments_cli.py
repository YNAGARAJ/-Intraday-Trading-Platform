"""Unit tests for shared.instruments.cli -- offline via monkeypatched connections,
mirroring tests/unit/test_indicators_cli.py's pattern from M04.
"""

import sys
from datetime import date

import pytest

import shared.instruments.cli as cli_module
from shared.core.exceptions import CorporateActionFetchError, InstrumentFetchError
from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction, Instrument

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeInstrumentRepo:
    def __init__(self, instrument: Instrument | None = None) -> None:
        self._instrument = instrument
        self.get_called_with: tuple[str, str] | None = None

    def get(self, symbol: str, exchange: str) -> Instrument | None:
        self.get_called_with = (symbol, exchange)
        return self._instrument


class FakeActionRepo:
    def __init__(self, actions: list[CorporateAction] | None = None) -> None:
        self._actions = actions or []

    def list_for_symbol(self, symbol: str, exchange: str) -> list[CorporateAction]:
        return self._actions


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    instrument_repo: FakeInstrumentRepo,
    action_repo: FakeActionRepo,
    refresh_instrument_master: object = lambda repo, exchange: 0,
    refresh_corporate_actions: object = lambda repo: 0,
) -> None:
    monkeypatch.setattr(cli_module, "get_connection", lambda settings: conn)
    monkeypatch.setattr(cli_module, "apply_schema", lambda conn: None)
    monkeypatch.setattr(
        cli_module, "InstrumentRepository", lambda conn: instrument_repo
    )
    monkeypatch.setattr(
        cli_module, "CorporateActionRepository", lambda conn: action_repo
    )
    monkeypatch.setattr(
        cli_module, "refresh_instrument_master", refresh_instrument_master
    )
    monkeypatch.setattr(
        cli_module, "refresh_corporate_actions", refresh_corporate_actions
    )


class TestCli:
    def test_found_instrument_with_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        instrument = Instrument(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            name="Reliance Industries",
            isin="INE002A01018",
            lot_size=1,
            tick_size=0.05,
        )
        action = CorporateAction(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            ex_date=date(2024, 1, 5),
            action_type=CorporateActionType.SPLIT,
            source="NSE_LIVE",
            ratio_numerator=2,
            ratio_denominator=1,
        )
        instrument_repo = FakeInstrumentRepo(instrument)
        action_repo = FakeActionRepo([action])
        _patch_common(monkeypatch, conn, instrument_repo, action_repo)
        monkeypatch.setattr(
            sys, "argv", ["cli.py", "--symbol", SYMBOL, "--exchange", EXCHANGE]
        )

        cli_module.main()

        assert instrument_repo.get_called_with == (SYMBOL, EXCHANGE)
        assert conn.closed is True

    def test_instrument_not_found_does_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()
        _patch_common(monkeypatch, conn, FakeInstrumentRepo(None), FakeActionRepo())
        monkeypatch.setattr(sys, "argv", ["cli.py", "--symbol", "NOPE"])

        cli_module.main()

        assert conn.closed is True

    def test_instrument_fetch_error_for_one_exchange_does_not_abort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()

        def failing_refresh(repo: object, exchange: str) -> int:
            if exchange == "ASX":
                raise InstrumentFetchError("simulated ASX failure")
            return 1

        _patch_common(
            monkeypatch,
            conn,
            FakeInstrumentRepo(None),
            FakeActionRepo(),
            refresh_instrument_master=failing_refresh,
        )
        monkeypatch.setattr(sys, "argv", ["cli.py"])

        cli_module.main()  # must not raise

        assert conn.closed is True

    def test_corporate_action_fetch_error_does_not_abort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()

        def failing_refresh(repo: object) -> int:
            raise CorporateActionFetchError("simulated NSE failure")

        _patch_common(
            monkeypatch,
            conn,
            FakeInstrumentRepo(None),
            FakeActionRepo(),
            refresh_corporate_actions=failing_refresh,
        )
        monkeypatch.setattr(sys, "argv", ["cli.py"])

        cli_module.main()  # must not raise

        assert conn.closed is True

    def test_connection_closed_even_if_lookup_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = FakeConn()

        class RaisingInstrumentRepo:
            def get(self, symbol: str, exchange: str) -> Instrument | None:
                raise RuntimeError("simulated DB failure")

        monkeypatch.setattr(cli_module, "get_connection", lambda settings: conn)
        monkeypatch.setattr(cli_module, "apply_schema", lambda conn: None)
        monkeypatch.setattr(
            cli_module, "InstrumentRepository", lambda conn: RaisingInstrumentRepo()
        )
        monkeypatch.setattr(
            cli_module, "CorporateActionRepository", lambda conn: FakeActionRepo()
        )
        monkeypatch.setattr(
            cli_module, "refresh_instrument_master", lambda repo, exchange: 0
        )
        monkeypatch.setattr(cli_module, "refresh_corporate_actions", lambda repo: 0)
        monkeypatch.setattr(sys, "argv", ["cli.py"])

        with pytest.raises(RuntimeError):
            cli_module.main()

        assert conn.closed is True
