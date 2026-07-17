"""Test proxy Server -> Probe per le scansioni NMAP (aggiunta su richiesta utente).

Il ProbeClient e' MOCKATO: nessuna Probe reale viene contattata.
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeScanClient:
    """ProbeClient finto che registra le chiamate e risponde in modo prevedibile."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def post_scan(self, base_url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("post_scan", body))
        return {
            "scan_id": "scan-1",
            "status": "running",
            "started_at": "2026-07-17T00:00:00Z",
            "target": body["target"],
        }

    def get_scans(self, base_url: str, token: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("get_scans", params))
        return {
            "items": [
                {
                    "scan_id": "scan-1",
                    "target": "192.168.1.0/24",
                    "status": "done",
                    "started_at": "2026-07-17T00:00:00Z",
                    "finished_at": "2026-07-17T00:01:00Z",
                    "summary": {"hosts_up": 2, "hosts_total": 254, "ports_open": 5},
                }
            ],
            "total": 1,
        }

    def get_scan(self, base_url: str, token: str, scan_id: str) -> dict[str, Any]:
        self.calls.append(("get_scan", scan_id))
        return {
            "scan_id": scan_id,
            "target": "192.168.1.0/24",
            "options": {"target": "192.168.1.0/24", "technique": "connect"},
            "status": "done",
            "started_at": "2026-07-17T00:00:00Z",
            "finished_at": "2026-07-17T00:01:00Z",
            "error": None,
            "summary": {"hosts_up": 2, "hosts_total": 254, "ports_open": 5},
            "hosts": [{"ip": "192.168.1.1", "ports": [{"port": 80, "state": "open"}]}],
        }


class _UnreachableScanClient:
    def _boom(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        from pulse_server import errors

        raise errors.service_unavailable("Probe non raggiungibile.")

    post_scan = _boom
    get_scans = _boom

    def get_scan(self, base_url: str, token: str, scan_id: str) -> dict[str, Any]:
        from pulse_server import errors

        raise errors.not_found("Risorsa inesistente sulla Probe.")


def _client_with_scan(db_session, scan_client):
    from fastapi.testclient import TestClient

    from pulse_server.context import get_probe_client
    from pulse_server.db import get_session
    from pulse_server.main import create_app

    app = create_app()

    def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_probe_client] = lambda: scan_client
    return TestClient(app), app


def _probe(client, headers, name="p-scan"):
    return client.post(
        "/api/v1/probes",
        headers=headers,
        json={
            "name": name,
            "description": "",
            "query_endpoint": "https://p.local:8444",
            "tags": [],
            "enabled": True,
        },
    ).json()["probe"]["id"]


def _scans_read_token(client, headers) -> str:
    """Crea un utente con SOLO scans.read (ruolo custom) e ne ritorna l'access token."""
    rid = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "scan-viewer", "description": "", "permission_codes": ["scans.read"]},
    ).json()["id"]
    client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "scanviewer",
            "email": "scanviewer@example.com",
            "full_name": "",
            "password": "Password123!",
            "role_ids": [rid],
            "status": "active",
        },
    )
    return str(
        client.post(
            "/api/v1/auth/login", json={"username": "scanviewer", "password": "Password123!"}
        ).json()["access_token"]
    )


# --------------------------------------------------------------------------- #
# POST /probes/{id}/scan                                                       #
# --------------------------------------------------------------------------- #


def test_start_scan_ok_and_audit_written(db_session, auth_headers) -> None:
    from sqlalchemy import select

    from pulse_server.models import AuditLog

    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        pid = _probe(client, auth_headers)
        r = client.post(
            f"/api/v1/probes/{pid}/scan",
            headers=auth_headers,
            json={"target": "192.168.1.0/24", "technique": "syn", "timing": "T4"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["scan_id"] == "scan-1"
        assert r.json()["status"] == "running"
        assert ("post_scan", {"target": "192.168.1.0/24", "technique": "syn", "timing": "T4",
                              "service_version": False, "os_detection": False, "no_ping": False,
                              "scripts": []}) == fake.calls[0]
        # Audit scritto con action scans.run, entita' probe, riassunto opzioni.
        rows = db_session.execute(
            select(AuditLog).where(AuditLog.action == "scans.run")
        ).scalars().all()
        match = [a for a in rows if a.entity_id == pid]
        assert match, "audit scans.run mancante"
        entry = match[-1]
        assert entry.entity_type == "probe"
        assert entry.outcome == "success"
        assert entry.details == {"target": "192.168.1.0/24", "technique": "syn", "timing": "T4"}
    finally:
        app.dependency_overrides.clear()


def test_start_scan_without_permission_403(db_session, auth_headers) -> None:
    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        pid = _probe(client, auth_headers, name="p-scan-403")
        token = _scans_read_token(client, auth_headers)
        r = client.post(
            f"/api/v1/probes/{pid}/scan",
            headers={"Authorization": f"Bearer {token}"},
            json={"target": "10.0.0.1"},
        )
        assert r.status_code == 403
        # Nessuna chiamata inoltrata alla Probe.
        assert fake.calls == []
    finally:
        app.dependency_overrides.clear()


def test_start_scan_without_token_401(db_session, auth_headers) -> None:
    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        pid = _probe(client, auth_headers, name="p-scan-401")
        r = client.post(f"/api/v1/probes/{pid}/scan", json={"target": "10.0.0.1"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_start_scan_probe_unreachable_503(db_session, auth_headers) -> None:
    client, app = _client_with_scan(db_session, _UnreachableScanClient())
    try:
        pid = _probe(client, auth_headers, name="p-scan-503")
        r = client.post(
            f"/api/v1/probes/{pid}/scan", headers=auth_headers, json={"target": "10.0.0.1"}
        )
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_start_scan_unknown_probe_404(db_session, auth_headers) -> None:
    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        r = client.post(
            "/api/v1/probes/00000000-0000-0000-0000-0000000000ff/scan",
            headers=auth_headers,
            json={"target": "10.0.0.1"},
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# GET /probes/{id}/scans e /scan/{scan_id}                                     #
# --------------------------------------------------------------------------- #


def test_list_scans_ok(db_session, auth_headers) -> None:
    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        pid = _probe(client, auth_headers, name="p-scan-list")
        # Il ruolo scans.read basta per la lettura.
        token = _scans_read_token(client, auth_headers)
        r = client.get(
            f"/api/v1/probes/{pid}/scans?page=2&page_size=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["scan_id"] == "scan-1"
        assert fake.calls[0] == ("get_scans", {"page": 2, "page_size": 10})
    finally:
        app.dependency_overrides.clear()


def test_get_scan_detail_ok(db_session, auth_headers) -> None:
    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        pid = _probe(client, auth_headers, name="p-scan-detail")
        r = client.get(f"/api/v1/probes/{pid}/scan/scan-1", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["scan_id"] == "scan-1"
        assert body["hosts"][0]["ip"] == "192.168.1.1"
        assert fake.calls[0] == ("get_scan", "scan-1")
    finally:
        app.dependency_overrides.clear()


def test_get_scan_detail_not_found_404(db_session, auth_headers) -> None:
    client, app = _client_with_scan(db_session, _UnreachableScanClient())
    try:
        pid = _probe(client, auth_headers, name="p-scan-missing")
        r = client.get(f"/api/v1/probes/{pid}/scan/nope", headers=auth_headers)
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_scans_read_without_token_401(db_session, auth_headers) -> None:
    fake = _FakeScanClient()
    client, app = _client_with_scan(db_session, fake)
    try:
        pid = _probe(client, auth_headers, name="p-scan-noauth")
        assert client.get(f"/api/v1/probes/{pid}/scans").status_code == 401
        assert client.get(f"/api/v1/probes/{pid}/scan/x").status_code == 401
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# ProbeQueryClient reale (metodi scan) con httpx mockato                       #
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpx:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    def __enter__(self) -> "_FakeHttpx":
        return self

    def __exit__(self, *_a: Any) -> bool:
        return False

    def request(self, *_a: Any, **_k: Any) -> _Resp:
        return self._resp


def _real_client(monkeypatch, resp: _Resp):
    from pulse_server.config import get_settings
    from pulse_server.proxy import ProbeQueryClient

    c = ProbeQueryClient(get_settings())
    monkeypatch.setattr(c, "_client", lambda: _FakeHttpx(resp))
    return c


def test_real_post_scan(monkeypatch) -> None:
    c = _real_client(monkeypatch, _Resp(200, {"scan_id": "x", "status": "running"}))
    out = c.post_scan("https://p", "tok", {"target": "1.2.3.4"})
    assert out["scan_id"] == "x"


def test_real_get_scans(monkeypatch) -> None:
    c = _real_client(monkeypatch, _Resp(200, {"items": [], "total": 0}))
    out = c.get_scans("https://p", "tok", {"page": 1, "page_size": 20})
    assert out["total"] == 0


def test_real_get_scan_ok(monkeypatch) -> None:
    c = _real_client(monkeypatch, _Resp(200, {"scan_id": "abc", "status": "done"}))
    out = c.get_scan("https://p", "tok", "abc")
    assert out["scan_id"] == "abc"


def test_real_get_scan_404(monkeypatch) -> None:
    from pulse_server import errors

    c = _real_client(monkeypatch, _Resp(404, {}))
    with pytest.raises(errors.ApiError) as exc:
        c.get_scan("https://p", "tok", "missing")
    assert exc.value.status_code == 404
