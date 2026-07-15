"""Test mirati per completare la copertura al 100% (rami difensivi/filtri)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

ADMIN_ID = "00000000-0000-0000-0000-0000000000a1"
ADMIN_ROLE = "00000000-0000-0000-0000-000000000002"
OPERATOR_ROLE = "00000000-0000-0000-0000-000000000003"


# ------------------------------- context / helpers -------------------------


def test_get_probe_client_factory() -> None:
    from pulse_server.config import get_settings
    from pulse_server.context import get_probe_client

    assert get_probe_client(get_settings()) is not None


def test_count_active_superadmins_without_exclude(db_session) -> None:
    from pulse_server.routers.users import _count_active_superadmins

    assert _count_active_superadmins(db_session) >= 1


# ------------------------------- deps / auth -------------------------------


def test_probe_wrong_token_after_enrollment(client, auth_headers) -> None:
    """deps: loop su Probe con token_hash presente ma non corrispondente -> 401."""
    created = client.post(
        "/api/v1/probes",
        headers=auth_headers,
        json={"name": "p-wrongtok", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True},
    ).json()
    client.post(
        "/api/v1/probe/register",
        json={"enrollment_token": created["enrollment_token"], "hostname": "h", "version": "1"},
    )
    r = client.get("/api/v1/probe/config", headers={"Authorization": "Bearer totally-wrong-token"})
    assert r.status_code == 401


def test_refresh_disabled_user(client, auth_headers) -> None:
    """auth: refresh con utente disabilitato -> 401."""
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"username": "refdis", "email": "refdis@example.com", "full_name": "", "password": "Password123!", "role_ids": [ADMIN_ROLE], "status": "active"},
    )
    login = client.post("/api/v1/auth/login", json={"username": "refdis", "password": "Password123!"}).json()
    uid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"}).json()["id"]
    client.put(f"/api/v1/users/{uid}", headers=auth_headers, json={"status": "disabled"})
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 401


def test_logout_unknown_refresh_token(client, auth_headers) -> None:
    """auth: logout con refresh token inesistente -> 204 (nessuna revoca ma ok)."""
    r = client.post("/api/v1/auth/logout", headers=auth_headers, json={"refresh_token": "does-not-exist"})
    assert r.status_code == 204


# ------------------------------- filtri "senza parametri" ------------------


def test_list_endpoints_without_filters(client, auth_headers) -> None:
    for path in (
        "/api/v1/probes",
        "/api/v1/systems",
        "/api/v1/checks",
        "/api/v1/roles",
        "/api/v1/users",
        "/api/v1/notification-channels",
        "/api/v1/notification-workflows",
        "/api/v1/alarms",
        "/api/v1/audit",
        "/api/v1/logs",
        "/api/v1/notifications/history",
    ):
        assert client.get(path, headers=auth_headers).status_code == 200


def test_notifications_history_workflow_filter(client, auth_headers) -> None:
    wid = str(uuid.uuid4())
    r = client.get(f"/api/v1/notifications/history?workflow_id={wid}", headers=auth_headers)
    assert r.status_code == 200


def test_logs_probe_and_checks_filters(client, auth_headers, db_session) -> None:
    from pulse_server.audit import write_system_log
    from pulse_server.models import Probe

    probe = Probe(name="log-probe", status="online", tags=[])
    db_session.add(probe)
    db_session.flush()
    write_system_log(db_session, component="probe", level="error", message="x", probe_id=probe.id)
    db_session.flush()
    r = client.get(f"/api/v1/logs?probe_id={probe.id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["total"] >= 1
    # checks filtrati per system_id + probe_id
    assert client.get(f"/api/v1/checks?system_id=none&probe_id={probe.id}", headers=auth_headers).status_code == 200


# ------------------------------- roles / users edge ------------------------


def test_workflow_update_without_conditions_actions(client, auth_headers) -> None:
    """workflows 195->197: PUT che non tocca conditions/actions."""
    cid = client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={"name": "wf-min-ch", "type": "telegram", "enabled": True, "inbound_enabled": False, "config": {"bot_token": "t", "webhook_secret": "s"}},
    ).json()["id"]
    wid = client.post(
        "/api/v1/notification-workflows",
        headers=auth_headers,
        json={"name": "wf-min", "description": "", "enabled": True, "trigger": "status_changed", "scope": {"probe_ids": [], "system_ids": [], "check_ids": []}, "conditions": [], "suppression": {"cooldown_seconds": 0, "dedup_window_seconds": 0, "respect_maintenance": True}, "actions": [{"step_order": 0, "channel_id": cid, "recipients": ["c"], "template": "t", "delay_seconds": 0}]},
    ).json()["id"]
    r = client.put(f"/api/v1/notification-workflows/{wid}", headers=auth_headers, json={"description": "solo-descr"})
    assert r.status_code == 200 and r.json()["description"] == "solo-descr"


def test_role_update_name_noncustom(client, auth_headers) -> None:
    """roles: aggiornamento del nome su ruolo custom (ramo body.name is not None)."""
    rid = client.post(
        "/api/v1/roles", headers=auth_headers, json={"name": "renme", "description": "d", "permission_codes": []}
    ).json()["id"]
    r = client.put(f"/api/v1/roles/{rid}", headers=auth_headers, json={"name": "renamed-ok"})
    assert r.status_code == 200 and r.json()["name"] == "renamed-ok"


def test_non_superadmin_cannot_remove_last_superadmin(client, auth_headers) -> None:
    """users 150/185: un Admin (non SuperAdmin) non puo' disabilitare/eliminare l'ultimo SuperAdmin."""
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"username": "adminuser", "email": "adminuser@example.com", "full_name": "", "password": "Password123!", "role_ids": [ADMIN_ROLE], "status": "active"},
    )
    tok = client.post("/api/v1/auth/login", json={"username": "adminuser", "password": "Password123!"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    # admin (seed) e' l'unico SuperAdmin attivo; adminuser non e' SuperAdmin
    disable = client.put(f"/api/v1/users/{ADMIN_ID}", headers=h, json={"status": "disabled"})
    assert disable.status_code == 409
    delete = client.delete(f"/api/v1/users/{ADMIN_ID}", headers=h)
    assert delete.status_code == 409


# ------------------------------- dashboard ---------------------------------


def test_dashboard_aggregate_probe_without_rollup(client, auth_headers) -> None:
    """dashboard 114->121: probe senza rollup salta il ciclo systems."""
    client.post(
        "/api/v1/probes",
        headers=auth_headers,
        json={"name": "p-norollup-agg", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True},
    )
    r = client.get("/api/v1/dashboard/aggregate", headers=auth_headers)
    assert r.status_code == 200


# ------------------------------- inbound whatsapp malformed ----------------


def test_whatsapp_malformed_payload_400(client, auth_headers) -> None:
    import hashlib
    import hmac
    import json

    client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={"name": "wa-mal", "type": "whatsapp", "enabled": True, "inbound_enabled": True, "config": {"provider": "meta", "api_base": "https://g", "api_token": "t", "phone_number_id": "1", "webhook_secret": "wa-sec"}},
    )
    raw = json.dumps({"entry": [{"changes": [{"value": {}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"wa-sec", raw, hashlib.sha256).hexdigest()
    r = client.post("/api/v1/inbound/whatsapp", headers={"X-Hub-Signature-256": sig}, content=raw)
    assert r.status_code == 400


# ------------------------------- probe_comm CA + threshold -----------------


def _client_with_settings(db_session, **overrides):
    from pulse_server.config import Settings, get_settings
    from pulse_server.db import get_session
    from pulse_server.main import create_app

    app = create_app()

    def _sess():
        yield db_session

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_settings] = lambda: Settings(**overrides)
    return app


def test_probe_register_reads_ca_and_config_threshold(tmp_path, db_session) -> None:
    """probe_comm 62-64 (lettura CA) e 90 (_threshold con sistema assegnato)."""
    ca = tmp_path / "ca.pem"
    ca.write_text("---CA---", encoding="utf-8")
    app = _client_with_settings(db_session, tls_ca_cert_path=str(ca))
    with TestClient(app) as c:
        # login admin per creare probe + sistema
        tok = c.post("/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        created = c.post("/api/v1/probes", headers=h, json={"name": "p-ca", "description": "", "query_endpoint": "https://p:8444", "tags": [], "enabled": True}).json()
        pid = created["probe"]["id"]
        c.post("/api/v1/systems", headers=h, json={"system_id": "ca-sys", "system_name": "S", "heartbeat_url": "https://s/api/heartbeat", "probe_id": pid, "poll_interval_seconds": 30, "timeout_seconds": 5, "enabled": True, "thresholds": {"response_ms_warn": 100, "response_ms_error": 200}})
        reg = c.post("/api/v1/probe/register", json={"enrollment_token": created["enrollment_token"], "hostname": "h", "version": "1"})
        assert reg.status_code == 200 and reg.json()["ca_certificate"] == "---CA---"
        ptok = reg.json()["probe_token"]
        cfg = c.get("/api/v1/probe/config", headers={"Authorization": f"Bearer {ptok}"})
        assert cfg.status_code == 200
        assert cfg.json()["systems"][0]["thresholds"]["response_ms_error"] == 200
    app.dependency_overrides.clear()
