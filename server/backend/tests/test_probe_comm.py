"""Test area Comunicazione Server<->Probe (§1.9)."""

from __future__ import annotations


def _create_probe(client, headers, name="probe-comm"):
    r = client.post(
        "/api/v1/probes",
        headers=headers,
        json={"name": name, "description": "", "query_endpoint": "https://p.local:8444", "tags": [], "enabled": True},
    ).json()
    return r["probe"]["id"], r["enrollment_token"]


def _enroll(client, token):
    return client.post(
        "/api/v1/probe/register",
        json={"enrollment_token": token, "hostname": "host1", "version": "1.0.0"},
    )


def test_full_probe_lifecycle(client, auth_headers) -> None:
    pid, token = _create_probe(client, auth_headers)
    reg = _enroll(client, token)
    assert reg.status_code == 200, reg.text
    probe_token = reg.json()["probe_token"]
    assert reg.json()["probe_id"] == pid
    ph = {"Authorization": f"Bearer {probe_token}"}

    # config pull
    cfg = client.get("/api/v1/probe/config", headers=ph)
    assert cfg.status_code == 200
    assert cfg.json()["probe_id"] == pid

    # liveness
    live = client.post(
        "/api/v1/probe/heartbeat",
        headers=ph,
        json={"version": "1.0.1", "uptime_seconds": 10, "opensearch_healthy": True, "systems_polled": 0, "last_poll_at": "2026-07-15T00:00:00Z"},
    )
    assert live.status_code == 200
    assert "config_version" in live.json()

    # rollup
    rollup = client.post(
        "/api/v1/probe/rollup",
        headers=ph,
        json={"window": "1h", "generated_at": "2026-07-15T00:00:00Z", "systems": [{"system_id": "s", "status": "ok", "avg_response_ms": 5.0, "uptime_pct": 100.0, "checks": []}]},
    )
    assert rollup.status_code == 202 and rollup.json()["accepted"] is True

    # events (nessun workflow abbinato -> accettati senza invii)
    events = client.post(
        "/api/v1/probe/events",
        headers=ph,
        json={"events": [{"type": "status_changed", "system_id": "s", "status": "error", "reachable": True, "timestamp": "2026-07-15T00:00:00Z"}]},
    )
    assert events.status_code == 202 and events.json()["accepted"] == 1

    # dopo la liveness lo stato admin-side e' online
    status = client.get(f"/api/v1/probes/{pid}/status", headers=auth_headers)
    assert status.json()["status"] == "online"


def test_register_invalid_token(client) -> None:
    r = _enroll(client, "totally-invalid-token")
    assert r.status_code == 401


def test_register_token_reuse_rejected(client, auth_headers) -> None:
    _, token = _create_probe(client, auth_headers, name="probe-reuse")
    assert _enroll(client, token).status_code == 200
    assert _enroll(client, token).status_code == 401


def test_register_disabled_probe(client, auth_headers, db_session) -> None:
    from pulse_server.models import Probe
    from sqlalchemy import select

    pid, token = _create_probe(client, auth_headers, name="probe-disabled")
    probe = db_session.get(Probe, __import__("uuid").UUID(pid))
    probe.enabled = False
    db_session.flush()
    r = _enroll(client, token)
    assert r.status_code == 403


def test_probe_endpoints_require_token(client) -> None:
    assert client.get("/api/v1/probe/config").status_code == 401
    r = client.get("/api/v1/probe/config", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_events_trigger_workflow_and_alarm(client, auth_headers, db_session) -> None:
    """Un evento che soddisfa un workflow apre un allarme e registra un invio."""
    from pulse_server.notifications import DeliveryResult, get_notifier, set_notifier

    class _Fake:
        def send(self, *a, **k):  # type: ignore[no-untyped-def]
            return DeliveryResult(True, "ok")

    original = get_notifier("telegram")
    set_notifier("telegram", _Fake())
    try:
        cid = client.post(
            "/api/v1/notification-channels",
            headers=auth_headers,
            json={"name": "ev-ch", "type": "telegram", "enabled": True, "inbound_enabled": False, "config": {"bot_token": "t", "webhook_secret": "s"}},
        ).json()["id"]
        client.post(
            "/api/v1/notification-workflows",
            headers=auth_headers,
            json={
                "name": "ev-wf", "description": "", "enabled": True, "trigger": "status_changed",
                "scope": {"probe_ids": [], "system_ids": [], "check_ids": []},
                "conditions": [{"field": "status", "op": "eq", "value": "error", "group": "g"}],
                "suppression": {"cooldown_seconds": 0, "dedup_window_seconds": 0, "respect_maintenance": True},
                "actions": [{"step_order": 0, "channel_id": cid, "recipients": ["chat"], "template": "{{status}}", "delay_seconds": 0}],
            },
        )
        pid, token = _create_probe(client, auth_headers, name="probe-ev")
        ph = {"Authorization": f"Bearer {_enroll(client, token).json()['probe_token']}"}
        r = client.post(
            "/api/v1/probe/events",
            headers=ph,
            json={"events": [{"type": "status_changed", "system_id": "s", "status": "error", "reachable": True, "timestamp": "2026-07-15T00:00:00Z"}]},
        )
        assert r.status_code == 202
        alarms = client.get("/api/v1/alarms?status=active", headers=auth_headers)
        assert alarms.json()["total"] >= 1
    finally:
        set_notifier("telegram", original)
