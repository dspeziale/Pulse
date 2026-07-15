"""Test mirati sui rami difensivi residui (deps, update workflow, filtri)."""

from __future__ import annotations

import datetime as dt


# ------------------------------- deps.py -----------------------------------


def test_client_ip_none() -> None:
    from pulse_server.deps import client_ip

    class _Req:
        client = None

    assert client_ip(_Req()) is None  # type: ignore[arg-type]


def test_token_invalid_subject(client) -> None:
    from pulse_server.config import get_settings
    from pulse_server.security import create_access_token

    s = get_settings()
    tok = create_access_token(secret=s.jwt_secret, algorithm=s.jwt_algorithm, subject="not-a-uuid", ttl_seconds=60, roles=[], permissions=[])
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_token_unknown_user(client) -> None:
    from pulse_server.config import get_settings
    from pulse_server.security import create_access_token

    s = get_settings()
    tok = create_access_token(secret=s.jwt_secret, algorithm=s.jwt_algorithm, subject="00000000-0000-0000-0000-0000000000ff", ttl_seconds=60, roles=[], permissions=[])
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_disabled_user_token_forbidden(client, auth_headers) -> None:
    # crea utente, ottiene token, poi lo disabilita -> le richieste diventano 403
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"username": "todisable", "email": "td@pulse.local", "full_name": "", "password": "Password123!", "role_ids": ["00000000-0000-0000-0000-000000000002"], "status": "active"},
    )
    tok = client.post("/api/v1/auth/login", json={"username": "todisable", "password": "Password123!"}).json()["access_token"]
    uid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["id"]
    client.put(f"/api/v1/users/{uid}", headers=auth_headers, json={"status": "disabled"})
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_probe_token_disabled_forbidden(client, auth_headers, db_session) -> None:
    from pulse_server.models import Probe
    import uuid as _uuid

    created = client.post(
        "/api/v1/probes",
        headers=auth_headers,
        json={"name": "p-deps", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True},
    ).json()
    token = created["enrollment_token"]
    reg = client.post("/api/v1/probe/register", json={"enrollment_token": token, "hostname": "h", "version": "1"})
    ptok = reg.json()["probe_token"]
    probe = db_session.get(Probe, _uuid.UUID(created["probe"]["id"]))
    probe.enabled = False
    db_session.flush()
    r = client.get("/api/v1/probe/config", headers={"Authorization": f"Bearer {ptok}"})
    assert r.status_code == 403


# ------------------------------- workflows update --------------------------


def test_workflow_update_all_fields(client, auth_headers) -> None:
    cid = client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={"name": "wf-upd-ch", "type": "telegram", "enabled": True, "inbound_enabled": False, "config": {"bot_token": "t", "webhook_secret": "s"}},
    ).json()["id"]
    wid = client.post(
        "/api/v1/notification-workflows",
        headers=auth_headers,
        json={
            "name": "wf-upd", "description": "", "enabled": True, "trigger": "status_changed",
            "scope": {"probe_ids": [], "system_ids": [], "check_ids": []}, "conditions": [],
            "suppression": {"cooldown_seconds": 0, "dedup_window_seconds": 0, "respect_maintenance": True},
            "actions": [{"step_order": 0, "channel_id": cid, "recipients": ["c"], "template": "t", "delay_seconds": 0}],
        },
    ).json()["id"]
    r = client.put(
        f"/api/v1/notification-workflows/{wid}",
        headers=auth_headers,
        json={
            "name": "wf-upd2", "trigger": "system_unreachable", "enabled": False,
            "scope": {"probe_ids": ["p"], "system_ids": [], "check_ids": []},
            "suppression": {"cooldown_seconds": 10, "dedup_window_seconds": 5, "respect_maintenance": False},
            "conditions": [{"field": "reachable", "op": "eq", "value": False, "group": "g"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "wf-upd2" and body["trigger"] == "system_unreachable" and body["enabled"] is False
    assert body["scope"]["probe_ids"] == ["p"]


def test_workflow_update_bad_trigger(client, auth_headers) -> None:
    cid = client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={"name": "wf-bt-ch", "type": "telegram", "enabled": True, "inbound_enabled": False, "config": {"bot_token": "t", "webhook_secret": "s"}},
    ).json()["id"]
    wid = client.post(
        "/api/v1/notification-workflows",
        headers=auth_headers,
        json={
            "name": "wf-bt", "description": "", "enabled": True, "trigger": "status_changed",
            "scope": {"probe_ids": [], "system_ids": [], "check_ids": []}, "conditions": [],
            "suppression": {"cooldown_seconds": 0, "dedup_window_seconds": 0, "respect_maintenance": True},
            "actions": [{"step_order": 0, "channel_id": cid, "recipients": ["c"], "template": "t", "delay_seconds": 0}],
        },
    ).json()["id"]
    r = client.put(f"/api/v1/notification-workflows/{wid}", headers=auth_headers, json={"trigger": "invalid"})
    assert r.status_code == 422


def test_alarm_filters_system_probe(client, auth_headers, db_session) -> None:
    from pulse_server.models import Alarm, MonitoredSystem, Probe

    probe = Probe(name="al-probe", status="online", tags=[])
    db_session.add(probe)
    db_session.flush()
    system = MonitoredSystem(
        system_id="al-sys", system_name="S", heartbeat_url="https://s/api/heartbeat",
        probe_id=probe.id, poll_interval_seconds=30, timeout_seconds=5, enabled=True,
    )
    db_session.add(system)
    db_session.flush()
    db_session.add(Alarm(status="active", system_id=system.id, probe_id=probe.id, opened_at=dt.datetime.now(dt.timezone.utc)))
    db_session.flush()
    r = client.get(f"/api/v1/alarms?system_id={system.id}&probe_id={probe.id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["total"] >= 1


def test_alarm_bad_timestamp(client, auth_headers) -> None:
    assert client.get("/api/v1/alarms?from=bad", headers=auth_headers).status_code == 400


def test_probe_update_name_and_endpoint(client, auth_headers) -> None:
    pid = client.post(
        "/api/v1/probes", headers=auth_headers,
        json={"name": "pu-1", "description": "", "query_endpoint": "https://a:8444", "tags": [], "enabled": True},
    ).json()["probe"]["id"]
    r = client.put(
        f"/api/v1/probes/{pid}", headers=auth_headers,
        json={"name": "pu-2", "query_endpoint": "https://b:8444"},
    )
    assert r.status_code == 200 and r.json()["query_endpoint"] == "https://b:8444"


def test_system_update_windows(client, auth_headers) -> None:
    pid = client.post(
        "/api/v1/probes", headers=auth_headers,
        json={"name": "sw-probe", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True},
    ).json()["probe"]["id"]
    sid = client.post(
        "/api/v1/systems", headers=auth_headers,
        json={"system_id": "sw-sys", "system_name": "S", "heartbeat_url": "https://s/api/heartbeat", "probe_id": pid, "poll_interval_seconds": 30, "timeout_seconds": 5, "enabled": True},
    ).json()["id"]
    now = dt.datetime.now(dt.timezone.utc)
    r = client.put(
        f"/api/v1/systems/{sid}", headers=auth_headers,
        json={"maintenance_windows": [{"start": now.isoformat(), "end": (now + dt.timedelta(hours=2)).isoformat(), "note": "n"}]},
    )
    assert r.status_code == 200 and len(r.json()["maintenance_windows"]) == 1


def test_probe_config_version_fallback(client, auth_headers, db_session) -> None:
    import uuid as _uuid

    from pulse_server.models import Probe

    created = client.post(
        "/api/v1/probes", headers=auth_headers,
        json={"name": "cv-probe", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True},
    ).json()
    ptok = client.post(
        "/api/v1/probe/register",
        json={"enrollment_token": created["enrollment_token"], "hostname": "h", "version": "1"},
    ).json()["probe_token"]
    probe = db_session.get(Probe, _uuid.UUID(created["probe"]["id"]))
    probe.config_version = None
    db_session.flush()
    r = client.get("/api/v1/probe/config", headers={"Authorization": f"Bearer {ptok}"})
    assert r.status_code == 200 and r.json()["config_version"]


def test_systems_update_all_fields(client, auth_headers) -> None:
    pid = client.post(
        "/api/v1/probes", headers=auth_headers,
        json={"name": "sys-upd-probe", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True},
    ).json()["probe"]["id"]
    sid = client.post(
        "/api/v1/systems", headers=auth_headers,
        json={"system_id": "upd-sys", "system_name": "S", "heartbeat_url": "https://s/api/heartbeat", "probe_id": pid, "poll_interval_seconds": 30, "timeout_seconds": 5, "enabled": True},
    ).json()["id"]
    r = client.put(
        f"/api/v1/systems/{sid}", headers=auth_headers,
        json={"heartbeat_url": "https://new/api/heartbeat", "poll_interval_seconds": 60, "timeout_seconds": 10},
    )
    assert r.status_code == 200 and r.json()["poll_interval_seconds"] == 60
