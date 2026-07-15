"""Motore di valutazione workflow notifiche (07_workflow_notifiche.md).

Responsabilita':
 - match del trigger, dell'ambito (scope) e delle condizioni (AND nel gruppo, OR
   tra gruppi);
 - controlli di soppressione (finestre di manutenzione, orari attivi, cooldown,
   deduplica);
 - apertura/aggiornamento/risoluzione allarmi;
 - invio notifiche (primo step) con registrazione delle delivery.

Le funzioni "pure" (match/condizioni) sono separate da quelle che toccano il DB
per massimizzare la testabilita'.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import (
    Alarm,
    MaintenanceWindow,
    MonitoredSystem,
    NotificationChannel,
    NotificationDelivery,
    NotificationWorkflow,
)
from .notifications import decrypt_config, get_notifier, render_template
from .security import SecretBox

# Trigger che aprono/mantengono un allarme; recovery lo risolve.
_ALARM_TRIGGERS = {
    "status_changed",
    "status_is",
    "system_unreachable",
    "response_time_exceeded",
    "sustained_state",
    "probe_offline",
}
_RECOVERY_TRIGGERS = {"system_recovered", "probe_online"}


@dataclass
class WorkflowMatch:
    matched: bool
    planned_actions: list[dict[str, Any]] = field(default_factory=list)
    suppressed_by: str | None = None


def _event_field(event: dict[str, Any], name: str) -> Any:
    """Estrae un campo dell'evento, incluse le metriche in details.metrics.*"""
    if name in event:
        return event[name]
    if name.startswith("details.metrics."):
        raw = event.get("details")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                return None
        elif isinstance(raw, dict):
            parsed = raw
        else:
            return None
        metrics = parsed.get("metrics", {}) if isinstance(parsed, dict) else {}
        return metrics.get(name.split("details.metrics.", 1)[1])
    return None


def eval_condition(op: str, left: Any, right: Any) -> bool:
    """Valuta un singolo operatore di condizione."""
    if op == "eq":
        return bool(left == right)
    if op == "neq":
        return bool(left != right)
    if op in ("gt", "gte", "lt", "lte"):
        if left is None or right is None:
            return False
        try:
            lf, rf = float(left), float(right)
        except (ValueError, TypeError):
            return False
        return {"gt": lf > rf, "gte": lf >= rf, "lt": lf < rf, "lte": lf <= rf}[op]
    if op == "in":
        return isinstance(right, (list, tuple)) and left in right
    if op == "not_in":
        return isinstance(right, (list, tuple)) and left not in right
    if op == "contains":
        return right is not None and left is not None and str(right) in str(left)
    if op == "matches":
        if left is None or right is None:
            return False
        try:
            return re.search(str(right), str(left)) is not None
        except re.error:
            return False
    return False  # pragma: no cover - op validato dallo schema DB (CHECK)


def conditions_match(event: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    """AND all'interno di un gruppo, OR tra gruppi. Nessuna condizione = match."""
    if not conditions:
        return True
    groups: dict[str, list[dict[str, Any]]] = {}
    for cond in conditions:
        gkey = cond.get("group") or cond.get("logic_group") or "_default"
        groups.setdefault(gkey, []).append(cond)
    for conds in groups.values():
        if all(eval_condition(c["op"], _event_field(event, c["field"]), c.get("value")) for c in conds):
            return True
    return False


def scope_match(event: dict[str, Any], scope: dict[str, Any] | None) -> bool:
    """Empty list = tutti. Confronto sui valori business dell'evento."""
    if not scope:
        return True
    for key, ev_key in (("probe_ids", "probe_id"), ("system_ids", "system_id"), ("check_ids", "check_id")):
        wanted = scope.get(key) or []
        if wanted:
            value = event.get(ev_key)
            if value is None or str(value) not in [str(w) for w in wanted]:
                return False
    return True


def _within_active_hours(active_hours: dict[str, Any] | None, now: dt.datetime) -> bool:
    """active_hours: { "days": [0..6], "start": "HH:MM", "end": "HH:MM" }."""
    if not active_hours:
        return True
    days = active_hours.get("days")
    if days is not None and now.weekday() not in days:
        return False
    start = active_hours.get("start")
    end = active_hours.get("end")
    if start and end:
        cur = now.strftime("%H:%M")
        return bool(start <= cur <= end)
    return True


def evaluate(
    event: dict[str, Any],
    workflow: dict[str, Any],
    *,
    now: dt.datetime,
    maintenance_active: bool = False,
) -> WorkflowMatch:
    """Valutazione pura (senza DB) di trigger/scope/condizioni/soppressione base."""
    if workflow.get("trigger") != event.get("type") and workflow.get("trigger") != event.get("trigger"):
        return WorkflowMatch(matched=False)
    if not scope_match(event, workflow.get("scope")):
        return WorkflowMatch(matched=False)
    if not conditions_match(event, workflow.get("conditions", [])):
        return WorkflowMatch(matched=False)

    suppression = workflow.get("suppression") or {}
    if suppression.get("respect_maintenance", True) and maintenance_active:
        return WorkflowMatch(matched=True, suppressed_by="maintenance_window")
    if not _within_active_hours(suppression.get("active_hours"), now):
        return WorkflowMatch(matched=True, suppressed_by="active_hours")

    return WorkflowMatch(matched=True, planned_actions=list(workflow.get("actions", [])))


# --- Serializzazione workflow ORM -> dict per la valutazione ----------------


def workflow_to_dict(wf: NotificationWorkflow) -> dict[str, Any]:
    return {
        "id": str(wf.id),
        "name": wf.name,
        "enabled": wf.enabled,
        "trigger": wf.trigger,
        "scope": wf.scope or {},
        "suppression": wf.suppression or {},
        "conditions": [
            {"field": c.field, "op": c.op, "value": c.value, "group": c.logic_group}
            for c in sorted(wf.conditions, key=lambda x: (x.order_index or 0))
        ],
        "actions": [
            {
                "step_order": a.step_order,
                "channel_id": str(a.channel_id),
                "recipients": a.recipients,
                "template": a.template,
                "delay_seconds": a.delay_seconds,
                "escalation_condition": a.escalation_condition,
                "repeat": a.repeat,
            }
            for a in sorted(wf.actions, key=lambda x: x.step_order)
        ],
    }


# --- Elaborazione con effetti (DB) ------------------------------------------


def _maintenance_active(session: Session, event: dict[str, Any], now: dt.datetime) -> bool:
    sys_uuid: uuid.UUID | None = None
    system = session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == str(event.get("system_id")))
    ).scalar_one_or_none()
    if system is not None:
        sys_uuid = system.id
    stmt = select(MaintenanceWindow).where(
        MaintenanceWindow.start_at <= now, MaintenanceWindow.end_at >= now
    )
    for win in session.execute(stmt).scalars().all():
        if win.system_id is None and win.probe_id is None:
            return True
        if sys_uuid is not None and win.system_id == sys_uuid:
            return True
    return False


def _dedup_key(workflow_id: str, event: dict[str, Any]) -> str:
    return f"{event.get('probe_id')}:{event.get('system_id')}:{event.get('check_id')}:{workflow_id}"


def _send_first_step(
    session: Session,
    *,
    box: SecretBox,
    workflow: NotificationWorkflow,
    actions: list[dict[str, Any]],
    event: dict[str, Any],
    alarm_id: uuid.UUID | None,
) -> None:
    if not actions:
        return
    step = actions[0]
    channel = session.get(NotificationChannel, uuid.UUID(str(step["channel_id"])))
    if channel is None or not channel.enabled:
        return
    context = {
        "system_name": event.get("system_id"),
        "status": event.get("status"),
        "response_ms": event.get("response_ms"),
        "message": event.get("message"),
        "probe": event.get("probe_id"),
        "timestamp": event.get("timestamp"),
    }
    body = render_template(step["template"], context)
    plain_cfg = decrypt_config(box, channel.config)
    notifier = get_notifier(channel.type)
    for recipient in step.get("recipients", []):
        status = "sent"
        error: str | None = None
        try:
            result = notifier.send(plain_cfg, recipient, body)
            if not result.delivered:
                status, error = "failed", result.detail
        except Exception as exc:  # noqa: BLE001 - errori provider registrati come failed
            status, error = "failed", str(exc)
        session.add(
            NotificationDelivery(
                workflow_id=workflow.id,
                alarm_id=alarm_id,
                channel_id=channel.id,
                recipient=str(recipient),
                status=status,
                error=error,
            )
        )


def process_event(
    session: Session,
    event: dict[str, Any],
    *,
    box: SecretBox,
    now: dt.datetime | None = None,
) -> None:
    """Elabora un singolo evento contro tutti i workflow abilitati."""
    now = now or dt.datetime.now(dt.timezone.utc)
    etype = event.get("type") or event.get("trigger")

    # Auto-risoluzione su recovery.
    if etype in _RECOVERY_TRIGGERS:
        _resolve_alarms(session, event, now)

    maint = _maintenance_active(session, event, now)
    workflows = (
        session.execute(
            select(NotificationWorkflow).where(
                NotificationWorkflow.enabled.is_(True), NotificationWorkflow.trigger == etype
            )
        )
        .scalars()
        .all()
    )
    for wf in workflows:
        wf_dict = workflow_to_dict(wf)
        match = evaluate(event, wf_dict, now=now, maintenance_active=maint)
        if not match.matched:
            continue
        if match.suppressed_by is not None:
            audit.write_audit(
                session,
                actor_type="system",
                actor_id="workflow-engine",
                action="workflow.suppressed",
                outcome="success",
                entity_type="workflow",
                entity_id=str(wf.id),
                details={"reason": match.suppressed_by, "event": etype},
            )
            continue

        dedup_key = _dedup_key(str(wf.id), event)
        suppression = wf.suppression or {}
        if _is_suppressed_by_state(session, dedup_key, suppression, now):
            audit.write_audit(
                session,
                actor_type="system",
                actor_id="workflow-engine",
                action="workflow.suppressed",
                outcome="success",
                entity_type="workflow",
                entity_id=str(wf.id),
                details={"reason": "cooldown_or_dedup", "event": etype},
            )
            continue

        alarm_id: uuid.UUID | None = None
        if etype in _ALARM_TRIGGERS:
            alarm_id = _open_alarm(session, wf, event, dedup_key, now)
        _send_first_step(
            session,
            box=box,
            workflow=wf,
            actions=match.planned_actions,
            event=event,
            alarm_id=alarm_id,
        )
        audit.write_audit(
            session,
            actor_type="system",
            actor_id="workflow-engine",
            action="workflow.triggered",
            outcome="success",
            entity_type="workflow",
            entity_id=str(wf.id),
            details={"event": etype, "system_id": event.get("system_id")},
        )


def _is_suppressed_by_state(
    session: Session, dedup_key: str, suppression: dict[str, Any], now: dt.datetime
) -> bool:
    cooldown = int(suppression.get("cooldown_seconds", 0) or 0)
    if cooldown <= 0:
        return False
    threshold = now - dt.timedelta(seconds=cooldown)
    recent = session.execute(
        select(Alarm).where(Alarm.dedup_key == dedup_key, Alarm.opened_at >= threshold)
    ).first()
    return recent is not None


def _open_alarm(
    session: Session,
    wf: NotificationWorkflow,
    event: dict[str, Any],
    dedup_key: str,
    now: dt.datetime,
) -> uuid.UUID:
    existing = session.execute(
        select(Alarm).where(Alarm.dedup_key == dedup_key, Alarm.status.in_(["active", "acknowledged"]))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    system = session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == str(event.get("system_id")))
    ).scalar_one_or_none()
    alarm = Alarm(
        workflow_id=wf.id,
        probe_id=None,
        system_id=system.id if system else None,
        check_id=event.get("check_id"),
        dedup_key=dedup_key,
        status="active",
        current_step=0,
        opened_at=now,
    )
    session.add(alarm)
    session.flush()
    return alarm.id


def _resolve_alarms(session: Session, event: dict[str, Any], now: dt.datetime) -> None:
    system = session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == str(event.get("system_id")))
    ).scalar_one_or_none()
    if system is None:
        return
    open_alarms = session.execute(
        select(Alarm).where(Alarm.system_id == system.id, Alarm.status.in_(["active", "acknowledged"]))
    ).scalars().all()
    for alarm in open_alarms:
        alarm.status = "resolved"
        alarm.resolved_at = now
