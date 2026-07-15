"""Test del poller: polling sistema, rilevazione eventi, rollup, ciclo completo."""

from __future__ import annotations

import httpx
import pytest

from pulse_probe import poller
from pulse_probe.config import Settings
from pulse_probe.server_client import ServerClient
from pulse_probe.state import RuntimeState
from pulse_probe.store import InMemoryStore


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


SYSTEM = {
    "system_id": "app", "system_name": "App", "heartbeat_url": "https://app/api/heartbeat",
    "poll_interval_seconds": 30, "timeout_seconds": 5, "enabled": True,
    "thresholds": {"response_ms_error": 500},
}


def test_poll_system_ok() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"check_id": "db", "status": "ok", "response_ms": 10})

    docs = poller.poll_system(_client(handler), SYSTEM, "p1")
    assert len(docs) == 1 and docs[0]["status"] == "ok" and docs[0]["reachable"] is True


def test_poll_system_http_error() -> None:
    docs = poller.poll_system(_client(lambda r: httpx.Response(503)), SYSTEM, "p1")
    assert docs[0]["status"] == "down" and docs[0]["http_status"] == 503


def test_poll_system_connection_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    docs = poller.poll_system(_client(handler), SYSTEM, "p1")
    assert docs[0]["status"] == "down" and docs[0]["reachable"] is False


def test_poll_system_non_json() -> None:
    docs = poller.poll_system(_client(lambda r: httpx.Response(200, text="not json")), SYSTEM, "p1")
    assert docs[0]["status"] == "down" and "non JSON" in docs[0]["message"]


def test_detect_events_transitions() -> None:
    last: dict[tuple[str, str], str] = {}
    # primo giro: nessun prev -> nessun status_changed, ma imposta stato
    docs_ok = [{"system_id": "a", "check_id": "db", "status": "ok", "response_ms": 10, "reachable": True, "@timestamp": "t1", "message": None}]
    assert poller.detect_events(docs_ok, last, {}, "p") == []
    # cambio ok->error
    docs_err = [{"system_id": "a", "check_id": "db", "status": "error", "response_ms": 10, "reachable": True, "@timestamp": "t2", "message": None}]
    ev = poller.detect_events(docs_err, last, {}, "p")
    assert any(e["type"] == "status_changed" for e in ev)
    # recovery error->ok
    ev2 = poller.detect_events(docs_ok, last, {}, "p")
    assert any(e["type"] == "system_recovered" for e in ev2)


def test_detect_events_unreachable_and_threshold() -> None:
    last: dict[tuple[str, str], str] = {}
    docs_down = [{"system_id": "a", "check_id": "c", "status": "down", "response_ms": None, "reachable": False, "@timestamp": "t", "message": None}]
    ev = poller.detect_events(docs_down, last, {}, "p")
    assert any(e["type"] == "system_unreachable" for e in ev)
    # ripetuto: gia' down -> nessun nuovo unreachable
    assert poller.detect_events(docs_down, last, {}, "p") == []
    # soglia response_ms superata
    last2: dict[tuple[str, str], str] = {}
    docs_slow = [{"system_id": "a", "check_id": "c", "status": "ok", "response_ms": 900, "reachable": True, "@timestamp": "t", "message": None}]
    ev2 = poller.detect_events(docs_slow, last2, {"response_ms_error": 500}, "p")
    assert any(e["type"] == "response_time_exceeded" for e in ev2)


def test_build_rollup() -> None:
    docs_by_system = {
        "a": [
            {"check_id": "db", "status": "ok", "response_ms": 10},
            {"check_id": "web", "status": "error", "response_ms": 30},
        ],
        "empty": [],
    }
    rollup = poller.build_rollup(docs_by_system, "1h")
    assert rollup["window"] == "1h"
    assert len(rollup["systems"]) == 1
    sys_a = rollup["systems"][0]
    assert sys_a["status"] == "error"  # peggiore
    assert sys_a["avg_response_ms"] == 20.0
    assert 0 <= sys_a["uptime_pct"] <= 100


class _FakeServer(ServerClient):
    def __init__(self) -> None:
        self.events: list = []
        self.rollups: list = []

    def send_events(self, token, events):  # type: ignore[override]
        self.events.append(events)
        return {"accepted": len(events)}

    def send_rollup(self, token, rollup):  # type: ignore[override]
        self.rollups.append(rollup)
        return {"accepted": True}


def _state(server: ServerClient) -> RuntimeState:
    return RuntimeState(
        settings=Settings(opensearch_url=None, poller_enabled=False),
        store=InMemoryStore(),
        server=server,
        probe_token="tok",
        probe_id="p1",
        systems=[SYSTEM, {"system_id": "off", "heartbeat_url": "https://x", "enabled": False}],
    )


def test_poll_once_full_cycle() -> None:
    server = _FakeServer()
    state = _state(server)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"check_id": "db", "status": "error", "response_ms": 900})

    # primo ciclo imposta stato; secondo genera eventi (status change vs prev)
    poller.poll_once(state, _client(handler))
    summary = poller.poll_once(state, _client(handler))
    assert summary["polled"] == 1  # il sistema disabilitato e' saltato
    assert server.rollups  # rollup inviato
    # sono stati indicizzati heartbeat
    items, total, _ = state.store.search_heartbeats()
    assert total >= 2


def test_poll_once_send_failure_marks_pending() -> None:
    class _Boom(ServerClient):
        def __init__(self) -> None:
            pass

        def send_events(self, token, events):  # type: ignore[override]
            raise RuntimeError("server down")

        def send_rollup(self, token, rollup):  # type: ignore[override]
            raise RuntimeError("server down")

    state = _state(_Boom())

    def handler(req: httpx.Request) -> httpx.Response:
        # response_ms oltre la soglia (500) -> evento response_time_exceeded ad ogni ciclo
        return httpx.Response(200, json={"check_id": "db", "status": "error", "response_ms": 900})

    poller.poll_once(state, _client(handler))  # evento generato, invio eventi fallisce
    assert state.pending_events > 0


def test_poll_once_without_token_skips_server() -> None:
    state = _state(_FakeServer())
    state.probe_token = None

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"check_id": "db", "status": "ok", "response_ms": 10})

    poller.poll_once(state, _client(handler))
    assert state.server.rollups == []  # type: ignore[attr-defined]
