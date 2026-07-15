"""Aree Audit (§1.14), Log di sistema (§1.15), Configurazione (§1.16)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUserDep, SessionDep, client_ip, require_permission
from ..models import AuditLog, Configuration, SystemLog
from ._helpers import clamp_pagination, offset, parse_uuid

audit_router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
logs_router = APIRouter(prefix="/api/v1/logs", tags=["logs"])
config_router = APIRouter(prefix="/api/v1/config", tags=["config"])


def _parse_iso(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise errors.bad_request(f"Timestamp ISO-8601 non valido: {value}")


# ============================ Audit ========================================


@audit_router.get("", response_model=schemas.AuditList)
def list_audit(
    session: SessionDep,
    actor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    outcome: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUserDep = Depends(require_permission("audit.read")),
) -> schemas.AuditList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    conds = []
    if actor is not None:
        conds.append(AuditLog.actor_id == actor)
    if action is not None:
        conds.append(AuditLog.action == action)
    if entity_type is not None:
        conds.append(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        conds.append(AuditLog.entity_id == entity_id)
    if outcome is not None:
        conds.append(AuditLog.outcome == outcome)
    if from_ is not None:
        conds.append(AuditLog.timestamp >= _parse_iso(from_))
    if to is not None:
        conds.append(AuditLog.timestamp <= _parse_iso(to))
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(
            stmt.order_by(AuditLog.timestamp.desc()).offset(offset(page, page_size)).limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.AuditList(items=[serializers.audit_out(a) for a in rows], total=total)


@audit_router.get("/{audit_id}", response_model=schemas.AuditOut)
def get_audit(
    audit_id: str,
    session: SessionDep,
    _: CurrentUserDep = Depends(require_permission("audit.read")),
) -> schemas.AuditOut:
    entry = session.get(AuditLog, parse_uuid(audit_id, what="audit_id"))
    if entry is None:
        raise errors.not_found("Voce di audit inesistente.")
    return serializers.audit_out(entry)


# ============================ Log di sistema ===============================


@logs_router.get("", response_model=schemas.LogList)
def list_logs(
    session: SessionDep,
    component: str | None = None,
    probe_id: str | None = None,
    level: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUserDep = Depends(require_permission("syslog.read")),
) -> schemas.LogList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(SystemLog)
    count_stmt = select(func.count(SystemLog.id))
    conds = []
    if component is not None:
        conds.append(SystemLog.component == component)
    if probe_id is not None:
        conds.append(SystemLog.probe_id == parse_uuid(probe_id, what="probe_id"))
    if level is not None:
        conds.append(SystemLog.level == level)
    if from_ is not None:
        conds.append(SystemLog.timestamp >= _parse_iso(from_))
    if to is not None:
        conds.append(SystemLog.timestamp <= _parse_iso(to))
    if q:
        conds.append(SystemLog.message.ilike(f"%{q}%"))
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(
            stmt.order_by(SystemLog.timestamp.desc()).offset(offset(page, page_size)).limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.LogList(items=[serializers.log_out(log) for log in rows], total=total)


# ============================ Configurazione ===============================


@config_router.get("", response_model=schemas.ConfigList)
def list_config(
    session: SessionDep,
    _: CurrentUserDep = Depends(require_permission("config.read")),
) -> schemas.ConfigList:
    rows = session.execute(select(Configuration).order_by(Configuration.key)).scalars().all()
    return schemas.ConfigList(items=[serializers.config_out(c) for c in rows])


@config_router.get("/{key}", response_model=schemas.ConfigItemOut)
def get_config_item(
    key: str,
    session: SessionDep,
    _: CurrentUserDep = Depends(require_permission("config.read")),
) -> schemas.ConfigItemOut:
    item = session.get(Configuration, key)
    if item is None:
        raise errors.not_found("Parametro di configurazione inesistente.")
    return serializers.config_out(item)


@config_router.put("", response_model=schemas.ConfigUpdateResponse)
def update_config(
    body: schemas.ConfigUpdateRequest,
    session: SessionDep,
    request: Request,
    actor: CurrentUserDep = Depends(require_permission("config.update")),
) -> schemas.ConfigUpdateResponse:
    updated: list[str] = []
    requires_restart: list[str] = []
    for change in body.items:
        item = session.get(Configuration, change.key)
        if item is None:
            raise errors.unprocessable(f"Parametro inesistente: {change.key}")
        item.value = change.value
        item.updated_by = actor.id
        updated.append(item.key)
        if item.requires_restart:
            requires_restart.append(item.key)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="config.update",
        outcome="success",
        entity_type="configuration",
        entity_id=None,
        ip=client_ip(request),
        details={"keys": updated},
    )
    session.commit()
    return schemas.ConfigUpdateResponse(updated=updated, requires_restart=requires_restart)
