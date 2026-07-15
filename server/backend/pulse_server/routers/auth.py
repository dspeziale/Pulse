"""Area Auth (DOCUMENTO_API §1.1)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from .. import errors, schemas
from ..audit import write_audit
from ..deps import (
    CurrentUser,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    client_ip,
    load_user_permissions,
    require_permission,
)
from ..models import DbSession, User
from ..security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from fastapi import Depends

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _issue_access(settings: SettingsDep, user: User, roles: list[str], perms: list[str]) -> str:
    return create_access_token(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        subject=str(user.id),
        ttl_seconds=settings.access_token_ttl_seconds,
        roles=roles,
        permissions=perms,
    )


@router.post("/login", response_model=schemas.LoginResponse)
def login(
    body: schemas.LoginRequest, request: Request, session: SessionDep, settings: SettingsDep
) -> schemas.LoginResponse:
    user = session.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    ip = client_ip(request)

    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.failed_login_threshold and user.status == "active":
                user.status = "locked"
            write_audit(
                session,
                actor_type="user",
                actor_id=str(user.id),
                action="auth.login",
                outcome="failure",
                ip=ip,
            )
            session.commit()
        raise errors.unauthorized("Credenziali non valide.")

    if user.status != "active":
        write_audit(
            session,
            actor_type="user",
            actor_id=str(user.id),
            action="auth.login",
            outcome="failure",
            ip=ip,
            details={"reason": user.status},
        )
        session.commit()
        raise errors.forbidden("Account disabilitato o bloccato.")

    perms = sorted(load_user_permissions(session, user.id))
    roles = [r.name for r in user.roles]
    access = _issue_access(settings, user, roles, perms)
    refresh = generate_opaque_token()
    now = dt.datetime.now(dt.timezone.utc)
    session.add(
        DbSession(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh),
            expires_at=now + dt.timedelta(seconds=settings.refresh_token_ttl_seconds),
            user_agent=request.headers.get("User-Agent"),
            ip=ip,
        )
    )
    user.failed_login_count = 0
    user.last_login_at = now
    write_audit(
        session, actor_type="user", actor_id=str(user.id), action="auth.login", outcome="success", ip=ip
    )
    session.commit()

    return schemas.LoginResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
        user=schemas.LoginUser(id=str(user.id), username=user.username, roles=roles, permissions=perms),
    )


@router.post("/refresh", response_model=schemas.RefreshResponse)
def refresh(
    body: schemas.RefreshRequest, session: SessionDep, settings: SettingsDep
) -> schemas.RefreshResponse:
    token_hash = hash_token(body.refresh_token)
    now = dt.datetime.now(dt.timezone.utc)
    db_session = session.execute(
        select(DbSession).where(DbSession.refresh_token_hash == token_hash)
    ).scalar_one_or_none()
    if db_session is None or db_session.revoked_at is not None or db_session.expires_at <= now:
        raise errors.unauthorized("Refresh token scaduto o revocato.")
    user = session.get(User, db_session.user_id)
    if user is None or user.status != "active":
        raise errors.unauthorized("Utente non valido.")
    perms = sorted(load_user_permissions(session, user.id))
    roles = [r.name for r in user.roles]
    access = _issue_access(settings, user, roles, perms)
    return schemas.RefreshResponse(access_token=access, expires_in=settings.access_token_ttl_seconds)


@router.post("/logout", status_code=204)
def logout(
    body: schemas.LogoutRequest, user: CurrentUserDep, session: SessionDep, request: Request
) -> Response:
    token_hash = hash_token(body.refresh_token)
    db_session = session.execute(
        select(DbSession).where(DbSession.refresh_token_hash == token_hash)
    ).scalar_one_or_none()
    if db_session is not None and db_session.revoked_at is None:
        db_session.revoked_at = dt.datetime.now(dt.timezone.utc)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.logout",
        outcome="success",
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


@router.get("/me", response_model=schemas.MeResponse)
def me(
    session: SessionDep,
    user: CurrentUser = Depends(require_permission("profile.read")),
) -> schemas.MeResponse:
    db_user = session.get(User, user.id)
    assert db_user is not None
    return schemas.MeResponse(
        id=str(db_user.id),
        username=db_user.username,
        email=db_user.email,
        full_name=db_user.full_name,
        roles=[r.name for r in db_user.roles],
        permissions=sorted(user.permissions),
        status=db_user.status,
    )


@router.post("/change-password", status_code=204)
def change_password(
    body: schemas.ChangePasswordRequest,
    session: SessionDep,
    request: Request,
    user: CurrentUser = Depends(require_permission("profile.update")),
) -> Response:
    db_user = session.get(User, user.id)
    assert db_user is not None
    if not verify_password(body.current_password, db_user.password_hash):
        raise errors.bad_request("Password attuale errata.")
    db_user.password_hash = hash_password(body.new_password)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.change_password",
        outcome="success",
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)
