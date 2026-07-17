"""Area Utenti (DOCUMENTO_API §1.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, or_, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUser, SessionDep, client_ip, require_permission
from ..models import Role, User, UserRole
from ..security import hash_password
from ._helpers import (
    clamp_pagination,
    commit_or_conflict,
    flush_or_conflict,
    offset,
    parse_uuid,
    sort_clause,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])

SUPERADMIN = "SuperAdmin"


def _load_roles(session: SessionDep, role_ids: list[str]) -> list[Role]:
    roles: list[Role] = []
    for rid in role_ids:
        role = session.get(Role, parse_uuid(rid, what="role_id"))
        if role is None:
            raise errors.unprocessable(f"Ruolo inesistente: {rid}")
        roles.append(role)
    return roles


def _count_active_superadmins(session: SessionDep, *, exclude: uuid.UUID | None = None) -> int:
    stmt = (
        select(func.count(func.distinct(User.id)))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == SUPERADMIN, User.status == "active")
    )
    if exclude is not None:
        stmt = stmt.where(User.id != exclude)
    return int(session.execute(stmt).scalar_one())


def _is_superadmin(user: User) -> bool:
    return any(r.name == SUPERADMIN for r in user.roles)


@router.get("", response_model=schemas.UserList)
def list_users(
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    status: str | None = None,
    role: str | None = None,
    sort: str | None = None,
    _: CurrentUser = Depends(require_permission("users.read")),
) -> schemas.UserList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(User)
    count_stmt = select(func.count(func.distinct(User.id)))
    if role is not None:
        stmt = stmt.join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
        count_stmt = count_stmt.join(UserRole, UserRole.user_id == User.id).join(
            Role, Role.id == UserRole.role_id
        )
        stmt = stmt.where(Role.name == role)
        count_stmt = count_stmt.where(Role.name == role)
    if status is not None:
        stmt = stmt.where(User.status == status)
        count_stmt = count_stmt.where(User.status == status)
    if q:
        like = f"%{q}%"
        cond = or_(User.username.ilike(like), User.email.ilike(like), User.full_name.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(session.execute(count_stmt).scalar_one())
    order = sort_clause(
        sort,
        {
            "username": User.username,
            "full_name": User.full_name,
            "email": User.email,
            "created_at": User.created_at,
            "last_login_at": User.last_login_at,
            "status": User.status,
        },
        User.created_at.asc(),
    )
    rows = (
        session.execute(stmt.order_by(order).offset(offset(page, page_size)).limit(page_size))
        .scalars()
        .all()
    )
    return schemas.UserList(
        items=[serializers.user_out(u) for u in rows], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=schemas.UserOut, status_code=201)
def create_user(
    body: schemas.UserCreate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users.create")),
) -> schemas.UserOut:
    roles = _load_roles(session, body.role_ids)
    user = User(
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        status=body.status,
    )
    session.add(user)
    flush_or_conflict(session, message="Username o email gia' esistenti.")
    for role in roles:
        session.add(UserRole(user_id=user.id, role_id=role.id))
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="users.create",
        outcome="success",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Username o email gia' esistenti.")
    session.refresh(user)
    return serializers.user_out(user)


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(
    user_id: str, session: SessionDep, _: CurrentUser = Depends(require_permission("users.read"))
) -> schemas.UserOut:
    user = session.get(User, parse_uuid(user_id, what="user_id"))
    if user is None:
        raise errors.not_found("Utente inesistente.")
    return serializers.user_out(user)


@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: str,
    body: schemas.UserUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users.update")),
) -> schemas.UserOut:
    user = session.get(User, parse_uuid(user_id, what="user_id"))
    if user is None:
        raise errors.not_found("Utente inesistente.")
    if body.status is not None and body.status != "active" and user.id == actor.id:
        raise errors.conflict("Un utente non puo' auto-disabilitarsi.")
    if (
        body.status is not None
        and body.status != "active"
        and _is_superadmin(user)
        and _count_active_superadmins(session, exclude=user.id) == 0
    ):
        raise errors.conflict("Deve esistere almeno un SuperAdmin attivo.")
    if body.email is not None:
        user.email = body.email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.status is not None:
        user.status = body.status
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="users.update",
        outcome="success",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Email gia' in uso.")
    session.refresh(user)
    return serializers.user_out(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users.delete")),
) -> Response:
    user = session.get(User, parse_uuid(user_id, what="user_id"))
    if user is None:
        raise errors.not_found("Utente inesistente.")
    if user.id == actor.id:
        raise errors.conflict("Un utente non puo' auto-eliminarsi.")
    if _is_superadmin(user) and _count_active_superadmins(session, exclude=user.id) == 0:
        raise errors.conflict("Deve esistere almeno un SuperAdmin attivo.")
    session.delete(user)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="users.delete",
        outcome="success",
        entity_type="user",
        entity_id=str(user_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


@router.put("/{user_id}/roles", response_model=schemas.UserOut)
def set_roles(
    user_id: str,
    body: schemas.UserRolesUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users.assign_roles")),
) -> schemas.UserOut:
    user = session.get(User, parse_uuid(user_id, what="user_id"))
    if user is None:
        raise errors.not_found("Utente inesistente.")
    roles = _load_roles(session, body.role_ids)
    had_superadmin = _is_superadmin(user)
    will_superadmin = any(r.name == SUPERADMIN for r in roles)
    if (
        had_superadmin
        and not will_superadmin
        and user.status == "active"
        and _count_active_superadmins(session, exclude=user.id) == 0
    ):
        raise errors.conflict("Deve esistere almeno un SuperAdmin attivo.")
    session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role in roles:
        session.add(UserRole(user_id=user.id, role_id=role.id))
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="users.assign_roles",
        outcome="success",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    session.commit()
    session.refresh(user)
    return serializers.user_out(user)


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: str,
    body: schemas.ResetPasswordRequest,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users.update")),
) -> Response:
    user = session.get(User, parse_uuid(user_id, what="user_id"))
    if user is None:
        raise errors.not_found("Utente inesistente.")
    user.password_hash = hash_password(body.new_password)
    user.failed_login_count = 0
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="users.reset_password",
        outcome="success",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)
