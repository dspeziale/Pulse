"""Test del motore workflow con effetti sul DB (process_event)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from pulse_server import workflow
from pulse_server.models import (
    Alarm,
    MaintenanceWindow,
    MonitoredSystem,
    NotificationChannel,
    NotificationDelivery,
    NotificationWorkflow,
    Probe,
    WorkflowAction,
    WorkflowCondition,
)
from pulse_server.notifications import DeliveryResult, get_notifier, set_notifier
from pulse_server.security import SecretBox

BOX = SecretBox("test-key")


class _Fake:
    def __init__(self, ok: bool = True, boom: bool = False) -> None:
        self.ok = ok
        self.boom = boom
        self.count = 0

    def send(self, config, recipient, message):  # type: ignore[no-untyped-def]
        self.count += 1
        if self.boom:
            raise RuntimeError("provider down")
        return DeliveryResult(self.ok, "ok" if self.ok else "fail")


@pytest.fixture()
def telegram_fake():
    original = get_notifier("telegram")
    fake = _Fake()
    set_notifier("telegram", fake)
    yield fake
    set_notifier("telegram", original)


def _setup(session, *, trigger="status_changed", conditions=None, suppression=None, recipients=("chat",)):
    probe = Probe(name=f"wp-{dt.datetime.now().timestamp()}", status="online", tags=[])
    session.add(probe)
    session.flush()
    system = MonitoredSystem(
        system_id="wf-sys", system_name="S", heartbeat_url="https://s/api/heartbeat",
        probe_id=probe.id, poll_interval_seconds=30, timeout_seconds=5, enabled=True,
    )
    session.add(system)
    channel = NotificationChannel(
        name=f"wc-{dt.datetime.now().timestamp()}", type="telegram", enabled=True, inbound_enabled=False,
        config={"bot_token": "t", "webhook_secret": "s"},
    )
    session.add(channel)
    session.flush()
    wf = NotificationWorkflow(
        name=f"wf-{dt.datetime.now().timestamp()}", description="", enabled=True, trigger=trigger,
        scope={}, suppression=suppression or {},
    )
    session.add(wf)
    session.flush()
    for idx, c in enumerate(conditions or []):
        session.add(WorkflowCondition(workflow_id=wf.id, field=c["field"], op=c["op"], value=c["value"], order_index=idx))
    session.add(
        WorkflowAction(
            workflow_id=wf.id, step_order=0, channel_id=channel.id, recipients=list(recipients),
            template="{{status}}", delay_seconds=0,
        )
    )
    session.flush()
    return probe, system, channel, wf


def test_process_opens_alarm_and_sends(db_session, telegram_fake) -> None:
    _setup(db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}])
    event = {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}
    workflow.process_event(db_session, event, box=BOX)
    db_session.flush()
    alarms = db_session.execute(select(Alarm).where(Alarm.status == "active")).scalars().all()
    assert len(alarms) == 1
    assert telegram_fake.count == 1
    deliveries = db_session.execute(select(NotificationDelivery)).scalars().all()
    assert deliveries and deliveries[0].status == "sent"


def test_process_reuses_existing_alarm(db_session, telegram_fake) -> None:
    _setup(db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}])
    event = {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}
    workflow.process_event(db_session, event, box=BOX)
    workflow.process_event(db_session, event, box=BOX)
    db_session.flush()
    alarms = db_session.execute(select(Alarm)).scalars().all()
    assert len(alarms) == 1  # dedup: stesso allarme riusato


def test_cooldown_suppression(db_session, telegram_fake) -> None:
    _setup(
        db_session,
        conditions=[{"field": "status", "op": "eq", "value": "error"}],
        suppression={"cooldown_seconds": 3600},
    )
    event = {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}
    workflow.process_event(db_session, event, box=BOX)
    first = telegram_fake.count
    workflow.process_event(db_session, event, box=BOX)  # entro cooldown -> soppresso
    assert telegram_fake.count == first


def test_maintenance_suppression(db_session, telegram_fake) -> None:
    probe, system, _, _ = _setup(
        db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}],
        suppression={"respect_maintenance": True},
    )
    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(
        MaintenanceWindow(system_id=system.id, probe_id=probe.id, start_at=now - dt.timedelta(hours=1), end_at=now + dt.timedelta(hours=1))
    )
    db_session.flush()
    event = {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}
    workflow.process_event(db_session, event, box=BOX, now=now)
    assert telegram_fake.count == 0


def test_global_maintenance_window(db_session, telegram_fake) -> None:
    _setup(db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}],
           suppression={"respect_maintenance": True})
    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(MaintenanceWindow(start_at=now - dt.timedelta(hours=1), end_at=now + dt.timedelta(hours=1)))
    db_session.flush()
    event = {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}
    workflow.process_event(db_session, event, box=BOX, now=now)
    assert telegram_fake.count == 0


def test_recovery_resolves_alarm(db_session, telegram_fake) -> None:
    probe, system, channel, wf = _setup(db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}])
    workflow.process_event(db_session, {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}, box=BOX)
    db_session.flush()

    # workflow di recovery
    rec = NotificationWorkflow(name="rec-wf", description="", enabled=True, trigger="system_recovered", scope={}, suppression={})
    db_session.add(rec)
    db_session.flush()
    workflow.process_event(db_session, {"type": "system_recovered", "system_id": "wf-sys", "status": "ok", "reachable": True}, box=BOX)
    db_session.flush()
    alarms = db_session.execute(select(Alarm)).scalars().all()
    assert all(a.status == "resolved" for a in alarms)


def test_send_failure_recorded(db_session) -> None:
    original = get_notifier("telegram")
    set_notifier("telegram", _Fake(boom=True))
    try:
        _setup(db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}])
        workflow.process_event(db_session, {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}, box=BOX)
        db_session.flush()
        d = db_session.execute(select(NotificationDelivery)).scalars().all()
        assert d and d[0].status == "failed"
    finally:
        set_notifier("telegram", original)


def test_disabled_channel_no_send(db_session, telegram_fake) -> None:
    _, _, channel, _ = _setup(db_session, conditions=[{"field": "status", "op": "eq", "value": "error"}])
    channel.enabled = False
    db_session.flush()
    workflow.process_event(db_session, {"type": "status_changed", "system_id": "wf-sys", "status": "error", "reachable": True}, box=BOX)
    assert telegram_fake.count == 0


def test_no_matching_workflow(db_session, telegram_fake) -> None:
    workflow.process_event(db_session, {"type": "status_changed", "system_id": "none", "status": "error"}, box=BOX)
    assert telegram_fake.count == 0
