"""Area Sistemi monitorati (DOCUMENTO_API §1.6) e Check (§1.7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUserDep, SessionDep, client_ip, require_permission
from ..models import DiscoveredCheck, MaintenanceWindow, MonitoredSystem, Probe
from ._helpers import clamp_pagination, commit_or_conflict, offset, parse_uuid

router = APIRouter(prefix="/api/v1/systems", tags=["systems"])
checks_router = APIRouter(prefix="/api/v1/checks", tags=["checks"])


def _require_probe(session: SessionDep, probe_id: str) -> Probe:
    try:
        pid = parse_uuid(probe_id, what="probe_id")
    except errors.ApiError:
        raise errors.unprocessable("Probe inesistente.")
    probe = session.get(Probe, pid)
    if probe is None:
        raise errors.unprocessable("Probe inesistente.")
    return probe


def _replace_windows(session: SessionDep, system: MonitoredSystem, windows: list[schemas.MaintenanceWindowIn]) -> None:
    session.execute(
        MaintenanceWindow.__table__.delete().where(MaintenanceWindow.system_id == system.id)
    )
    for win in windows:
        if win.end <= win.start:
            raise errors.unprocessable("Finestra di manutenzione con intervallo non valido.")
        session.add(
            MaintenanceWindow(
                system_id=system.id,
                probe_id=system.probe_id,
                start_at=win.start,
                end_at=win.end,
                note=win.note,
            )
        )


@router.get("", response_model=schemas.SystemList)
def list_systems(
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    probe_id: str | None = None,
    enabled: bool | None = None,
    _: CurrentUserDep = Depends(require_permission("systems.read")),
) -> schemas.SystemList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(MonitoredSystem)
    count_stmt = select(func.count(MonitoredSystem.id))
    if probe_id is not None:
        pid = parse_uuid(probe_id, what="probe_id")
        stmt = stmt.where(MonitoredSystem.probe_id == pid)
        count_stmt = count_stmt.where(MonitoredSystem.probe_id == pid)
    if enabled is not None:
        stmt = stmt.where(MonitoredSystem.enabled.is_(enabled))
        count_stmt = count_stmt.where(MonitoredSystem.enabled.is_(enabled))
    if q:
        like = f"%{q}%"
        cond = or_(MonitoredSystem.system_id.ilike(like), MonitoredSystem.system_name.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(
            stmt.order_by(MonitoredSystem.created_at).offset(offset(page, page_size)).limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.SystemList(items=[serializers.system_out(session, s) for s in rows], total=total)


@router.post("", response_model=schemas.SystemOut, status_code=201)
def create_system(
    body: schemas.SystemCreate,
    session: SessionDep,
    request: Request,
    actor: CurrentUserDep = Depends(require_permission("systems.create")),
) -> schemas.SystemOut:
    probe = _require_probe(session, body.probe_id)
    th = body.thresholds or schemas.Thresholds()
    system = MonitoredSystem(
        system_id=body.system_id,
        system_name=body.system_name,
        heartbeat_url=body.heartbeat_url,
        probe_id=probe.id,
        poll_interval_seconds=body.poll_interval_seconds,
        timeout_seconds=body.timeout_seconds,
        enabled=body.enabled,
        response_ms_warn=th.response_ms_warn,
        response_ms_error=th.response_ms_error,
    )
    session.add(system)
    session.flush()
    if body.maintenance_windows:
        _replace_windows(session, system, body.maintenance_windows)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="systems.create",
        outcome="success",
        entity_type="system",
        entity_id=str(system.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="system_id gia' esistente.")
    session.refresh(system)
    return serializers.system_out(session, system)


@router.get("/{system_id}", response_model=schemas.SystemOut)
def get_system(
    system_id: str, session: SessionDep, _: CurrentUserDep = Depends(require_permission("systems.read"))
) -> schemas.SystemOut:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    return serializers.system_out(session, system)


@router.put("/{system_id}", response_model=schemas.SystemOut)
def update_system(
    system_id: str,
    body: schemas.SystemUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUserDep = Depends(require_permission("systems.update")),
) -> schemas.SystemOut:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    if body.probe_id is not None:
        system.probe_id = _require_probe(session, body.probe_id).id
    if body.system_name is not None:
        system.system_name = body.system_name
    if body.heartbeat_url is not None:
        system.heartbeat_url = body.heartbeat_url
    if body.poll_interval_seconds is not None:
        system.poll_interval_seconds = body.poll_interval_seconds
    if body.timeout_seconds is not None:
        system.timeout_seconds = body.timeout_seconds
    if body.enabled is not None:
        system.enabled = body.enabled
    if body.thresholds is not None:
        system.response_ms_warn = body.thresholds.response_ms_warn
        system.response_ms_error = body.thresholds.response_ms_error
    if body.maintenance_windows is not None:
        _replace_windows(session, system, body.maintenance_windows)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="systems.update",
        outcome="success",
        entity_type="system",
        entity_id=str(system.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="system_id gia' esistente.")
    session.refresh(system)
    return serializers.system_out(session, system)


@router.delete("/{system_id}", status_code=204)
def delete_system(
    system_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUserDep = Depends(require_permission("systems.delete")),
) -> Response:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    session.delete(system)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="systems.delete",
        outcome="success",
        entity_type="system",
        entity_id=str(system_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


@router.get("/{system_id}/checks", response_model=schemas.SystemChecksList)
def system_checks(
    system_id: str,
    session: SessionDep,
    _: CurrentUserDep = Depends(require_permission("checks.read")),
) -> schemas.SystemChecksList:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    rows = (
        session.execute(select(DiscoveredCheck).where(DiscoveredCheck.system_id == system.id))
        .scalars()
        .all()
    )
    return schemas.SystemChecksList(items=[serializers.check_out(c) for c in rows])


@checks_router.get("", response_model=schemas.GlobalChecksList)
def list_checks(
    session: SessionDep,
    system_id: str | None = None,
    probe_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUserDep = Depends(require_permission("checks.read")),
) -> schemas.GlobalChecksList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(DiscoveredCheck, MonitoredSystem.system_id).join(
        MonitoredSystem, MonitoredSystem.id == DiscoveredCheck.system_id
    )
    count_stmt = select(func.count(DiscoveredCheck.id)).join(
        MonitoredSystem, MonitoredSystem.id == DiscoveredCheck.system_id
    )
    if system_id is not None:
        stmt = stmt.where(MonitoredSystem.system_id == system_id)
        count_stmt = count_stmt.where(MonitoredSystem.system_id == system_id)
    if probe_id is not None:
        pid = parse_uuid(probe_id, what="probe_id")
        stmt = stmt.where(DiscoveredCheck.probe_id == pid)
        count_stmt = count_stmt.where(DiscoveredCheck.probe_id == pid)
    total = int(session.execute(count_stmt).scalar_one())
    rows = session.execute(stmt.offset(offset(page, page_size)).limit(page_size)).all()
    items = [
        schemas.GlobalCheckOut(
            system_id=business_system_id,
            check_id=c.check_id,
            check_name=c.check_name,
            probe_id=str(c.probe_id) if c.probe_id else None,
            last_status=c.last_status,
            last_seen_at=c.last_seen_at,
        )
        for c, business_system_id in rows
    ]
    return schemas.GlobalChecksList(items=items, total=total)
