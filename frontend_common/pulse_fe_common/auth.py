"""Gestione sessione/JWT e controllo permessi lato UI (dashboard Server).

La sessione Flask memorizza access_token, refresh_token e il profilo utente
(con i permessi restituiti dal backend). I decoratori proteggono le route e,
alla scadenza del token (401 dal backend), l'utente viene reindirizzato al login.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from flask import (Flask, abort, flash, redirect, request, session, url_for)

from .rbac import has_any, has_permission

SESSION_ACCESS = "access_token"
SESSION_REFRESH = "refresh_token"
SESSION_USER = "user"


# -- accesso allo stato di sessione -------------------------------------------
def current_user() -> Optional[dict]:
    return session.get(SESSION_USER)


def access_token() -> Optional[str]:
    return session.get(SESSION_ACCESS)


def is_authenticated() -> bool:
    return bool(session.get(SESSION_ACCESS)) and bool(session.get(SESSION_USER))


def user_permissions() -> list:
    user = session.get(SESSION_USER) or {}
    return user.get("permissions", []) or []


def can(code: str) -> bool:
    """True se l'utente corrente possiede il permesso ``code``."""
    return has_permission(user_permissions(), code)


def store_session(access: str, refresh: Optional[str], user: dict) -> None:
    session[SESSION_ACCESS] = access
    if refresh is not None:
        session[SESSION_REFRESH] = refresh
    session[SESSION_USER] = user


def clear_session() -> None:
    session.pop(SESSION_ACCESS, None)
    session.pop(SESSION_REFRESH, None)
    session.pop(SESSION_USER, None)


# -- decoratori ----------------------------------------------------------------
def login_required(view: Callable) -> Callable:
    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if not is_authenticated():
            flash("Effettua l'accesso per continuare.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def permission_required(*codes: str) -> Callable:
    """Richiede l'autenticazione e almeno uno dei permessi indicati."""

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            if not is_authenticated():
                flash("Effettua l'accesso per continuare.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if not has_any(user_permissions(), codes):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


# -- integrazione con l'app ----------------------------------------------------
def register_template_helpers(app: Flask) -> None:
    """Espone ai template le utilità di permesso e l'utente corrente."""

    @app.context_processor
    def _inject():
        return {
            "can": can,
            "current_user": current_user(),
            "is_authenticated": is_authenticated(),
        }
