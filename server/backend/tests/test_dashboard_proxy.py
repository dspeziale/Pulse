"""Test area Heartbeat/Query proxy e Dashboard (§1.8)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest


class _FakeProbeClient:
    def get_heartbeats(self, base_url: str, token: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"items": [{"@timestamp": "2026-07-15T00:00:00Z", "status": "ok"}], "total": 1}

    def post_query(self, base_url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"items": [], "aggregations": {"avg_response_ms": 42}, "total": 0}


@pytest.fixture()
def client_with_probe(db_session):
    from fastapi.testclient import TestClient

    from pulse_server.context import get_probe_client
    from pulse_server.db import get_session
    from pulse_server.main import create_app

    app = create_app()

    def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_probe_client] = lambda: _FakeProbeClient()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _probe(client, headers, name="p-dash"):
    return client.post(
        "/api/v1/probes",
        headers=headers,
        json={"name": name, "description": "", "query_endpoint": "https://p.local:8444", "tags": [], "enabled": True},
    ).json()["probe"]["id"]


def test_get_heartbeats_proxy(client_with_probe, auth_headers) -> None:
    pid = _probe(client_with_probe, auth_headers)
    r = client_with_probe.get(
        f"/api/v1/probes/{pid}/heartbeats?system_id=s1&status=ok&from=2026-01-01T00:00:00Z&page=1&page_size=10",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_post_query_proxy(client_with_probe, auth_headers) -> None:
    pid = _probe(client_with_probe, auth_headers, name="p-query")
    r = client_with_probe.post(
        f"/api/v1/probes/{pid}/query",
        headers=auth_headers,
        json={"filters": [{"field": "status", "op": "eq", "value": "error"}], "from": "2026-01-01T00:00:00Z"},
    )
    assert r.status_code == 200
    assert r.json()["aggregations"]["avg_response_ms"] == 42


def test_heartbeats_probe_without_endpoint_503(client_with_probe, auth_headers, db_session) -> None:
    from pulse_server.models import Probe
    from sqlalchemy import select

    pid = _probe(client_with_probe, auth_headers, name="p-noendpoint")
    probe = db_session.execute(select(Probe).where(Probe.name == "p-noendpoint")).scalar_one()
    probe.query_endpoint = None
    db_session.flush()
    r = client_with_probe.get(f"/api/v1/probes/{pid}/heartbeats", headers=auth_headers)
    assert r.status_code == 503


def test_heartbeats_unknown_probe_404(client_with_probe, auth_headers) -> None:
    r = client_with_probe.get(
        "/api/v1/probes/00000000-0000-0000-0000-0000000000ab/heartbeats", headers=auth_headers
    )
    assert r.status_code == 404


def test_dashboard_aggregate(client_with_probe, auth_headers, db_session) -> None:
    from pulse_server.models import Probe, ProbeRollup
    from sqlalchemy import select

    pid = _probe(client_with_probe, auth_headers, name="p-agg")
    probe = db_session.execute(select(Probe).where(Probe.name == "p-agg")).scalar_one()
    db_session.add(
        ProbeRollup(
            probe_id=probe.id,
            window="24h",
            payload={"systems": [{"system_id": "s", "status": "down"}, {"system_id": "s2", "status": "ok"}]},
            generated_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.flush()
    r = client_with_probe.get("/api/v1/dashboard/aggregate?window=24h", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["systems_summary"]["down"] >= 1
    assert any(p["probe_id"] == str(probe.id) for p in data["probes"])


def test_dashboard_probe(client_with_probe, auth_headers, db_session) -> None:
    from pulse_server.models import Probe, ProbeRollup
    from sqlalchemy import select

    pid = _probe(client_with_probe, auth_headers, name="p-single")
    probe = db_session.execute(select(Probe).where(Probe.name == "p-single")).scalar_one()
    db_session.add(
        ProbeRollup(
            probe_id=probe.id, window="1h",
            payload={"systems": [{"system_id": "s", "status": "ok", "avg_response_ms": 10, "uptime_pct": 99.9, "checks": []}]},
            generated_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.flush()
    r = client_with_probe.get(f"/api/v1/dashboard/probe/{pid}", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()["systems"]) == 1


def test_dashboard_probe_no_rollup(client_with_probe, auth_headers) -> None:
    pid = _probe(client_with_probe, auth_headers, name="p-norollup")
    r = client_with_probe.get(f"/api/v1/dashboard/probe/{pid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["systems"] == []


def test_proxy_service_unavailable_on_http_error(db_session, auth_headers, monkeypatch) -> None:
    """Il client reale mappa gli errori httpx a 503."""
    import httpx

    from pulse_server.config import get_settings
    from pulse_server.proxy import ProbeQueryClient
    from pulse_server import errors

    client = ProbeQueryClient(get_settings())

    class _Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(client, "_client", lambda: _Boom())
    with pytest.raises(errors.ApiError) as exc:
        client.get_heartbeats("https://x", "t", {})
    assert exc.value.status_code == 503
