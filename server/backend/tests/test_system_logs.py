"""Test dell'istrumentazione di write_system_log sugli eventi operativi.

BUG risolto: system_logs era sempre vuoto perche' write_system_log non veniva
mai chiamata. Qui si verifica che ogni evento chiave persista una riga.

NB: il vincolo DB CHECK su system_logs.component ammette SOLO {'server','probe'};
la categoria operativa (auth/config/notifications/scans/enrollment/...) e' quindi
riportata nel campo `logger`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select

from pulse_server.models import SystemLog

ADMIN_ROLE = "00000000-0000-0000-0000-000000000002"


def _logs(session, **filters: Any) -> list[SystemLog]:
    stmt = select(SystemLog)
    for key, value in filters.items():
        stmt = stmt.where(getattr(SystemLog, key) == value)
    return list(session.execute(stmt).scalars().all())


def _new_probe(client, headers, name: str) -> dict[str, Any]:
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
    ).json()


# --------------------------------------------------------------------------- #
# Avvio applicazione                                                           #
# --------------------------------------------------------------------------- #


def test_startup_log_written(db_session, monkeypatch) -> None:
    from pulse_server import db as db_mod
    from pulse_server import main

    class _Ctx:
        def __enter__(self):
            return db_session

        def __exit__(self, *_a: Any) -> bool:
            return False  # non chiude la sessione di test

    monkeypatch.setattr(db_mod, "get_session_factory", lambda: (lambda: _Ctx()))
    main._emit_startup_log()
    rows = _logs(db_session, component="server", logger="startup")
    assert any("Avvio del server Pulse" in r.message for r in rows)


def test_startup_log_never_raises(monkeypatch) -> None:
    from pulse_server import db as db_mod
    from pulse_server import main

    def _boom():
        raise RuntimeError("db non disponibile")

    monkeypatch.setattr(db_mod, "get_session_factory", _boom)
    # Non deve sollevare: il logging di avvio e' best-effort.
    main._emit_startup_log()


# --------------------------------------------------------------------------- #
# Enrollment / rotazione Probe                                                 #
# --------------------------------------------------------------------------- #


def test_enrollment_writes_system_log(client, auth_headers, db_session) -> None:
    created = _new_probe(client, auth_headers, "sl-enroll")
    pid = created["probe"]["id"]
    r = client.post(
        "/api/v1/probe/register",
        json={"enrollment_token": created["enrollment_token"], "hostname": "host-abc", "version": "9.9"},
    )
    assert r.status_code == 200, r.text
    rows = _logs(db_session, component="probe", logger="enrollment")
    match = [row for row in rows if row.probe_id == uuid.UUID(pid)]
    assert match, "system_log enrollment mancante"
    assert match[-1].level == "info"
    assert "host-abc" in match[-1].message


def test_rotate_credentials_writes_warning_log(client, auth_headers, db_session) -> None:
    created = _new_probe(client, auth_headers, "sl-rotate")
    pid = created["probe"]["id"]
    r = client.post(f"/api/v1/probes/{pid}/rotate-credentials", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = _logs(db_session, component="probe", logger="rotate")
    match = [row for row in rows if row.probe_id == uuid.UUID(pid)]
    assert match, "system_log rotate mancante"
    assert match[-1].level == "warning"


# --------------------------------------------------------------------------- #
# Blocco account (lockout)                                                     #
# --------------------------------------------------------------------------- #


def test_lockout_writes_warning_log(client, auth_headers, db_session) -> None:
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "username": "lockme",
            "email": "lockme@example.com",
            "full_name": "",
            "password": "Password123!",
            "role_ids": [ADMIN_ROLE],
            "status": "active",
        },
    )
    # Soglia default = 5: cinque tentativi errati -> lockout.
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "lockme", "password": "wrong-pw"})
    rows = _logs(db_session, component="server", logger="auth", level="warning")
    assert any("lockme" in r.message and "bloccato" in r.message for r in rows)
    # Il log del lockout e' UNICO (non uno per tentativo): niente spam.
    lock_rows = [r for r in rows if "lockme" in r.message]
    assert len(lock_rows) == 1


# --------------------------------------------------------------------------- #
# Aggiornamento configurazione                                                 #
# --------------------------------------------------------------------------- #


def test_config_update_writes_system_log(client, auth_headers, db_session) -> None:
    r = client.put(
        "/api/v1/config",
        headers=auth_headers,
        json={"items": [{"key": "retention_system_logs_days", "value": 90}]},
    )
    assert r.status_code == 200, r.text
    rows = _logs(db_session, component="server", logger="config")
    assert any("retention_system_logs_days" in row.message for row in rows)


# --------------------------------------------------------------------------- #
# Avvio scansione NMAP (proxy)                                                 #
# --------------------------------------------------------------------------- #


class _FakeScanClient:
    def post_scan(self, base_url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "scan_id": "scan-sl",
            "status": "running",
            "started_at": "2026-07-17T00:00:00Z",
            "target": body["target"],
        }


def test_scan_start_writes_system_log(db_session, auth_headers) -> None:
    from fastapi.testclient import TestClient

    from pulse_server.context import get_probe_client
    from pulse_server.db import get_session
    from pulse_server.main import create_app

    app = create_app()

    def _sess():
        yield db_session

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_probe_client] = lambda: _FakeScanClient()
    try:
        with TestClient(app) as c:
            created = _new_probe(c, auth_headers, "sl-scan")
            pid = created["probe"]["id"]
            r = c.post(
                f"/api/v1/probes/{pid}/scan",
                headers=auth_headers,
                json={"target": "10.10.0.0/24", "technique": "connect"},
            )
            assert r.status_code == 200, r.text
        rows = _logs(db_session, component="probe", logger="scans")
        match = [row for row in rows if row.probe_id == uuid.UUID(pid)]
        assert match, "system_log scans mancante"
        assert "10.10.0.0/24" in match[-1].message
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Esito consegna notifica                                                      #
# --------------------------------------------------------------------------- #


def test_notification_delivery_writes_system_log(db_session) -> None:
    from pulse_server import workflow
    from pulse_server.models import (
        MonitoredSystem,
        NotificationChannel,
        NotificationWorkflow,
        Probe,
        WorkflowAction,
    )
    from pulse_server.notifications import (
        DeliveryResult,
        encrypt_config,
        get_notifier,
        set_notifier,
    )
    from pulse_server.security import SecretBox

    box = SecretBox("test-key")

    class _Fake:
        def send(self, config: Any, recipient: Any, message: Any) -> DeliveryResult:
            return DeliveryResult(True, "ok")

    original = get_notifier("telegram")
    set_notifier("telegram", _Fake())
    try:
        probe = Probe(name=f"sl-not-{dt.datetime.now().timestamp()}", status="online", tags=[])
        db_session.add(probe)
        db_session.flush()
        db_session.add(
            MonitoredSystem(
                system_id="sl-not-sys", system_name="S", heartbeat_url="https://s/api/heartbeat",
                probe_id=probe.id, poll_interval_seconds=30, timeout_seconds=5, enabled=True,
            )
        )
        channel = NotificationChannel(
            name=f"sl-not-ch-{dt.datetime.now().timestamp()}", type="telegram", enabled=True,
            inbound_enabled=False, config=encrypt_config(box, {"bot_token": "t", "webhook_secret": "s"}),
        )
        db_session.add(channel)
        wf = NotificationWorkflow(
            name=f"sl-not-wf-{dt.datetime.now().timestamp()}", description="", enabled=True,
            trigger="status_changed", scope={}, suppression={},
        )
        db_session.add(wf)
        db_session.flush()
        db_session.add(
            WorkflowAction(
                workflow_id=wf.id, step_order=0, channel_id=channel.id, recipients=["chat"],
                template="{{status}}", delay_seconds=0,
            )
        )
        db_session.flush()
        workflow.process_event(
            db_session,
            {"type": "status_changed", "system_id": "sl-not-sys", "status": "error", "reachable": True},
            box=box,
        )
        db_session.flush()
        rows = _logs(db_session, component="server", logger="notifications")
        assert rows and rows[-1].level == "info"
        assert "telegram" in rows[-1].message
    finally:
        set_notifier("telegram", original)


def test_notification_failure_writes_error_log(db_session) -> None:
    from pulse_server import workflow
    from pulse_server.models import (
        MonitoredSystem,
        NotificationChannel,
        NotificationWorkflow,
        Probe,
        WorkflowAction,
    )
    from pulse_server.notifications import (
        DeliveryResult,
        encrypt_config,
        get_notifier,
        set_notifier,
    )
    from pulse_server.security import SecretBox

    box = SecretBox("test-key")

    class _Boom:
        def send(self, config: Any, recipient: Any, message: Any) -> DeliveryResult:
            return DeliveryResult(False, "provider ko")

    original = get_notifier("telegram")
    set_notifier("telegram", _Boom())
    try:
        probe = Probe(name=f"sl-err-{dt.datetime.now().timestamp()}", status="online", tags=[])
        db_session.add(probe)
        db_session.flush()
        db_session.add(
            MonitoredSystem(
                system_id="sl-err-sys", system_name="S", heartbeat_url="https://s/api/heartbeat",
                probe_id=probe.id, poll_interval_seconds=30, timeout_seconds=5, enabled=True,
            )
        )
        channel = NotificationChannel(
            name=f"sl-err-ch-{dt.datetime.now().timestamp()}", type="telegram", enabled=True,
            inbound_enabled=False, config=encrypt_config(box, {"bot_token": "t", "webhook_secret": "s"}),
        )
        db_session.add(channel)
        wf = NotificationWorkflow(
            name=f"sl-err-wf-{dt.datetime.now().timestamp()}", description="", enabled=True,
            trigger="status_changed", scope={}, suppression={},
        )
        db_session.add(wf)
        db_session.flush()
        db_session.add(
            WorkflowAction(
                workflow_id=wf.id, step_order=0, channel_id=channel.id, recipients=["chat"],
                template="{{status}}", delay_seconds=0,
            )
        )
        db_session.flush()
        workflow.process_event(
            db_session,
            {"type": "status_changed", "system_id": "sl-err-sys", "status": "error", "reachable": True},
            box=box,
        )
        db_session.flush()
        rows = _logs(db_session, component="server", logger="notifications", level="error")
        assert rows, "system_log notifica fallita mancante"
    finally:
        set_notifier("telegram", original)


# --------------------------------------------------------------------------- #
# Verifica anche via GET /logs                                                 #
# --------------------------------------------------------------------------- #


def test_logs_endpoint_returns_config_event(client, auth_headers) -> None:
    client.put(
        "/api/v1/config",
        headers=auth_headers,
        json={"items": [{"key": "retention_system_logs_days", "value": 90}]},
    )
    r = client.get("/api/v1/logs?component=server", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
