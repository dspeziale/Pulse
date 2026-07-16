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


def _make_tcp_system(client, headers, pid, **over):
    body = {
        "system_id": over.get("system_id", "tcp-1"),
        "system_name": over.get("system_name", "TCP System 1"),
        "kind": "tcp",
        "tcp_host": over.get("tcp_host", "db.local"),
        "tcp_port": over.get("tcp_port", 5432),
        "probe_id": pid,
        "poll_interval_seconds": 30,
        "timeout_seconds": 5,
        "enabled": True,
    }
    for k in ("tcp_host", "tcp_port", "heartbeat_url"):
        if k in over:
            body[k] = over[k]
    return client.post("/api/v1/systems", headers=headers, json=body)


def test_create_tcp_system_ok(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-tcp-ok")
    r = _make_tcp_system(client, auth_headers, pid, system_id="tcp-ok")
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["kind"] == "tcp"
    assert data["tcp_host"] == "db.local"
    assert data["tcp_port"] == 5432
    assert data["heartbeat_url"] is None
    # rilettura: i campi tcp sono serializzati
    got = client.get(f"/api/v1/systems/{data['id']}", headers=auth_headers).json()
    assert got["kind"] == "tcp" and got["tcp_port"] == 5432


def test_create_http_system_has_kind_default(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-http-default")
    r = _make_system(client, auth_headers, pid, system_id="http-default")
    assert r.status_code == 201
    assert r.json()["kind"] == "http"
    assert r.json()["tcp_host"] is None and r.json()["tcp_port"] is None


def test_create_tcp_without_host_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-tcp-nohost")
    r = client.post(
        "/api/v1/systems",
        headers=auth_headers,
        json={
            "system_id": "tcp-nohost", "system_name": "x", "kind": "tcp",
            "tcp_port": 443, "probe_id": pid,
            "poll_interval_seconds": 30, "timeout_seconds": 5,
        },
    )
    assert r.status_code == 422


def test_create_tcp_without_port_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-tcp-noport")
    r = client.post(
        "/api/v1/systems",
        headers=auth_headers,
        json={
            "system_id": "tcp-noport", "system_name": "x", "kind": "tcp",
            "tcp_host": "h.local", "probe_id": pid,
            "poll_interval_seconds": 30, "timeout_seconds": 5,
        },
    )
    assert r.status_code == 422


def test_create_http_without_url_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-http-nourl")
    r = client.post(
        "/api/v1/systems",
        headers=auth_headers,
        json={
            "system_id": "http-nourl", "system_name": "x", "kind": "http",
            "probe_id": pid, "poll_interval_seconds": 30, "timeout_seconds": 5,
        },
    )
    assert r.status_code == 422


def test_create_tcp_port_out_of_range_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-tcp-badport")
    r = _make_tcp_system(client, auth_headers, pid, system_id="tcp-badport", tcp_port=70000)
    assert r.status_code == 422


def test_create_http_invalid_url_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-http-badurl")
    r = _make_system(client, auth_headers, pid, system_id="http-badurl")
    # override heartbeat_url con schema non http
    r = client.post(
        "/api/v1/systems",
        headers=auth_headers,
        json={
            "system_id": "http-badurl2", "system_name": "x", "kind": "http",
            "heartbeat_url": "ftp://nope", "probe_id": pid,
            "poll_interval_seconds": 30, "timeout_seconds": 5,
        },
    )
    assert r.status_code == 422


def test_update_system_to_tcp_ok(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-upd-tcp")
    sid = _make_system(client, auth_headers, pid, system_id="upd-to-tcp").json()["id"]
    r = client.put(
        f"/api/v1/systems/{sid}",
        headers=auth_headers,
        json={"kind": "tcp", "tcp_host": "svc.local", "tcp_port": 8080},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "tcp" and r.json()["tcp_port"] == 8080


def test_update_to_tcp_without_port_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-upd-tcp-bad")
    sid = _make_system(client, auth_headers, pid, system_id="upd-tcp-bad").json()["id"]
    r = client.put(
        f"/api/v1/systems/{sid}",
        headers=auth_headers,
        json={"kind": "tcp", "tcp_host": "svc.local"},
    )
    assert r.status_code == 422


def test_update_tcp_port_out_of_range_422(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-upd-badport")
    sid = _make_system(client, auth_headers, pid, system_id="upd-badport").json()["id"]
    r = client.put(f"/api/v1/systems/{sid}", headers=auth_headers, json={"tcp_port": 0})
    assert r.status_code == 422


def test_update_heartbeat_url_valid_and_invalid(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-upd-url")
    sid = _make_system(client, auth_headers, pid, system_id="upd-url").json()["id"]
    ok = client.put(
        f"/api/v1/systems/{sid}",
        headers=auth_headers,
        json={"heartbeat_url": "https://new.local/api/heartbeat"},
    )
    assert ok.status_code == 200 and ok.json()["heartbeat_url"].endswith("/api/heartbeat")
    bad = client.put(
        f"/api/v1/systems/{sid}", headers=auth_headers, json={"heartbeat_url": "ftp://nope"}
    )
    assert bad.status_code == 422


def test_list_systems_filter_by_kind(client, auth_headers) -> None:
    pid = _make_probe(client, auth_headers, name="probe-kind-filter")
    _make_system(client, auth_headers, pid, system_id="kf-http")
    _make_tcp_system(client, auth_headers, pid, system_id="kf-tcp")

    http_only = client.get(f"/api/v1/systems?probe_id={pid}&kind=http", headers=auth_headers)
    assert http_only.status_code == 200
    kinds = {i["kind"] for i in http_only.json()["items"]}
    assert kinds == {"http"}
    assert any(i["system_id"] == "kf-http" for i in http_only.json()["items"])

    tcp_only = client.get(f"/api/v1/systems?probe_id={pid}&kind=tcp", headers=auth_headers)
    assert tcp_only.status_code == 200
    tcp_kinds = {i["kind"] for i in tcp_only.json()["items"]}
    assert tcp_kinds == {"tcp"}
    assert any(i["system_id"] == "kf-tcp" for i in tcp_only.json()["items"])

    # senza filtro kind: entrambi presenti
    both = client.get(f"/api/v1/systems?probe_id={pid}", headers=auth_headers)
    assert both.json()["total"] >= 2


def test_list_systems_kind_combined_with_other_probe(client, auth_headers) -> None:
    pid1 = _make_probe(client, auth_headers, name="probe-kind-p1")
    pid2 = _make_probe(client, auth_headers, name="probe-kind-p2")
    _make_tcp_system(client, auth_headers, pid1, system_id="kc-tcp-p1")
    _make_tcp_system(client, auth_headers, pid2, system_id="kc-tcp-p2")
    r = client.get(f"/api/v1/systems?kind=tcp&probe_id={pid1}", headers=auth_headers)
    assert r.status_code == 200
    ids = {i["system_id"] for i in r.json()["items"]}
    assert ids == {"kc-tcp-p1"}


def test_list_systems_invalid_kind_422(client, auth_headers) -> None:
    r = client.get("/api/v1/systems?kind=ftp", headers=auth_headers)
    assert r.status_code == 422


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


# --- config_version bump della Probe su create/update/delete (re-sync) --------

import uuid as _uuid  # noqa: E402

from pulse_server.models import Probe  # noqa: E402


def _probe_cfg_version(db_session, pid: str) -> str | None:
    probe = db_session.get(Probe, _uuid.UUID(pid))
    db_session.refresh(probe)
    return probe.config_version


def _set_cfg_version(db_session, pid: str, value: str) -> None:
    probe = db_session.get(Probe, _uuid.UUID(pid))
    probe.config_version = value
    db_session.flush()


def test_create_system_bumps_probe_config_version(client, auth_headers, db_session) -> None:
    pid = _make_probe(client, auth_headers, name="p-bump-create")
    _set_cfg_version(db_session, pid, "SENTINEL-0")
    r = _make_system(client, auth_headers, pid, system_id="bump-create-sys")
    assert r.status_code == 201
    assert _probe_cfg_version(db_session, pid) not in (None, "SENTINEL-0")


def test_update_system_bumps_probe_config_version(client, auth_headers, db_session) -> None:
    pid = _make_probe(client, auth_headers, name="p-bump-upd")
    sid = _make_system(client, auth_headers, pid, system_id="bump-upd-sys").json()["id"]
    _set_cfg_version(db_session, pid, "SENTINEL-1")
    r = client.put(f"/api/v1/systems/{sid}", headers=auth_headers, json={"enabled": False})
    assert r.status_code == 200
    assert _probe_cfg_version(db_session, pid) != "SENTINEL-1"


def test_reassign_system_bumps_both_probes(client, auth_headers, db_session) -> None:
    pid1 = _make_probe(client, auth_headers, name="p-bump-src")
    pid2 = _make_probe(client, auth_headers, name="p-bump-dst")
    sid = _make_system(client, auth_headers, pid1, system_id="bump-move-sys").json()["id"]
    _set_cfg_version(db_session, pid1, "SENTINEL-SRC")
    _set_cfg_version(db_session, pid2, "SENTINEL-DST")
    r = client.put(f"/api/v1/systems/{sid}", headers=auth_headers, json={"probe_id": pid2})
    assert r.status_code == 200 and r.json()["probe_id"] == pid2
    # entrambe le Probe (vecchia e nuova) devono essere state bumpate
    assert _probe_cfg_version(db_session, pid1) != "SENTINEL-SRC"
    assert _probe_cfg_version(db_session, pid2) != "SENTINEL-DST"


def test_delete_system_bumps_probe_config_version(client, auth_headers, db_session) -> None:
    pid = _make_probe(client, auth_headers, name="p-bump-del")
    sid = _make_system(client, auth_headers, pid, system_id="bump-del-sys").json()["id"]
    _set_cfg_version(db_session, pid, "SENTINEL-DEL")
    r = client.delete(f"/api/v1/systems/{sid}", headers=auth_headers)
    assert r.status_code == 204
    assert _probe_cfg_version(db_session, pid) != "SENTINEL-DEL"


def test_bump_config_version_unknown_probe_is_noop(db_session) -> None:
    """Il bump su una Probe inesistente non solleva errori (ramo difensivo)."""
    from pulse_server.routers.systems import _bump_probe_config_version

    _bump_probe_config_version(db_session, _uuid.uuid4())  # nessuna eccezione
