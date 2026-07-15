"""Dependency della Probe: stato runtime e autenticazione del Server (token)."""

from __future__ import annotations

import hmac

from fastapi import Request

from . import errors
from .state import RuntimeState


def get_state(request: Request) -> RuntimeState:
    state: RuntimeState = request.app.state.runtime
    return state


def require_server_token(request: Request) -> None:
    """Valida il Bearer token presentato dal Server (mTLS a livello trasporto)."""
    state: RuntimeState = request.app.state.runtime
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise errors.unauthorized("Header Authorization Bearer mancante.")
    token = header[7:].strip()
    if not hmac.compare_digest(token, state.settings.server_query_token):
        raise errors.unauthorized("Token del Server non valido.")
