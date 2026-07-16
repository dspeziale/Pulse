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


def test_probe_registry_fields_create_and_read(client, auth_headers) -> None:
    """create con anagrafica -> ProbeOut la riporta; default null se assente."""
    r = client.post(
        "/api/v1/probes",
        headers=auth_headers,
        json={
            "name": "probe-registry", "description": "", "query_endpoint": "https://p.local:8444",
            "tags": [], "enabled": True,
            "location": "DC Milano", "contact_name": "Mario Rossi",
            "contact_email": "mario.rossi@example.com", "contact_phone": "+39 02 1234567",
        },
    )
    assert r.status_code == 201, r.text
    probe = r.json()["probe"]
    assert probe["location"] == "DC Milano"
    assert probe["contact_name"] == "Mario Rossi"
    assert probe["contact_email"] == "mario.rossi@example.com"
    assert probe["contact_phone"] == "+39 02 1234567"
    # rilettura
    got = client.get(f"/api/v1/probes/{probe['id']}", headers=auth_headers).json()
    assert got["contact_email"] == "mario.rossi@example.com"


def test_probe_registry_defaults_null(client, auth_headers) -> None:
    r = _create_probe(client, auth_headers, name="probe-no-registry")
    probe = r.json()["probe"]
    assert probe["location"] is None
    assert probe["contact_name"] is None
    assert probe["contact_email"] is None
    assert probe["contact_phone"] is None


def test_probe_registry_partial_update(client, auth_headers) -> None:
    pid = _create_probe(client, auth_headers, name="probe-upd-registry").json()["probe"]["id"]
    upd = client.put(
        f"/api/v1/probes/{pid}",
        headers=auth_headers,
        json={"contact_name": "Anna Bianchi", "contact_phone": "3331112222"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["contact_name"] == "Anna Bianchi"
    assert upd.json()["contact_phone"] == "3331112222"
    # gli altri campi anagrafici restano invariati (null)
    assert upd.json()["location"] is None
    # secondo update parziale: valorizza location e contact_email
    upd2 = client.put(
        f"/api/v1/probes/{pid}",
        headers=auth_headers,
        json={"location": "DC Roma", "contact_email": "anna.bianchi@example.com"},
    )
    assert upd2.status_code == 200, upd2.text
    assert upd2.json()["location"] == "DC Roma"
    assert upd2.json()["contact_email"] == "anna.bianchi@example.com"
    # contact_name impostato al primo update resta invariato
    assert upd2.json()["contact_name"] == "Anna Bianchi"


def test_probe_invalid_contact_email_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/probes",
        headers=auth_headers,
        json={
            "name": "probe-bademail", "description": "", "query_endpoint": "https://p.local:8444",
            "tags": [], "enabled": True, "contact_email": "not-an-email",
        },
    )
    assert r.status_code == 422


def test_probe_blank_contact_email_becomes_null(client, auth_headers) -> None:
    """Una stringa vuota per contact_email e' normalizzata a null (no 422)."""
    r = client.post(
        "/api/v1/probes",
        headers=auth_headers,
        json={
            "name": "probe-blankemail", "description": "", "query_endpoint": "https://p.local:8444",
            "tags": [], "enabled": True, "contact_email": "   ",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["probe"]["contact_email"] is None


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
