"""Sessione e login locale della dashboard PROBE.

Decisione FE-02 (vedi QUESTIONI APERTE API-04): la dashboard Probe autentica gli
operatori locali con credenziali locali (da variabili d'ambiente), indipendenti
dal RBAC del Server, così da restare operativa anche a Server irraggiungibile.
Non esiste un modello di permessi granulare sulla Probe: l'operatore locale, una
volta autenticato, accede alle sole viste di sola lettura dei dati locali.
"""
from __future__ import annotations

import functools
import hmac
from typing import Any, Callable, Optional

from flask import (Flask, current_app, flash, redirect, request, session,
                   url_for)

SESSION_USER = "probe_user"


def current_user() -> Optional[str]:
    return session.get(SESSION_USER)


def is_authenticated() -> bool:
    return bool(session.get(SESSION_USER))


def verify_credentials(username: str, password: str) -> bool:
    """Confronto costante-nel-tempo con le credenziali locali configurate."""
    cfg = current_app.config["PULSE_CFG"]
    ok_user = hmac.compare_digest(username or "", cfg.dash_user)
    ok_pass = hmac.compare_digest(password or "", cfg.dash_password)
    return ok_user and ok_pass


def store_session(username: str) -> None:
    session[SESSION_USER] = username


def clear_session() -> None:
    session.pop(SESSION_USER, None)


def login_required(view: Callable) -> Callable:
    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if not is_authenticated():
            flash("Effettua l'accesso per continuare.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def register_template_helpers(app: Flask) -> None:
    @app.context_processor
    def _inject():
        return {
            "current_user": current_user(),
            "is_authenticated": is_authenticated(),
        }
