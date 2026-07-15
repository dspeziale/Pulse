"""Test aree Audit (§1.14), Log (§1.15), Config (§1.16), Health (§1.17)."""

from __future__ import annotations

import datetime as dt


def test_audit_list_and_detail(client, auth_headers, db_session) -> None:
    # il login admin (fixture) ha gia' generato una voce di audit auth.login
    listed = client.get("/api/v1/audit?action=auth.login&outcome=success", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    aid = listed.json()["items"][0]["id"]

    detail = client.get(f"/api/v1/audit/{aid}", headers=auth_headers)
    assert detail.status_code == 200 and detail.json()["id"] == aid


def test_audit_filters(client, auth_headers) -> None:
    r = client.get(
        "/api/v1/audit?actor=x&entity_type=user&entity_id=y&from=2020-01-01T00:00:00Z&to=2100-01-01T00:00:00Z",
        headers=auth_headers,
    )
    assert r.status_code == 200


def test_audit_not_found(client, auth_headers) -> None:
    r = client.get("/api/v1/audit/00000000-0000-0000-0000-0000000000ef", headers=auth_headers)
    assert r.status_code == 404


def test_logs_list_and_filters(client, auth_headers, db_session) -> None:
    from pulse_server.audit import write_system_log

    write_system_log(db_session, component="server", level="info", message="hello world", logger="test")
    db_session.flush()
    r = client.get(
        "/api/v1/logs?component=server&level=info&q=hello&from=2020-01-01T00:00:00Z&to=2100-01-01T00:00:00Z",
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["total"] >= 1


def test_logs_bad_timestamp(client, auth_headers) -> None:
    assert client.get("/api/v1/logs?from=bad", headers=auth_headers).status_code == 400


def test_config_list_get_update(client, auth_headers) -> None:
    listed = client.get("/api/v1/config", headers=auth_headers)
    assert listed.status_code == 200
    assert any(i["key"] == "api_port" for i in listed.json()["items"])

    one = client.get("/api/v1/config/access_token_ttl_seconds", headers=auth_headers)
    assert one.status_code == 200 and one.json()["key"] == "access_token_ttl_seconds"

    upd = client.put(
        "/api/v1/config",
        headers=auth_headers,
        json={"items": [{"key": "access_token_ttl_seconds", "value": 600}, {"key": "api_port", "value": 8443}]},
    )
    assert upd.status_code == 200
    assert "access_token_ttl_seconds" in upd.json()["updated"]
    assert "api_port" in upd.json()["requires_restart"]


def test_config_get_not_found(client, auth_headers) -> None:
    assert client.get("/api/v1/config/nope", headers=auth_headers).status_code == 404


def test_config_update_unknown_key_422(client, auth_headers) -> None:
    r = client.put("/api/v1/config", headers=auth_headers, json={"items": [{"key": "nope", "value": 1}]})
    assert r.status_code == 422


def test_health_and_ready(client) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"


def test_health_ready_db_error() -> None:
    """Se il DB non risponde, /ready ritorna 503."""
    from fastapi.testclient import TestClient

    from pulse_server.db import get_session
    from pulse_server.main import create_app

    app = create_app()

    class _BrokenSession:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

    def _override():
        yield _BrokenSession()

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        r = c.get("/api/v1/health/ready")
    assert r.status_code == 503
    app.dependency_overrides.clear()
