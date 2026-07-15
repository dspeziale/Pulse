"""Test residui: state, config, errori."""

from __future__ import annotations

from pulse_probe import errors
from pulse_probe.config import get_settings
from pulse_probe.server_client import ServerClient
from pulse_probe.config import Settings
from pulse_probe.state import RuntimeState
from pulse_probe.store import InMemoryStore


def test_state_thresholds_and_uptime() -> None:
    state = RuntimeState(
        settings=Settings(opensearch_url=None),
        store=InMemoryStore(),
        server=ServerClient(Settings()),
        systems=[{"system_id": "a", "thresholds": {"response_ms_error": 100}}],
    )
    assert state.system_thresholds("a") == {"response_ms_error": 100}
    assert state.system_thresholds("missing") == {}
    assert state.uptime_seconds() >= 0


def test_get_settings_cached() -> None:
    assert get_settings() is get_settings()


def test_error_helpers() -> None:
    assert errors.unauthorized().status_code == 401
    assert errors.bad_request("x").status_code == 400
    assert errors.service_unavailable("x").status_code == 503
    body = errors.ApiError(404, "NOT_FOUND", "m", {"k": 1}).body()
    assert body["error"]["code"] == "NOT_FOUND" and body["error"]["details"] == {"k": 1}


def test_validation_error_handler(client, auth) -> None:
    # body non valido per /api/v1/query -> 422 formato standard
    r = client.post("/api/v1/query", headers=auth, json={"filters": "not-a-list"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNPROCESSABLE_ENTITY"


def test_method_not_allowed_handler(client) -> None:
    r = client.delete("/api/v1/health")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_not_found_handler(client) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
