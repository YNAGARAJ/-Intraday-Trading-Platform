"""Unit tests for the error/edge-case paths in shared.instruments.sources -- network
failures, malformed responses, and ASXCorporateActionSource's per-symbol behavior.
All offline via monkeypatched `requests` calls; live reachability is covered
separately in tests/integration/test_instruments_live_sources.py.
"""

from datetime import date

import pytest
import requests

from shared.core.exceptions import CorporateActionFetchError, InstrumentFetchError
from shared.instruments.sources import (
    ASXCorporateActionSource,
    ASXInstrumentSource,
    NSECorporateActionSource,
    NSEInstrumentSource,
)


class _FakeResponse:
    def __init__(
        self, text: str = "", json_data: object = None, status_code: int = 200
    ) -> None:
        self.text = text
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self) -> object:
        if self._json_data is None:
            raise ValueError("no JSON")
        return self._json_data


class TestNSEInstrumentSourceErrors:
    def test_network_failure_raises_instrument_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_connection_error(*args: object, **kwargs: object) -> _FakeResponse:
            raise requests.ConnectionError("simulated network failure")

        monkeypatch.setattr(requests, "get", raise_connection_error)

        with pytest.raises(InstrumentFetchError):
            NSEInstrumentSource().fetch()


class TestASXInstrumentSourceErrors:
    def test_network_failure_raises_instrument_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_connection_error(*args: object, **kwargs: object) -> _FakeResponse:
            raise requests.ConnectionError("simulated network failure")

        monkeypatch.setattr(requests, "get", raise_connection_error)

        with pytest.raises(InstrumentFetchError):
            ASXInstrumentSource().fetch()

    def test_unexpected_format_raises_instrument_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **kw: _FakeResponse(text="not the expected CSV at all"),
        )

        with pytest.raises(InstrumentFetchError, match="Company name"):
            ASXInstrumentSource().fetch()


class TestNSECorporateActionSourceErrors:
    def test_network_failure_raises_corporate_action_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FailingSession:
            headers: dict[str, str] = {}

            def get(self, *args: object, **kwargs: object) -> _FakeResponse:
                raise requests.ConnectionError("simulated network failure")

        monkeypatch.setattr(requests, "Session", lambda: FailingSession())

        with pytest.raises(CorporateActionFetchError):
            NSECorporateActionSource().fetch(date(2024, 1, 1), date(2024, 12, 31))

    def test_malformed_json_raises_corporate_action_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class BadJSONSession:
            headers: dict[str, str] = {}

            def get(self, *args: object, **kwargs: object) -> _FakeResponse:
                return _FakeResponse(json_data=None)

        monkeypatch.setattr(requests, "Session", lambda: BadJSONSession())

        with pytest.raises(CorporateActionFetchError):
            NSECorporateActionSource().fetch(date(2024, 1, 1), date(2024, 12, 31))


class TestASXCorporateActionSource:
    def test_no_symbols_returns_empty_and_logs(self) -> None:
        actions = ASXCorporateActionSource().fetch(date(2024, 1, 1), date(2024, 12, 31))

        assert actions == []

    def test_fetch_failure_for_one_symbol_skips_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_connection_error(*args: object, **kwargs: object) -> _FakeResponse:
            raise requests.ConnectionError("simulated network failure")

        monkeypatch.setattr(requests, "get", raise_connection_error)

        actions = ASXCorporateActionSource().fetch(
            date(2024, 1, 1), date(2024, 12, 31), symbols=["BHP"]
        )

        assert actions == []

    def test_no_ex_date_in_response_yields_no_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **kw: _FakeResponse(json_data={"data": {}}),
        )

        actions = ASXCorporateActionSource().fetch(
            date(2024, 1, 1), date(2024, 12, 31), symbols=["BHP"]
        )

        assert actions == []

    def test_ex_date_outside_window_yields_no_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **kw: _FakeResponse(
                json_data={"data": {"dateExDate": "2030-01-01"}}
            ),
        )

        actions = ASXCorporateActionSource().fetch(
            date(2024, 1, 1), date(2024, 12, 31), symbols=["BHP"]
        )

        assert actions == []

    def test_ex_date_in_window_still_yields_no_action_without_amount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Documents the known gap: key-statistics has dates but no dividend amount,
        # so even a fully-successful fetch can't construct a usable CorporateAction.
        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **kw: _FakeResponse(
                json_data={"data": {"dateExDate": "2024-06-01"}}
            ),
        )

        actions = ASXCorporateActionSource().fetch(
            date(2024, 1, 1), date(2024, 12, 31), symbols=["BHP"]
        )

        assert actions == []

    def test_malformed_ex_date_yields_no_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **kw: _FakeResponse(
                json_data={"data": {"dateExDate": "not-a-date"}}
            ),
        )

        actions = ASXCorporateActionSource().fetch(
            date(2024, 1, 1), date(2024, 12, 31), symbols=["BHP"]
        )

        assert actions == []
