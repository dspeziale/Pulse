"""Dependency di autenticazione/autorizzazione (RBAC) e contesto di richiesta."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import errors
from .config import Settings, get_settings
from .db import get_session
from .models import Probe, RolePermission, User, UserRole
from .security import decode_token, verify_token_hash


@dataclass
class CurrentUser:
    """Utente autenticato risolto dal token JWT."""

    id: uuid.UUID
    username: str
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)

    def has_permission(self, code: str) -> bool:
        return code in self.permissions


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


def load_user_permissions(session: Session, user_id: uuid.UUID) -> set[str]:
    """Permessi effettivi = unione dei permessi dei ruoli dell'utente."""
    stmt = (
        select(RolePermission.permission_code)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return {row[0] for row in session.execute(stmt).all()}


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise errors.unauthorized("Header Authorization Bearer mancante.")
    return header[7:].strip()


def get_current_user(request: Request, session: SessionDep, settings: SettingsDep) -> CurrentUser:
    """Risolve l'utente corrente dal JWT di accesso."""
    token = _extract_bearer(request)
    try:
        payload = decode_token(token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm)
    except jwt.PyJWTError:
        raise errors.unauthorized("Token non valido o scaduto.")
    if payload.get("type") != "access":
        raise errors.unauthorized("Tipo di token non valido.")
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        raise errors.unauthorized("Subject del token non valido.")

    user = session.get(User, user_id)
    if user is None:
        raise errors.unauthorized("Utente inesistente.")
    if user.status != "active":
        raise errors.forbidden("Account disabilitato o bloccato.")

    perms = load_user_permissions(session, user.id)
    roles = [r.name for r in user.roles]
    return CurrentUser(id=user.id, username=user.username, roles=roles, permissions=perms)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_permission(code: str) -> Callable[[CurrentUser], CurrentUser]:
    """Factory di dependency che impone il possesso del permesso `code`."""

    def _dep(user: CurrentUserDep) -> CurrentUser:
        if not user.has_permission(code):
            raise errors.forbidden(f"Permesso richiesto: {code}")
        return user

    return _dep


@dataclass
class AuthedProbe:
    """Probe autenticata via token (mTLS gestito a livello di trasporto)."""

    id: uuid.UUID
    name: str


def get_authed_probe(request: Request, session: SessionDep) -> AuthedProbe:
    """Autentica una Probe tramite Bearer probe_token (mTLS a livello TLS/proxy).

    Nota (QT-01/QT-05): la verifica del certificato client mTLS avviene a livello
    di trasporto (uvicorn --ssl o reverse proxy). A livello applicativo si valida
    il token per-Probe confrontandone l'hash con probes.token_hash.
    """
    token = _extract_bearer(request)
    probes = session.execute(select(Probe).where(Probe.token_hash.is_not(None))).scalars().all()
    for probe in probes:
        if probe.token_hash and verify_token_hash(token, probe.token_hash):
            if not probe.enabled:
                raise errors.forbidden("Probe disabilitata o revocata.")
            return AuthedProbe(id=probe.id, name=probe.name)
    raise errors.unauthorized("Token Probe non valido.")


AuthedProbeDep = Annotated[AuthedProbe, Depends(get_authed_probe)]


def client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host
