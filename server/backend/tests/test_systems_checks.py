"""Test aree Sistemi monitorati (§1.6) e Check (§1.7)."""

from __future__ import annotations

import datetime as dt


def _make_probe(client, headers, name="probe-sys"):
    return client.post(
        "/api/v1/probes",
        headers=headers,
        json={"name": name, "description": "", "query_endpoint": "https://p.local:8444", "tags": [], "enabled": True},
    ).json()["probe"]["id"]


def _make_system(client, headers, pid, **over):
    body = {
        "system_id": over.get("system_id", "sys-1"),
        "system_name": over.get("system_name", "System 1"),
        "heartbeat_url": "https://s.local/api/heartbeat",
        "probe_id": pid,
        "poll_interval_seconds": 30,
        "timeout_seconds": 5,
        "enabled": True,
        "thresholds": {"response_ms_warn": 300, "response_ms_error": 800},
    }
    body.update({k: over[k] for k in ("maintenance_windows",) if k in over})
    return client.post("/api/v1/systems", headers=headers, json=body)


def test_system_crud_with_windows_and_thresholds(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers)
    now = dt.datetime.now(dt.timezone.utc)
    windows = [{"start": now.isoformat(), "end": (now + dt.timedelta(hours=1)).isoformat(), "note": "maint"}]
    created = _make_system(client, auth_headers, pid, maintenance_windows=windows)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["thresholds"]["response_ms_warn"] == 300
    assert len(created.json()["maintenance_windows"]) == 1

    got = client.get(f"/api/v1/systems/{sid}", headers=auth_headers)
    assert got.status_code == 200

    upd = client.put(
        f"/api/v1/systems/{sid}",
        headers=auth_headers,
        json={"system_name": "Renamed", "thresholds": {"response_ms_warn": 100, "response_ms_error": 200}, "enabled": False},
    )
    assert upd.status_code == 200 and upd.json()["system_name"] == "Renamed"

    listed = client.get(f"/api/v1/systems?probe_id={pid}&enabled=false&q=Renamed", headers=auth_headers)
    assert listed.json()["total"] >= 1

    deleted = client.delete(f"/api/v1/systems/{sid}", headers=auth_headers)
    assert deleted.status_code == 204


def test_system_duplicate_id_conflict(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-dupsys")
    _make_system(client, auth_headers, pid, system_id="dup-sys")
    r = _make_system(client, auth_headers, pid, system_id="dup-sys", system_name="Other")
    assert r.status_code == 409


def test_system_unknown_probe_422(client, auth_headers) -> None:
    r = _make_system(client, auth_headers, "00000000-0000-0000-0000-0000000000bb", system_id="orphan")
    assert r.status_code == 422


def test_system_invalid_probe_uuid_422(client, auth_headers) -> None:
    r = _make_system(client, auth_headers, "not-a-uuid", system_id="orphan2")
    assert r.status_code == 422


def test_system_invalid_window_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-badwin")
    now = dt.datetime.now(dt.timezone.utc)
    windows = [{"start": now.isoformat(), "end": (now - dt.timedelta(hours=1)).isoformat(), "note": "bad"}]
    r = _make_system(client, auth_headers, pid, system_id="badwin", maintenance_windows=windows)
    assert r.status_code == 422


def test_system_not_found(client, auth_headers) -> None:
    ghost = "00000000-0000-0000-0000-0000000000dd"
    assert client.get(f"/api/v1/systems/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/systems/{ghost}", headers=auth_headers, json={"system_name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/systems/{ghost}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/systems/{ghost}/checks", headers=auth_headers).status_code == 404


def test_change_probe_on_update(client, auth_headers) -> None:
    pid1 = _make_probe(client, auth_headers, name="p-move-1")
    pid2 = _make_probe(client, auth_headers, name="p-move-2")
    sid = _make_system(client, auth_headers, pid1, system_id="movable").json()["id"]
    r = client.put(f"/api/v1/systems/{sid}", headers=auth_headers, json={"probe_id": pid2})
    assert r.status_code == 200 and r.json()["probe_id"] == pid2


def test_checks_endpoints_with_seeded_check(client, auth_headers, db_session) -> None:
    from pulse_server.models import DiscoveredCheck, MonitoredSystem
    from sqlalchemy import select

    pid = _make_probe(client, auth_headers, name="p-checks")
    sid_business = "sys-checks"
    _make_system(client, auth_headers, pid, system_id=sid_business)
    system = db_session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == sid_business)
    ).scalar_one()
    db_session.add(
        DiscoveredCheck(
            system_id=system.id, check_id="db", check_name="Database", probe_id=system.probe_id,
            last_status="ok", last_seen_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.flush()

    per_system = client.get(f"/api/v1/systems/{system.id}/checks", headers=auth_headers)
    assert per_system.status_code == 200
    assert per_system.json()["items"][0]["check_id"] == "db"

    glob = client.get(f"/api/v1/checks?system_id={sid_business}&probe_id={pid}", headers=auth_headers)
    assert glob.status_code == 200 and glob.json()["total"] >= 1
    assert glob.json()["items"][0]["system_id"] == sid_business
