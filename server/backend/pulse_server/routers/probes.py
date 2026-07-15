"""Area Probe (DOCUMENTO_API §1.5)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUser, CurrentUserDep, SessionDep, SettingsDep, client_ip, require_permission
from ..models import EnrollmentToken, MonitoredSystem, Probe
from ..security import generate_opaque_token, hash_token
from ._helpers import clamp_pagination, commit_or_conflict, offset, parse_uuid

router = APIRouter(prefix="/api/v1/probes", tags=["probes"])


def _new_enrollment(session: SessionDep, settings: SettingsDep, probe: Probe) -> tuple[str, dt.datetime]:
    token = generate_opaque_token()
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        seconds=settings.enrollment_token_ttl_seconds
    )
    session.add(EnrollmentToken(probe_id=probe.id, token_hash=hash_token(token), expires_at=expires))
    return token, expires


@router.get("", response_model=schemas.ProbeList)
def list_probes(
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    status: str | None = None,
    _: CurrentUser = Depends(require_permission("probes.read")),
) -> schemas.ProbeList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(Probe)
    count_stmt = select(func.count(Probe.id))
    if status is not None:
        stmt = stmt.where(Probe.status == status)
        count_stmt = count_stmt.where(Probe.status == status)
    if q:
        like = f"%{q}%"
        cond = or_(Probe.name.ilike(like), Probe.description.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(stmt.order_by(Probe.created_at).offset(offset(page, page_size)).limit(page_size))
        .scalars()
        .all()
    )
    return schemas.ProbeList(items=[serializers.probe_out(session, p) for p in rows], total=total)


@router.post("", response_model=schemas.ProbeCreateResponse, status_code=201)
def create_probe(
    body: schemas.ProbeCreate,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("probes.create")),
) -> schemas.ProbeCreateResponse:
    probe = Probe(
        name=body.name,
        description=body.description,
        query_endpoint=body.query_endpoint,
        tags=body.tags,
        enabled=body.enabled,
        status="pending",
    )
    session.add(probe)
    session.flush()
    token, expires = _new_enrollment(session, settings, probe)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="probes.create",
        outcome="success",
        entity_type="probe",
        entity_id=str(probe.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome Probe gia' esistente.")
    session.refresh(probe)
    return schemas.ProbeCreateResponse(
        probe=serializers.probe_out(session, probe),
        enrollment_token=token,
        enrollment_expires_at=expires,
    )


@router.get("/{probe_id}", response_model=schemas.ProbeOut)
def get_probe(
    probe_id: str, session: SessionDep, _: CurrentUser = Depends(require_permission("probes.read"))
) -> schemas.ProbeOut:
    probe = session.get(Probe, parse_uuid(probe_id, what="probe_id"))
    if probe is None:
        raise errors.not_found("Probe inesistente.")
    return serializers.probe_out(session, probe)


@router.put("/{probe_id}", response_model=schemas.ProbeOut)
def update_probe(
    probe_id: str,
    body: schemas.ProbeUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("probes.update")),
) -> schemas.ProbeOut:
    probe = session.get(Probe, parse_uuid(probe_id, what="probe_id"))
    if probe is None:
        raise errors.not_found("Probe inesistente.")
    if body.name is not None:
        probe.name = body.name
    if body.description is not None:
        probe.description = body.description
    if body.query_endpoint is not None:
        probe.query_endpoint = body.query_endpoint
    if body.tags is not None:
        probe.tags = body.tags
    if body.enabled is not None:
        probe.enabled = body.enabled
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="probes.update",
        outcome="success",
        entity_type="probe",
        entity_id=str(probe.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome Probe gia' esistente.")
    session.refresh(probe)
    return serializers.probe_out(session, probe)


@router.delete("/{probe_id}", status_code=204)
def delete_probe(
    probe_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("probes.delete")),
) -> Response:
    probe = session.get(Probe, parse_uuid(probe_id, what="probe_id"))
    if probe is None:
        raise errors.not_found("Probe inesistente.")
    assigned = session.execute(
        select(func.count(MonitoredSystem.id)).where(MonitoredSystem.probe_id == probe.id)
    ).scalar_one()
    if int(assigned) > 0:
        raise errors.conflict("Probe con sistemi assegnati: riassegnare o eliminare prima i sistemi.")
    session.delete(probe)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="probes.delete",
        outcome="success",
        entity_type="probe",
        entity_id=str(probe_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


@router.post("/{probe_id}/rotate-credentials", response_model=schemas.EnrollmentInfo)
def rotate_credentials(
    probe_id: str,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("probes.rotate_key")),
) -> schemas.EnrollmentInfo:
    probe = session.get(Probe, parse_uuid(probe_id, what="probe_id"))
    if probe is None:
        raise errors.not_found("Probe inesistente.")
    # Revoca il token corrente e i token di enrollment pendenti; forza re-enroll.
    probe.token_hash = None
    probe.certificate_fingerprint = None
    probe.status = "pending"
    now = dt.datetime.now(dt.timezone.utc)
    for tok in session.execute(
        select(EnrollmentToken).where(
            EnrollmentToken.probe_id == probe.id, EnrollmentToken.used_at.is_(None)
        )
    ).scalars():
        tok.used_at = now
    token, expires = _new_enrollment(session, settings, probe)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="probes.rotate_key",
        outcome="success",
        entity_type="probe",
        entity_id=str(probe.id),
        ip=client_ip(request),
    )
    session.commit()
    return schemas.EnrollmentInfo(enrollment_token=token, enrollment_expires_at=expires)


@router.get("/{probe_id}/status", response_model=schemas.ProbeStatusOut)
def probe_status(
    probe_id: str, session: SessionDep, _: CurrentUser = Depends(require_permission("probes.read"))
) -> schemas.ProbeStatusOut:
    probe = session.get(Probe, parse_uuid(probe_id, what="probe_id"))
    if probe is None:
        raise errors.not_found("Probe inesistente.")
    return schemas.ProbeStatusOut(
        id=str(probe.id),
        status=probe.status,
        last_seen_at=probe.last_seen_at,
        version=probe.version,
        last_sync_at=probe.last_sync_at,
        last_error=probe.last_error,
    )
