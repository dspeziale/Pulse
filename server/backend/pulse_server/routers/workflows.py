"""Area Workflow notifiche (DOCUMENTO_API §1.11) e Allarmi (§1.12)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUser, SessionDep, client_ip, require_permission
from ..models import (
    Alarm,
    NotificationChannel,
    NotificationWorkflow,
    WorkflowAction,
    WorkflowCondition,
)
from ..workflow import evaluate, workflow_to_dict
from ._helpers import clamp_pagination, commit_or_conflict, flush_or_conflict, offset, parse_uuid

router = APIRouter(prefix="/api/v1/notification-workflows", tags=["workflows"])
alarms_router = APIRouter(prefix="/api/v1/alarms", tags=["workflows"])

_VALID_TRIGGERS = {
    "status_changed",
    "status_is",
    "system_unreachable",
    "system_recovered",
    "response_time_exceeded",
    "sustained_state",
    "probe_offline",
    "probe_online",
}


def _validate_channels(session: SessionDep, actions: list[schemas.WorkflowActionIO]) -> None:
    for action in actions:
        cid = parse_uuid(action.channel_id, what="channel_id")
        if session.get(NotificationChannel, cid) is None:
            raise errors.unprocessable(f"Canale inesistente: {action.channel_id}")


def _validate_trigger(trigger: str) -> None:
    if trigger not in _VALID_TRIGGERS:
        raise errors.unprocessable(f"Trigger non valido: {trigger}")


def _replace_conditions(
    session: SessionDep, wf: NotificationWorkflow, conditions: list[schemas.WorkflowConditionIO]
) -> None:
    session.execute(
        delete(WorkflowCondition).where(WorkflowCondition.workflow_id == wf.id)
    )
    for idx, cond in enumerate(conditions):
        session.add(
            WorkflowCondition(
                workflow_id=wf.id,
                field=cond.field,
                op=cond.op,
                value=cond.value,
                logic_group=cond.group,
                order_index=idx,
            )
        )


def _replace_actions(
    session: SessionDep, wf: NotificationWorkflow, actions: list[schemas.WorkflowActionIO]
) -> None:
    session.execute(delete(WorkflowAction).where(WorkflowAction.workflow_id == wf.id))
    for action in actions:
        session.add(
            WorkflowAction(
                workflow_id=wf.id,
                step_order=action.step_order,
                channel_id=parse_uuid(action.channel_id, what="channel_id"),
                recipients=action.recipients,
                template=action.template,
                delay_seconds=action.delay_seconds,
                escalation_condition=action.escalation_condition,
                repeat=action.repeat,
            )
        )


@router.get("", response_model=schemas.WorkflowList)
def list_workflows(
    session: SessionDep,
    enabled: bool | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission("workflows.read")),
) -> schemas.WorkflowList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(NotificationWorkflow)
    count_stmt = select(func.count(NotificationWorkflow.id))
    if enabled is not None:
        stmt = stmt.where(NotificationWorkflow.enabled.is_(enabled))
        count_stmt = count_stmt.where(NotificationWorkflow.enabled.is_(enabled))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(NotificationWorkflow.name.ilike(like))
        count_stmt = count_stmt.where(NotificationWorkflow.name.ilike(like))
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(
            stmt.order_by(NotificationWorkflow.created_at)
            .offset(offset(page, page_size))
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.WorkflowList(items=[serializers.workflow_out(w) for w in rows], total=total)


@router.post("", response_model=schemas.WorkflowOut, status_code=201)
def create_workflow(
    body: schemas.WorkflowCreate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("workflows.create")),
) -> schemas.WorkflowOut:
    _validate_trigger(body.trigger)
    _validate_channels(session, body.actions)
    wf = NotificationWorkflow(
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        trigger=body.trigger,
        scope=body.scope.model_dump(),
        suppression=body.suppression.model_dump(),
        created_by=actor.id,
    )
    session.add(wf)
    flush_or_conflict(session, message="Nome workflow gia' esistente.")
    _replace_conditions(session, wf, body.conditions)
    _replace_actions(session, wf, body.actions)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="workflows.create",
        outcome="success",
        entity_type="notification_workflow",
        entity_id=str(wf.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome workflow gia' esistente.")
    session.refresh(wf)
    return serializers.workflow_out(wf)


@router.get("/{workflow_id}", response_model=schemas.WorkflowOut)
def get_workflow(
    workflow_id: str,
    session: SessionDep,
    _: CurrentUser = Depends(require_permission("workflows.read")),
) -> schemas.WorkflowOut:
    wf = session.get(NotificationWorkflow, parse_uuid(workflow_id, what="workflow_id"))
    if wf is None:
        raise errors.not_found("Workflow inesistente.")
    return serializers.workflow_out(wf)


@router.put("/{workflow_id}", response_model=schemas.WorkflowOut)
def update_workflow(
    workflow_id: str,
    body: schemas.WorkflowUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("workflows.update")),
) -> schemas.WorkflowOut:
    wf = session.get(NotificationWorkflow, parse_uuid(workflow_id, what="workflow_id"))
    if wf is None:
        raise errors.not_found("Workflow inesistente.")
    if body.trigger is not None:
        _validate_trigger(body.trigger)
        wf.trigger = body.trigger
    if body.actions is not None:
        _validate_channels(session, body.actions)
    if body.name is not None:
        wf.name = body.name
    if body.description is not None:
        wf.description = body.description
    if body.enabled is not None:
        wf.enabled = body.enabled
    if body.scope is not None:
        wf.scope = body.scope.model_dump()
    if body.suppression is not None:
        wf.suppression = body.suppression.model_dump()
    if body.conditions is not None:
        _replace_conditions(session, wf, body.conditions)
    if body.actions is not None:
        _replace_actions(session, wf, body.actions)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="workflows.update",
        outcome="success",
        entity_type="notification_workflow",
        entity_id=str(wf.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome workflow gia' esistente.")
    session.refresh(wf)
    return serializers.workflow_out(wf)


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(
    workflow_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("workflows.delete")),
) -> Response:
    wf = session.get(NotificationWorkflow, parse_uuid(workflow_id, what="workflow_id"))
    if wf is None:
        raise errors.not_found("Workflow inesistente.")
    session.delete(wf)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="workflows.delete",
        outcome="success",
        entity_type="notification_workflow",
        entity_id=str(workflow_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


@router.put("/{workflow_id}/enabled", response_model=schemas.WorkflowOut)
def set_enabled(
    workflow_id: str,
    body: schemas.WorkflowEnabledRequest,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("workflows.update")),
) -> schemas.WorkflowOut:
    wf = session.get(NotificationWorkflow, parse_uuid(workflow_id, what="workflow_id"))
    if wf is None:
        raise errors.not_found("Workflow inesistente.")
    wf.enabled = body.enabled
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="workflows.update",
        outcome="success",
        entity_type="notification_workflow",
        entity_id=str(wf.id),
        ip=client_ip(request),
        details={"enabled": body.enabled},
    )
    session.commit()
    session.refresh(wf)
    return serializers.workflow_out(wf)


@router.post("/{workflow_id}/simulate", response_model=schemas.SimulateResponse)
def simulate_workflow(
    workflow_id: str,
    body: schemas.SimulateRequest,
    session: SessionDep,
    _: CurrentUser = Depends(require_permission("workflows.update")),
) -> schemas.SimulateResponse:
    wf = session.get(NotificationWorkflow, parse_uuid(workflow_id, what="workflow_id"))
    if wf is None:
        raise errors.not_found("Workflow inesistente.")
    now = dt.datetime.now(dt.timezone.utc)
    match = evaluate(body.event, workflow_to_dict(wf), now=now, maintenance_active=False)
    return schemas.SimulateResponse(
        matched=match.matched,
        planned_actions=list(match.planned_actions),
        suppressed_by=match.suppressed_by,
    )


# ============================ Allarmi (§1.12) ==============================


@alarms_router.get("", response_model=schemas.AlarmList)
def list_alarms(
    session: SessionDep,
    status: str | None = None,
    system_id: str | None = None,
    probe_id: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission("workflows.read")),
) -> schemas.AlarmList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(Alarm)
    count_stmt = select(func.count(Alarm.id))
    if status is not None:
        stmt = stmt.where(Alarm.status == status)
        count_stmt = count_stmt.where(Alarm.status == status)
    if system_id is not None:
        sid = parse_uuid(system_id, what="system_id")
        stmt = stmt.where(Alarm.system_id == sid)
        count_stmt = count_stmt.where(Alarm.system_id == sid)
    if probe_id is not None:
        pid = parse_uuid(probe_id, what="probe_id")
        stmt = stmt.where(Alarm.probe_id == pid)
        count_stmt = count_stmt.where(Alarm.probe_id == pid)
    if from_ is not None:
        stmt = stmt.where(Alarm.opened_at >= _parse_iso(from_))
        count_stmt = count_stmt.where(Alarm.opened_at >= _parse_iso(from_))
    if to is not None:
        stmt = stmt.where(Alarm.opened_at <= _parse_iso(to))
        count_stmt = count_stmt.where(Alarm.opened_at <= _parse_iso(to))
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(
            stmt.order_by(Alarm.opened_at.desc()).offset(offset(page, page_size)).limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.AlarmList(items=[serializers.alarm_out(a) for a in rows], total=total)


@alarms_router.post("/{alarm_id}/ack", response_model=schemas.AlarmOut)
def ack_alarm(
    alarm_id: str,
    body: schemas.AckRequest,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("commands.execute")),
) -> schemas.AlarmOut:
    alarm = session.get(Alarm, parse_uuid(alarm_id, what="alarm_id"))
    if alarm is None:
        raise errors.not_found("Allarme inesistente.")
    if alarm.status == "resolved":
        raise errors.conflict("Allarme gia' risolto.")
    alarm.status = "acknowledged"
    alarm.acknowledged_at = dt.datetime.now(dt.timezone.utc)
    alarm.acknowledged_by = actor.id
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="alarms.ack",
        outcome="success",
        entity_type="alarm",
        entity_id=str(alarm.id),
        ip=client_ip(request),
        details={"note": body.note} if body.note else None,
    )
    session.commit()
    session.refresh(alarm)
    return serializers.alarm_out(alarm)


def _parse_iso(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise errors.bad_request(f"Timestamp ISO-8601 non valido: {value}")
