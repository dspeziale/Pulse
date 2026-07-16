"""Test dell'endpoint di test heartbeat POST /api/v1/systems/test.

Il target esterno e' simulato con httpx.MockTransport (nessun server reale):
il costruttore del client viene sostituito via monkeypatch.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from pulse_server.routers import systems as systems_router

_URL = "https://target.local/api/heartbeat"

VIEWER_ROLE = "00000000-0000-0000-0000-000000000004"


def _canonical_doc(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "@timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "system_id": "sys-1",
        "system_name": "System 1",
        "check_id": "cpu",
        "check_name": "CPU load",
        "status": "ok",
        "response_ms": 42,
        "message": "all good",
        "details": "n/a",
    }
    base.update(over)
    return base


def _patch_target(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def _mk(timeout_seconds: float) -> httpx.Client:
        return httpx.Client(transport=transport, timeout=timeout_seconds)

    monkeypatch.setattr(systems_router, "_build_test_client", _mk)


def _respond(payload: Any, status: int = 200):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def _post(client, headers, **body):
    payload = {"heartbeat_url": _URL}
    payload.update(body)
    return client.post("/api/v1/systems/test", headers=headers, json=payload)


# ------------------------------- schema valido -----------------------------


def test_valid_single_object(client, auth_headers, monkeypatch) -> None:
    _patch_target(monkeypatch, _respond(_canonical_doc()))
    r = _post(client, auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["reachable"] is True
    assert data["http_status"] == 200
    assert data["valid_schema"] is True
    assert data["checks_count"] == 1
    assert data["error"] is None
    assert len(data["documents"]) == 1
    assert data["documents"][0]["system_id"] == "sys-1"
    assert data["documents"][0]["response_ms"] == 42
    assert isinstance(data["response_ms"], int)


def test_valid_array_truncates_to_20(client, auth_headers, monkeypatch) -> None:
    docs = [_canonical_doc(check_id=f"c{i}") for i in range(25)]
    _patch_target(monkeypatch, _respond(docs))
    r = _post(client, auth_headers, timeout_seconds=10)
    assert r.status_code == 200
    data = r.json()
    assert data["valid_schema"] is True
    assert data["checks_count"] == 25
    assert len(data["documents"]) == 20


# ------------------------------- irraggiungibile ---------------------------


def test_target_unreachable(client, auth_headers, monkeypatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_target(monkeypatch, handler)
    r = _post(client, auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is False
    assert data["http_status"] is None
    assert data["valid_schema"] is False
    assert data["checks_count"] == 0
    assert data["documents"] == []
    assert data["error"] is not None


def test_reachable_with_5xx(client, auth_headers, monkeypatch) -> None:
    _patch_target(monkeypatch, _respond({"unexpected": True}, status=503))
    r = _post(client, auth_headers)
    data = r.json()
    assert data["reachable"] is True
    assert data["http_status"] == 503
    assert data["valid_schema"] is False


# ------------------------------- risposta non-JSON -------------------------


def test_non_json_response(client, auth_headers, monkeypatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>", headers={"content-type": "text/html"})

    _patch_target(monkeypatch, handler)
    r = _post(client, auth_headers)
    data = r.json()
    assert data["reachable"] is True
    assert data["http_status"] == 200
    assert data["valid_schema"] is False
    assert data["error"] is not None


# ------------------------------- schema JSON incompleto/invalido -----------


def test_incomplete_schema_missing_check_id(client, auth_headers, monkeypatch) -> None:
    doc = _canonical_doc()
    del doc["check_id"]
    _patch_target(monkeypatch, _respond(doc))
    r = _post(client, auth_headers)
    data = r.json()
    assert data["valid_schema"] is False
    assert data["checks_count"] == 0
    assert data["documents"] == []
    assert data["error"] is not None


def test_json_not_object_or_array(client, auth_headers, monkeypatch) -> None:
    _patch_target(monkeypatch, _respond(5))
    r = _post(client, auth_headers)
    assert r.json()["valid_schema"] is False


def test_empty_array(client, auth_headers, monkeypatch) -> None:
    _patch_target(monkeypatch, _respond([]))
    r = _post(client, auth_headers)
    assert r.json()["valid_schema"] is False


def test_array_with_non_dict_item(client, auth_headers, monkeypatch) -> None:
    _patch_target(monkeypatch, _respond([_canonical_doc(), "not-a-dict"]))
    r = _post(client, auth_headers)
    assert r.json()["valid_schema"] is False


# ------------------------------- 422 body non valido -----------------------


def test_invalid_url_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/systems/test", headers=auth_headers, json={"heartbeat_url": "ftp://nope"}
    )
    assert r.status_code == 422


def test_missing_url_422(client, auth_headers) -> None:
    r = client.post("/api/v1/systems/test", headers=auth_headers, json={})
    assert r.status_code == 422


def test_timeout_out_of_range_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/systems/test",
        headers=auth_headers,
        json={"heartbeat_url": _URL, "timeout_seconds": 100},
    )
    assert r.status_code == 422


# ------------------------------- 401 / 403 ---------------------------------


def test_no_token_401(client) -> None:
    r = client.post("/api/v1/systems/test", json={"heartbeat_url": _URL})
    assert r.status_code == 401


def test_forbidden_without_systems_create_or_update(client, auth_headers) -> None:
    # Utente con ruolo Viewer: ha systems.read ma non create/update -> 403.
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "username": "viewer1",
            "email": "viewer1@example.com",
            "full_name": "",
            "password": "Password123!",
            "role_ids": [VIEWER_ROLE],
            "status": "active",
        },
    )
    tok = client.post(
        "/api/v1/auth/login", json={"username": "viewer1", "password": "Password123!"}
    ).json()["access_token"]
    r = client.post(
        "/api/v1/systems/test",
        headers={"Authorization": f"Bearer {tok}"},
        json={"heartbeat_url": _URL},
    )
    assert r.status_code == 403


# ------------------------------- costruzione client reale ------------------


def test_build_test_client_is_httpx() -> None:
    c = systems_router._build_test_client(5.0)
    assert isinstance(c, httpx.Client)
    c.close()


# ------------------------------- TCP (esteso su richiesta utente) -----------


class _FakeSock:
    def __enter__(self) -> "_FakeSock":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False


def _patch_tcp(monkeypatch, ok: bool) -> None:
    def _conn(_addr, timeout=None):  # type: ignore[no-untyped-def]
        if not ok:
            raise OSError("connection refused")
        return _FakeSock()

    monkeypatch.setattr(systems_router.socket, "create_connection", _conn)


def test_tcp_reachable_true(client, auth_headers, monkeypatch) -> None:
    _patch_tcp(monkeypatch, ok=True)
    r = client.post(
        "/api/v1/systems/test",
        headers=auth_headers,
        json={"kind": "tcp", "tcp_host": "db.local", "tcp_port": 5432, "timeout_seconds": 3},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["reachable"] is True
    assert data["http_status"] is None
    assert data["valid_schema"] is True
    assert data["checks_count"] == 1
    assert data["error"] is None
    assert data["documents"][0]["check_id"] == "tcp"
    assert data["documents"][0]["status"] == "ok"
    assert isinstance(data["response_ms"], int)


def test_tcp_reachable_false(client, auth_headers, monkeypatch) -> None:
    _patch_tcp(monkeypatch, ok=False)
    r = client.post(
        "/api/v1/systems/test",
        headers=auth_headers,
        json={"kind": "tcp", "tcp_host": "db.local", "tcp_port": 5432},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is False
    assert data["valid_schema"] is False
    assert data["checks_count"] == 1
    assert data["documents"][0]["status"] == "down"
    assert data["error"] is not None


def test_tcp_missing_host_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/systems/test", headers=auth_headers, json={"kind": "tcp", "tcp_port": 5432}
    )
    assert r.status_code == 422


def test_tcp_missing_port_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/systems/test", headers=auth_headers, json={"kind": "tcp", "tcp_host": "db.local"}
    )
    assert r.status_code == 422


def test_tcp_port_out_of_range_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/systems/test",
        headers=auth_headers,
        json={"kind": "tcp", "tcp_host": "db.local", "tcp_port": 70000},
    )
    assert r.status_code == 422
