"""Fixture per i test della dashboard PROBE (probe-agent simulato)."""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_DASH = os.path.abspath(os.path.join(_HERE, ".."))
if _DASH not in sys.path:
    sys.path.insert(0, _DASH)

from pulse_fe_common.config import ProbeDashboardConfig  # noqa: E402

import app as app_module  # noqa: E402


class _Blank(dict):
    def __getattr__(self, name):  # pragma: no cover - via Jinja getattr
        return self.get(name, _Blank())

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            return [] if key == "items" else _Blank()


class FakeApiClient:
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

    def put(self, path, token=None, json=None):  # pragma: no cover - non usato
        return self._do("PUT", path, json=json)

    def delete(self, path, token=None, json=None):  # pragma: no cover - non usato
        return self._do("DELETE", path, json=json)


@pytest.fixture
def cfg():
    return ProbeDashboardConfig(
        agent_base_url="http://agent/api/v1",
        agent_token="agent-token",
        dash_user="probe",
        dash_password="secret",
        secret_key="test-secret",
        request_timeout=5.0,
        verify_tls=False,
        port=5001,
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
    def _login(username="probe"):
        with client.session_transaction() as s:
            s["probe_user"] = username
    return _login
