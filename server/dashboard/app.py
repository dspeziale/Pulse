"""Dashboard del SERVER Pulse — factory dell'app Flask.

Consuma esclusivamente le API REST della sezione BACKEND del DOCUMENTO_API.
Nessun accesso diretto a DB/OpenSearch.
"""
from __future__ import annotations

import os
from typing import Optional

from flask import Flask, flash, redirect, render_template, url_for

from pulse_fe_common.auth import (access_token, clear_session,
                                  register_template_helpers)
from pulse_fe_common.config import ServerDashboardConfig
from pulse_fe_common.datetimes import DEFAULT_FORMAT, format_datetime
from pulse_fe_common.http_client import (ApiAuthError, ApiError,
                                         ApiUnavailableError, ApiClient)

import dt as dt_adapter
from probesource import fetch_probe_names, probe_name, resolve_probe_names
from tzsource import fetch_config_timezone, resolve_timezone
from views import register_blueprints


def create_app(config: Optional[ServerDashboardConfig] = None) -> Flask:
    cfg = config or ServerDashboardConfig.from_env()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.secret_key
    # Nome cookie di sessione distinto dalla dashboard Probe: su localhost i
    # cookie non distinguono la porta, un nome condiviso deautenticherebbe l'utente
    # aprendo entrambe le dashboard.
    app.config["SESSION_COOKIE_NAME"] = cfg.session_cookie_name
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = cfg.session_cookie_secure
    app.config["PULSE_CFG"] = cfg
    app.config["API_CLIENT"] = ApiClient(
        cfg.api_base_url, timeout=cfg.request_timeout, verify=cfg.verify_tls
    )

    register_template_helpers(app)
    _register_timezone_filter(app)
    _register_probe_name_filter(app)
    register_blueprints(app)
    app.register_blueprint(dt_adapter.bp)
    dt_adapter.register_template_globals(app)
    _register_error_handlers(app)

    @app.route("/")
    def _root():
        from pulse_fe_common.auth import is_authenticated

        if is_authenticated():
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    @app.route("/healthz")
    def _healthz():
        """Liveness della dashboard (non verifica il backend). Per container."""
        return {"status": "ok"}, 200

    return app


def _register_timezone_filter(app: Flask) -> None:
    """Registra il filtro Jinja ``localdt`` (fuso orario da /config, con cache).

    Il fuso orario e' letto dalla configurazione del backend e memorizzato in una
    cache TTL su ``app.config`` (isolata per istanza dell'app). Su qualunque
    errore si ripiega su Europe/Rome (vedi tzsource.resolve_timezone).
    """
    app.config["TZ_CACHE"] = {"value": "Europe/Rome", "exp": 0.0}

    def _tz_fetch():
        return fetch_config_timezone(app.config["API_CLIENT"], access_token())

    @app.template_filter("localdt")
    def _localdt(value, fmt: str = DEFAULT_FORMAT):
        tz = resolve_timezone(app.config["TZ_CACHE"], _tz_fetch)
        return format_datetime(value, tz, fmt)


def _register_probe_name_filter(app: Flask) -> None:
    """Registra il filtro Jinja ``probe_name`` (probe_id -> nome, con cache).

    La mappa {id: name} e' letta da GET /probes e memorizzata in una cache TTL su
    ``app.config`` (isolata per istanza). Su qualunque errore (permesso assente,
    backend giu', id non in mappa) ripiega sul probe_id stesso (vedi probesource).
    """
    app.config["PROBE_CACHE"] = {"value": {}, "exp": 0.0}

    def _fetch():
        return fetch_probe_names(app.config["API_CLIENT"], access_token())

    @app.template_filter("probe_name")
    def _probe_name(value):
        names = resolve_probe_names(app.config["PROBE_CACHE"], _fetch)
        return probe_name(names, value)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiAuthError)
    def _on_auth(_exc: ApiAuthError):
        clear_session()
        flash("Sessione scaduta: effettua di nuovo l'accesso.", "warning")
        return redirect(url_for("auth.login"))

    @app.errorhandler(ApiError)
    def _on_api(exc: ApiError):
        flash(f"Errore dal backend: {exc.message}", "danger")
        return (
            render_template("error.html", code=exc.status_code, message=exc.message),
            exc.status_code,
        )

    @app.errorhandler(ApiUnavailableError)
    def _on_unavailable(exc: ApiUnavailableError):
        flash("Backend non raggiungibile.", "danger")
        return (
            render_template("error.html", code=503, message=exc.message),
            503,
        )

    @app.errorhandler(403)
    def _on_403(_exc):
        return render_template("error.html", code=403,
                               message="Permesso negato."), 403

    @app.errorhandler(404)
    def _on_404(_exc):
        return render_template("error.html", code=404,
                               message="Pagina non trovata."), 404


# Istanza WSGI per l'esecuzione in container / gunicorn.
app = create_app()


if __name__ == "__main__":  # pragma: no cover - avvio manuale
    app.run(host="0.0.0.0", port=int(os.environ.get("PULSE_SERVER_DASH_PORT", 5000)))
