"""Test degli endpoint FastAPI della Probe e del bootstrap/sync_config."""

from __future__ import annotations

import httpx

from pulse_probe import main
from pulse_probe.config import Settings
from pulse_probe.server_client import ServerClient
from pulse_probe.store import InMemoryStore


def _seed(state) -> None:
    state.store.index_heartbeats([
        {"@timestamp": "2026-07-15T10:00:00Z", "system_id": "a", "check_id": "db", "status": "ok", "response_ms": 10},
        {"@timestamp": "2026-07-15T10:01:00Z", "system_id": "a", "check_id": "db", "status": "error", "response_ms": 900},
    ])
    state.systems = [{
        "system_id": "a", "system_name": "A", "heartbeat_url": "https://a/api/heartbeat",
        "poll_interval_seconds": 30, "timeout_seconds": 5, "enabled": True,
    }]


def test_health_no_auth(client) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_ready(client) -> None:
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_query_requires_token(client) -> None:
    assert client.get("/api/v1/query/heartbeats").status_code == 401
    assert client.get("/api/v1/query/heartbeats", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_query_heartbeats(client, state, auth) -> None:
    _seed(state)
    r = client.get("/api/v1/query/heartbeats?system_id=a&status=error&page=1&page_size=10", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["status"] == "error"


def test_query_heartbeats_with_check_and_time(client, state, auth) -> None:
    _seed(state)
    r = client.get(
        "/api/v1/query/heartbeats?check_id=db&from=2026-07-15T09:00:00Z&to=2026-07-15T11:00:00Z&sort=@timestamp",
        headers=auth,
    )
    assert r.status_code == 200 and r.json()["total"] == 2


def test_query_advanced(client, state, auth) -> None:
    _seed(state)
    r = client.post(
        "/api/v1/query",
        headers=auth,
        json={
            "filters": [{"field": "system_id", "op": "eq", "value": "a"}],
            "aggregations": [{"type": "avg", "field": "response_ms"}, {"type": "count"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["aggregations"]["count"] == 2


def test_probe_systems(client, state, auth) -> None:
    _seed(state)
    r = client.get("/api/v1/systems", headers=auth)
    assert r.status_code == 200 and r.json()["items"][0]["system_id"] == "a"


def test_probe_status(client, state, auth) -> None:
    r = client.get("/api/v1/status", headers=auth)
    assert r.status_code == 200
    assert r.json()["probe_id"] == "probe-test"


def test_missing_auth_header(client) -> None:
    r = client.get("/api/v1/status")
    assert r.status_code == 401


# --------------------- bootstrap / sync_config -----------------------------


class _FakeServer(ServerClient):
    def __init__(self, *, needs_register: bool = False) -> None:
        self.needs_register = needs_register
        self.registered = False

    def register(self, enrollment_token, version):  # type: ignore[override]
        self.registered = True
        return {"probe_id": "p-new", "probe_token": "tok-new"}

    def get_config(self, token):  # type: ignore[override]
        return {"probe_id": "p-new", "systems": [{"system_id": "x"}], "config_version": "v9"}


def test_sync_config_with_enrollment() -> None:
    settings = Settings(opensearch_url=None, enrollment_token="enroll", probe_token=None)
    state = main.bootstrap_state(settings)
    state.server = _FakeServer(needs_register=True)
    main.sync_config(state)
    assert state.probe_token == "tok-new"
    assert state.config_version == "v9"
    assert state.systems and state.systems[0]["system_id"] == "x"


def test_sync_config_with_existing_token() -> None:
    settings = Settings(opensearch_url=None, probe_token="already")
    state = main.bootstrap_state(settings)
    state.server = _FakeServer()
    main.sync_config(state)
    assert state.probe_token == "already"
    assert state.config_version == "v9"


def test_send_liveness_triggers_resync() -> None:
    settings = Settings(opensearch_url=None, probe_token="tok")
    state = main.bootstrap_state(settings)

    calls = {"config": 0}

    class _S(ServerClient):
        def __init__(self) -> None:
            pass

        def send_liveness(self, token, body):  # type: ignore[override]
            return {"config_version": "v-new"}

        def get_config(self, token):  # type: ignore[override]
            calls["config"] += 1
            return {"probe_id": "p", "systems": [], "config_version": "v-new"}

    state.server = _S()
    state.config_version = "v-old"
    main._send_liveness(state)
    assert calls["config"] == 1 and state.config_version == "v-new"


def test_bootstrap_state_builds_inmemory() -> None:
    state = main.bootstrap_state(Settings(opensearch_url=None))
    assert isinstance(state.store, InMemoryStore)
