"""Fixture per i test della dashboard SERVER.

Il backend REST è simulato da FakeApiClient (nessuna dipendenza da un backend
reale, requisito di test). I template vengono renderizzati davvero: le risposte
mancanti tornano un dict "vuoto ma navigabile" così che nessuna pagina vada in
errore per dati assenti.
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_DASH = os.path.abspath(os.path.join(_HERE, ".."))
if _DASH not in sys.path:
    sys.path.insert(0, _DASH)

from pulse_fe_common.config import ServerDashboardConfig  # noqa: E402
from pulse_fe_common.http_client import (ApiAuthError, ApiError,  # noqa: E402
                                         ApiUnavailableError)

import app as app_module  # noqa: E402


class _Blank(dict):
    """Dict navigabile: attributi/chiavi mancanti non sollevano eccezioni."""

    def __getattr__(self, name):  # pragma: no cover - via Jinja getattr
        return self.get(name, _Blank())

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            return [] if key == "items" else _Blank()


class FakeApiClient:
    """Sostituto di ApiClient: risposte pre-registrate per (metodo, path)."""

    def __init__(self):
        self.responses: dict = {}
        self.calls: list = []
        self.sent: dict = {}
        self.params: dict = {}

    def set(self, method: str, path: str, value):
        self.responses[(method.upper(), path)] = value
        return self

    def _do(self, method, path, json=None, params=None):
        self.calls.append((method, path))
        if json is not None:
            self.sent[(method, path)] = json
        if params is not None:
            self.params[(method, path)] = params
        val = self.responses.get((method, path), _Blank())
        if isinstance(val, Exception):
            raise val
        return val

    def get(self, path, token=None, params=None):
        return self._do("GET", path, params=params)

    def post(self, path, token=None, json=None):
        return self._do("POST", path, json=json)

    def put(self, path, token=None, json=None):
        return self._do("PUT", path, json=json)

    def delete(self, path, token=None, json=None):
        return self._do("DELETE", path, json=json)


@pytest.fixture
def cfg():
    return ServerDashboardConfig(
        api_base_url="http://backend/api/v1",
        secret_key="test-secret",
        request_timeout=5.0,
        verify_tls=False,
        port=5000,
    )


@pytest.fixture
def fake():
    return FakeApiClient()


@pytest.fixture
def app(cfg, fake):
    application = app_module.create_app(cfg)
    application.config["TESTING"] = True
    application.config["API_CLIENT"] = fake
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    def _login(permissions=None, username="admin"):
        with client.session_transaction() as s:
            s["access_token"] = "test-access"
            s["refresh_token"] = "test-refresh"
            s["user"] = {"username": username, "permissions": permissions or []}
    return _login


# Riesporta le eccezioni per i test.
__all__ = ["ApiAuthError", "ApiError", "ApiUnavailableError"]
