"""Area Ruoli (DOCUMENTO_API §1.3) e Permessi (§1.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUser, SessionDep, client_ip, require_permission
from ..models import Permission, Role, RolePermission, UserRole
from ._helpers import clamp_pagination, commit_or_conflict, flush_or_conflict, offset, parse_uuid

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])
perm_router = APIRouter(prefix="/api/v1/permissions", tags=["permissions"])


def _validate_permission_codes(session: SessionDep, codes: list[str]) -> None:
    if not codes:
        return
    existing = {
        row[0]
        for row in session.execute(
            select(Permission.code).where(Permission.code.in_(codes))
        ).all()
    }
    missing = [c for c in codes if c not in existing]
    if missing:
        raise errors.unprocessable("Codici permesso inesistenti.", {"missing": missing})


@router.get("", response_model=schemas.RoleList)
def list_roles(
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    _: CurrentUser = Depends(require_permission("roles.read")),
) -> schemas.RoleList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(Role)
    count_stmt = select(func.count(Role.id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Role.name.ilike(like))
        count_stmt = count_stmt.where(Role.name.ilike(like))
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(stmt.order_by(Role.created_at).offset(offset(page, page_size)).limit(page_size))
        .scalars()
        .all()
    )
    return schemas.RoleList(items=[serializers.role_out(r) for r in rows], total=total)


@router.post("", response_model=schemas.RoleOut, status_code=201)
def create_role(
    body: schemas.RoleCreate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("roles.create")),
) -> schemas.RoleOut:
    _validate_permission_codes(session, body.permission_codes)
    role = Role(name=body.name, description=body.description, is_builtin=False)
    session.add(role)
    flush_or_conflict(session, message="Nome ruolo gia' esistente.")
    for code in body.permission_codes:
        session.add(RolePermission(role_id=role.id, permission_code=code))
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="roles.create",
        outcome="success",
        entity_type="role",
        entity_id=str(role.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome ruolo gia' esistente.")
    session.refresh(role)
    return serializers.role_out(role)


@router.get("/{role_id}", response_model=schemas.RoleOut)
def get_role(
    role_id: str, session: SessionDep, _: CurrentUser = Depends(require_permission("roles.read"))
) -> schemas.RoleOut:
    role = session.get(Role, parse_uuid(role_id, what="role_id"))
    if role is None:
        raise errors.not_found("Ruolo inesistente.")
    return serializers.role_out(role)


@router.put("/{role_id}", response_model=schemas.RoleOut)
def update_role(
    role_id: str,
    body: schemas.RoleUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("roles.update")),
) -> schemas.RoleOut:
    role = session.get(Role, parse_uuid(role_id, what="role_id"))
    if role is None:
        raise errors.not_found("Ruolo inesistente.")
    # DOCUMENTO_API §1.3: PUT su ruolo predefinito -> 409. Coerente con RB-02
    # ("struttura bloccata") e con lo schema (i builtin non sono modificabili via
    # API, inclusa la sola description). Il trigger DB protegge name/is_builtin;
    # il backend estende il blocco a QUALSIASI modifica dei builtin.
    if role.is_builtin:
        raise errors.conflict("Un ruolo predefinito non e' modificabile.")
    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="roles.update",
        outcome="success",
        entity_type="role",
        entity_id=str(role.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome ruolo gia' esistente.")
    session.refresh(role)
    return serializers.role_out(role)


@router.delete("/{role_id}", status_code=204)
def delete_role(
    role_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("roles.delete")),
) -> Response:
    role = session.get(Role, parse_uuid(role_id, what="role_id"))
    if role is None:
        raise errors.not_found("Ruolo inesistente.")
    if role.is_builtin:
        raise errors.conflict("Un ruolo predefinito non e' eliminabile.")
    assigned = session.execute(
        select(func.count(UserRole.user_id)).where(UserRole.role_id == role.id)
    ).scalar_one()
    if int(assigned) > 0:
        raise errors.conflict("Ruolo assegnato a utenti: rimuovere prima le assegnazioni.")
    session.delete(role)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="roles.delete",
        outcome="success",
        entity_type="role",
        entity_id=str(role_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


@router.put("/{role_id}/permissions", response_model=schemas.RoleOut)
def set_permissions(
    role_id: str,
    body: schemas.RolePermissionsUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("roles.assign_permissions")),
) -> schemas.RoleOut:
    role = session.get(Role, parse_uuid(role_id, what="role_id"))
    if role is None:
        raise errors.not_found("Ruolo inesistente.")
    if role.is_builtin:
        raise errors.conflict("I permessi di un ruolo predefinito non sono modificabili.")
    _validate_permission_codes(session, body.permission_codes)
    session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for code in body.permission_codes:
        session.add(RolePermission(role_id=role.id, permission_code=code))
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="roles.assign_permissions",
        outcome="success",
        entity_type="role",
        entity_id=str(role.id),
        ip=client_ip(request),
    )
    session.commit()
    session.refresh(role)
    return serializers.role_out(role)


@perm_router.get("", response_model=schemas.PermissionList)
def list_permissions(
    session: SessionDep, _: CurrentUser = Depends(require_permission("permissions.read"))
) -> schemas.PermissionList:
    rows = session.execute(select(Permission).order_by(Permission.area, Permission.code)).scalars().all()
    return schemas.PermissionList(
        items=[schemas.PermissionOut(code=p.code, area=p.area, description=p.description) for p in rows]
    )
