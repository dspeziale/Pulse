"""Test area Probe (§1.5)."""

from __future__ import annotations


def _create_probe(client, headers, name="probe-a"):
    return client.post(
        "/api/v1/probes",
        headers=headers,
        json={
            "name": name,
            "description": "Probe A",
            "query_endpoint": "https://probe-a.local:8444",
            "tags": ["dc1"],
            "enabled": True,
        },
    )


def test_probe_crud_and_enrollment(client, auth_headers) -> None:
    created = _create_probe(client, auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["enrollment_token"]
    assert body["enrollment_expires_at"]
    pid = body["probe"]["id"]
    assert body["probe"]["status"] == "pending"
    assert body["probe"]["systems_count"] == 0

    got = client.get(f"/api/v1/probes/{pid}", headers=auth_headers)
    assert got.status_code == 200

    upd = client.put(f"/api/v1/probes/{pid}", headers=auth_headers, json={"description": "upd", "tags": ["dc2"], "enabled": False})
    assert upd.status_code == 200 and upd.json()["enabled"] is False

    listed = client.get("/api/v1/probes?q=probe-a&status=pending", headers=auth_headers)
    assert listed.json()["total"] >= 1

    status = client.get(f"/api/v1/probes/{pid}/status", headers=auth_headers)
    assert status.status_code == 200 and status.json()["status"] == "pending"

    deleted = client.delete(f"/api/v1/probes/{pid}", headers=auth_headers)
    assert deleted.status_code == 204


def test_probe_duplicate_name_conflict(client, auth_headers) -> None:
    _create_probe(client, auth_headers, name="dupprobe")
    r = _create_probe(client, auth_headers, name="dupprobe")
    assert r.status_code == 409


def test_rotate_credentials(client, auth_headers) -> None:
    pid = _create_probe(client, auth_headers, name="rot").json()["probe"]["id"]
    r = client.post(f"/api/v1/probes/{pid}/rotate-credentials", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enrollment_token"]


def test_delete_probe_with_systems_conflict(client, auth_headers) -> None:
    pid = _create_probe(client, auth_headers, name="withsys").json()["probe"]["id"]
    client.post(
        "/api/v1/systems",
        headers=auth_headers,
        json={
            "system_id": "sys-on-probe", "system_name": "S", "heartbeat_url": "https://s.local/api/heartbeat",
            "probe_id": pid, "poll_interval_seconds": 30, "timeout_seconds": 5, "enabled": True,
        },
    )
    r = client.delete(f"/api/v1/probes/{pid}", headers=auth_headers)
    assert r.status_code == 409


def test_probe_not_found(client, auth_headers) -> None:
    ghost = "00000000-0000-0000-0000-0000000000cc"
    assert client.get(f"/api/v1/probes/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/probes/{ghost}", headers=auth_headers, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/probes/{ghost}", headers=auth_headers).status_code == 404
    assert client.post(f"/api/v1/probes/{ghost}/rotate-credentials", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/probes/{ghost}/status", headers=auth_headers).status_code == 404
