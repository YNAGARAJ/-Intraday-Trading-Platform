"""Tests for API-key authentication dependencies."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import optional_api_key, require_api_key


def _app_with_require() -> FastAPI:
    from fastapi import Depends

    app = FastAPI()

    @app.get("/protected")
    async def protected(_: None = Depends(require_api_key)) -> dict[str, str]:  # noqa: B008
        return {"ok": "true"}

    return app


def _app_with_optional() -> FastAPI:
    from fastapi import Depends

    app = FastAPI()

    @app.get("/maybe")
    async def maybe(_: None = Depends(optional_api_key)) -> dict[str, str]:  # noqa: B008
        return {"ok": "true"}

    return app


class TestRequireApiKey:
    def test_no_key_configured_returns_403(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = ""
            client = TestClient(_app_with_require(), raise_server_exceptions=False)
            resp = client.get("/protected", headers={"X-API-Key": "anything"})
        assert resp.status_code == 403

    def test_missing_header_returns_401(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = "secret"
            client = TestClient(_app_with_require(), raise_server_exceptions=False)
            resp = client.get("/protected")
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = "correct"
            client = TestClient(_app_with_require(), raise_server_exceptions=False)
            resp = client.get("/protected", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 403

    def test_correct_key_returns_200(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = "mysecret"
            client = TestClient(_app_with_require(), raise_server_exceptions=False)
            resp = client.get("/protected", headers={"X-API-Key": "mysecret"})
        assert resp.status_code == 200


class TestOptionalApiKey:
    def test_no_key_configured_allows_all(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = ""
            client = TestClient(_app_with_optional(), raise_server_exceptions=False)
            resp = client.get("/maybe")
        assert resp.status_code == 200

    def test_key_configured_without_header_returns_401(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = "set"
            client = TestClient(_app_with_optional(), raise_server_exceptions=False)
            resp = client.get("/maybe")
        assert resp.status_code == 401

    def test_key_configured_wrong_header_returns_403(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = "correct"
            client = TestClient(_app_with_optional(), raise_server_exceptions=False)
            resp = client.get("/maybe", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 403

    def test_key_configured_correct_header_passes(self) -> None:
        with patch("api.auth.settings") as m:
            m.api_key = "mykey"
            client = TestClient(_app_with_optional(), raise_server_exceptions=False)
            resp = client.get("/maybe", headers={"X-API-Key": "mykey"})
        assert resp.status_code == 200
