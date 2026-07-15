"""Fixture di test della Probe: app con storage in-memory, senza rete/poller."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from pulse_probe.config import Settings
from pulse_probe.main import create_app
from pulse_probe.state import RuntimeState

TOKEN = "test-server-token"


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        server_query_token=TOKEN,
        opensearch_url=None,  # forza storage in-memory
        poller_enabled=False,  # nessun loop di polling nei test
        probe_id="probe-test",
        server_base_url="http://server.invalid:9443",
    )


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def state(client: TestClient) -> RuntimeState:
    return client.app.state.runtime  # type: ignore[attr-defined,no-any-return]


@pytest.fixture()
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
