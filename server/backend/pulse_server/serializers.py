"""Conversione modelli ORM -> schemi di risposta (shape esatta del DOCUMENTO_API)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas
from .models import (
    Alarm,
    AuditLog,
    ChannelIdentity,
    Configuration,
    DiscoveredCheck,
    MaintenanceWindow,
    MonitoredSystem,
    NotificationChannel,
    NotificationDelivery,
    NotificationWorkflow,
    Probe,
    Role,
    SystemLog,
    User,
)
from .notifications import mask_config


def systems_count(session: Session, probe_id: uuid.UUID) -> int:
    return int(
        session.execute(
            select(func.count(MonitoredSystem.id)).where(MonitoredSystem.probe_id == probe_id)
        ).scalar_one()
    )


def user_out(user: User) -> schemas.UserOut:
    return schemas.UserOut(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def role_out(role: Role) -> schemas.RoleOut:
    return schemas.RoleOut(
        id=str(role.id),
        name=role.name,
        description=role.description,
        is_builtin=role.is_builtin,
        permissions=sorted(rp.permission_code for rp in role.permissions),
        created_at=role.created_at,
    )


def probe_out(session: Session, probe: Probe) -> schemas.ProbeOut:
    return schemas.ProbeOut(
        id=str(probe.id),
        name=probe.name,
        description=probe.description,
        query_endpoint=probe.query_endpoint,
        tags=list(probe.tags or []),
        enabled=probe.enabled,
        status=probe.status,
        last_seen_at=probe.last_seen_at,
        version=probe.version,
        systems_count=systems_count(session, probe.id),
        created_at=probe.created_at,
    )


def system_out(session: Session, system: MonitoredSystem) -> schemas.SystemOut:
    windows = (
        session.execute(
            select(MaintenanceWindow).where(MaintenanceWindow.system_id == system.id)
        )
        .scalars()
        .all()
    )
    return schemas.SystemOut(
        id=str(system.id),
        system_id=system.system_id,
        system_name=system.system_name,
        heartbeat_url=system.heartbeat_url,
        probe_id=str(system.probe_id),
        poll_interval_seconds=system.poll_interval_seconds,
        timeout_seconds=system.timeout_seconds,
        enabled=system.enabled,
        thresholds=schemas.Thresholds(
            response_ms_warn=system.response_ms_warn,
            response_ms_error=system.response_ms_error,
        ),
        maintenance_windows=[
            schemas.MaintenanceWindowOut(start=w.start_at, end=w.end_at, note=w.note)
            for w in windows
        ],
        created_at=system.created_at,
    )


def channel_out(channel: NotificationChannel) -> schemas.ChannelOut:
    return schemas.ChannelOut(
        id=str(channel.id),
        name=channel.name,
        type=channel.type,
        enabled=channel.enabled,
        inbound_enabled=channel.inbound_enabled,
        config=mask_config(channel.config),
        created_at=channel.created_at,
    )


def workflow_out(wf: NotificationWorkflow) -> schemas.WorkflowOut:
    scope = wf.scope or {}
    supp = wf.suppression or {}
    return schemas.WorkflowOut(
        id=str(wf.id),
        name=wf.name,
        description=wf.description,
        enabled=wf.enabled,
        trigger=wf.trigger,
        scope=schemas.WorkflowScope(
            probe_ids=list(scope.get("probe_ids", [])),
            system_ids=list(scope.get("system_ids", [])),
            check_ids=list(scope.get("check_ids", [])),
        ),
        conditions=[
            schemas.WorkflowConditionIO(field=c.field, op=c.op, value=c.value, group=c.logic_group)
            for c in sorted(wf.conditions, key=lambda x: (x.order_index or 0))
        ],
        suppression=schemas.WorkflowSuppression(
            cooldown_seconds=int(supp.get("cooldown_seconds", 0) or 0),
            dedup_window_seconds=int(supp.get("dedup_window_seconds", 0) or 0),
            active_hours=supp.get("active_hours"),
            respect_maintenance=bool(supp.get("respect_maintenance", True)),
        ),
        actions=[
            schemas.WorkflowActionIO(
                step_order=a.step_order,
                channel_id=str(a.channel_id),
                recipients=list(a.recipients or []),
                template=a.template,
                delay_seconds=a.delay_seconds,
                escalation_condition=a.escalation_condition,
                repeat=a.repeat,
            )
            for a in sorted(wf.actions, key=lambda x: x.step_order)
        ],
        created_at=wf.created_at,
    )


def alarm_out(alarm: Alarm) -> schemas.AlarmOut:
    return schemas.AlarmOut(
        id=str(alarm.id),
        workflow_id=str(alarm.workflow_id) if alarm.workflow_id else None,
        probe_id=str(alarm.probe_id) if alarm.probe_id else None,
        system_id=str(alarm.system_id) if alarm.system_id else None,
        check_id=alarm.check_id,
        status=alarm.status,
        opened_at=alarm.opened_at,
        acknowledged_at=alarm.acknowledged_at,
        acknowledged_by=str(alarm.acknowledged_by) if alarm.acknowledged_by else None,
        resolved_at=alarm.resolved_at,
    )


def delivery_out(d: NotificationDelivery) -> schemas.DeliveryOut:
    return schemas.DeliveryOut(
        id=str(d.id),
        channel_id=str(d.channel_id),
        workflow_id=str(d.workflow_id) if d.workflow_id else None,
        recipient=d.recipient,
        status=d.status,
        error=d.error,
        created_at=d.created_at,
    )


def identity_out(i: ChannelIdentity) -> schemas.ChannelIdentityOut:
    return schemas.ChannelIdentityOut(
        id=str(i.id),
        channel_type=i.channel_type,
        external_id=i.external_id,
        user_id=str(i.user_id),
    )


def audit_out(a: AuditLog) -> schemas.AuditOut:
    return schemas.AuditOut(
        id=str(a.id),
        timestamp=a.timestamp,
        actor_type=a.actor_type,
        actor_id=a.actor_id,
        action=a.action,
        entity_type=a.entity_type,
        entity_id=a.entity_id,
        outcome=a.outcome,
        ip=a.ip,
        details=a.details or {},
    )


def log_out(log: SystemLog) -> schemas.LogOut:
    return schemas.LogOut(
        id=str(log.id),
        timestamp=log.timestamp,
        component=log.component,
        probe_id=str(log.probe_id) if log.probe_id else None,
        level=log.level,
        logger=log.logger,
        message=log.message,
        context=log.context or {},
    )


def config_out(c: Configuration) -> schemas.ConfigItemOut:
    value = "********" if c.sensitive else c.value
    return schemas.ConfigItemOut(
        key=c.key,
        value=value,
        type=c.type,
        sensitive=c.sensitive,
        requires_restart=c.requires_restart,
        description=c.description,
    )


def check_out(c: DiscoveredCheck) -> schemas.CheckOut:
    return schemas.CheckOut(
        check_id=c.check_id,
        check_name=c.check_name,
        last_status=c.last_status,
        last_seen_at=c.last_seen_at,
    )
