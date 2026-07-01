"""Unit tests for M10 market indicator scrapers (market_indicators.py)."""

from __future__ import annotations

import json
import urllib.error
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from shared.sentiment.market_indicators import (
    _fetch_nse_json,
    _fetch_put_call_ratio,
    _get_nse_cookie,
    fetch_fii_dii,
    fetch_india_vix,
)
from shared.sentiment.models import FIIDIIData, VIXData

# ---------------------------------------------------------------------------
# _get_nse_cookie
# ---------------------------------------------------------------------------


class TestGetNseCookie:
    def _make_resp(self, cookie_header: str) -> MagicMock:
        resp = MagicMock()
        resp.headers.get.return_value = cookie_header
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_returns_cookie_before_semicolon(self, mock_open: MagicMock) -> None:
        mock_open.return_value = self._make_resp("nseappid=abc123; Path=/; HttpOnly")
        result = _get_nse_cookie()
        assert result == "nseappid=abc123"

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_empty_set_cookie_header_returns_empty(self, mock_open: MagicMock) -> None:
        mock_open.return_value = self._make_resp("")
        result = _get_nse_cookie()
        assert result == ""

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_network_error_returns_empty(self, mock_open: MagicMock) -> None:
        mock_open.side_effect = urllib.error.URLError("timeout")
        result = _get_nse_cookie()
        assert result == ""

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_no_semicolon_returns_whole_value(self, mock_open: MagicMock) -> None:
        mock_open.return_value = self._make_resp("sessionid=xyz")
        result = _get_nse_cookie()
        assert result == "sessionid=xyz"


# ---------------------------------------------------------------------------
# _fetch_nse_json
# ---------------------------------------------------------------------------


class TestFetchNseJson:
    def _make_resp(self, payload: object) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_returns_parsed_json(self, mock_open: MagicMock) -> None:
        mock_open.return_value = self._make_resp({"key": "value"})
        result = _fetch_nse_json("https://nse.example/api", "cookie=abc")
        assert result == {"key": "value"}

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_sets_cookie_header_when_provided(self, mock_open: MagicMock) -> None:
        mock_open.return_value = self._make_resp({})
        _fetch_nse_json("https://nse.example/api", "session=123")
        req = mock_open.call_args[0][0]
        assert req.get_header("Cookie") == "session=123"

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_network_error_returns_none(self, mock_open: MagicMock) -> None:
        mock_open.side_effect = urllib.error.URLError("connection refused")
        result = _fetch_nse_json("https://nse.example/api", "")
        assert result is None

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_invalid_json_returns_none(self, mock_open: MagicMock) -> None:
        resp = MagicMock()
        resp.read.return_value = b"not json"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp
        result = _fetch_nse_json("https://nse.example/api", "")
        assert result is None

    @patch("shared.sentiment.market_indicators.urllib.request.urlopen")
    def test_empty_cookie_no_cookie_header(self, mock_open: MagicMock) -> None:
        mock_open.return_value = self._make_resp([])
        _fetch_nse_json("https://nse.example/api", "")
        req = mock_open.call_args[0][0]
        assert req.get_header("Cookie") is None

# ---------------------------------------------------------------------------
# fetch_india_vix
# ---------------------------------------------------------------------------


class TestFetchIndiaVix:
    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_returns_vix_data(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = "session=abc"
        mock_json.side_effect = [
            # allIndices response
            {
                "data": [
                    {"indexName": "NIFTY 50", "last": "22000"},
                    {"indexName": "INDIA VIX", "last": "14.55"},
                ]
            },
            # option chain response (for PCR)
            {
                "filtered": {
                    "CE": {"totOI": 1_000_000},
                    "PE": {"totOI": 900_000},
                }
            },
        ]
        result = fetch_india_vix()
        assert result is not None
        assert isinstance(result, VIXData)
        assert result.vix == pytest.approx(14.55)
        assert result.put_call_ratio is not None

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_returns_none_on_fetch_failure(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = None
        assert fetch_india_vix() is None

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_returns_none_when_vix_not_in_response(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = {
            "data": [{"indexName": "NIFTY 50", "last": "22000"}]
        }
        assert fetch_india_vix() is None

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_pcr_none_when_option_chain_fails(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.side_effect = [
            {"data": [{"indexName": "INDIA VIX", "last": "18.0"}]},
            None,  # option chain fails
        ]
        result = fetch_india_vix()
        assert result is not None
        assert result.put_call_ratio is None

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_vix_has_utc_timestamp(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.side_effect = [
            {"data": [{"indexName": "INDIA VIX", "last": "15.0"}]},
            None,
        ]
        result = fetch_india_vix()
        assert result is not None
        assert result.fetched_at.tzinfo is not None


# ---------------------------------------------------------------------------
# _fetch_put_call_ratio
# ---------------------------------------------------------------------------


class TestFetchPutCallRatio:
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_computes_pcr(self, mock_json: MagicMock) -> None:
        mock_json.return_value = {
            "filtered": {
                "CE": {"totOI": 2_000_000},
                "PE": {"totOI": 1_800_000},
            }
        }
        result = _fetch_put_call_ratio("cookie")
        assert result is not None
        assert result == pytest.approx(0.9)

    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_zero_ce_oi_returns_none(self, mock_json: MagicMock) -> None:
        mock_json.return_value = {
            "filtered": {"CE": {"totOI": 0}, "PE": {"totOI": 1000}}
        }
        assert _fetch_put_call_ratio("cookie") is None

    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_none_response_returns_none(self, mock_json: MagicMock) -> None:
        mock_json.return_value = None
        assert _fetch_put_call_ratio("cookie") is None


# ---------------------------------------------------------------------------
# fetch_fii_dii
# ---------------------------------------------------------------------------


class TestFetchFIIDII:
    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_returns_fii_dii_data(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = "session=abc"
        mock_json.return_value = [
            {
                "category": "FII/FPI **",
                "buyValue": "5000.00",
                "sellValue": "3000.00",
                "netValue": "2000.00",
            },
            {
                "category": "DII",
                "buyValue": "2000.00",
                "sellValue": "1500.00",
                "netValue": "500.00",
            },
        ]
        result = fetch_fii_dii()
        assert result is not None
        assert isinstance(result, FIIDIIData)
        assert result.fii_net_crore == pytest.approx(2000.0)
        assert result.dii_net_crore == pytest.approx(500.0)

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_returns_none_on_api_failure(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = None
        assert fetch_fii_dii() is None

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_returns_none_when_fii_missing(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = [
            {"category": "DII", "netValue": "500.00"}
        ]
        assert fetch_fii_dii() is None

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_negative_net_sell(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = [
            {"category": "FII/FPI", "netValue": "-1234.56"},
            {"category": "DII", "netValue": "789.01"},
        ]
        result = fetch_fii_dii()
        assert result is not None
        assert result.fii_net_crore == pytest.approx(-1234.56)

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_date_is_today(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = [
            {"category": "FII", "netValue": "100.0"},
            {"category": "DII", "netValue": "200.0"},
        ]
        result = fetch_fii_dii()
        assert result is not None
        assert result.date == date.today()

    @patch("shared.sentiment.market_indicators._get_nse_cookie")
    @patch("shared.sentiment.market_indicators._fetch_nse_json")
    def test_net_values_with_commas(
        self, mock_json: MagicMock, mock_cookie: MagicMock
    ) -> None:
        mock_cookie.return_value = ""
        mock_json.return_value = [
            {"category": "FII", "netValue": "1,234.56"},
            {"category": "DII", "netValue": "789.01"},
        ]
        result = fetch_fii_dii()
        assert result is not None
        assert result.fii_net_crore == pytest.approx(1234.56)
