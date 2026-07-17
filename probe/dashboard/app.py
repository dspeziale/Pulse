"""Dashboard della PROBE Pulse — factory dell'app Flask.

Consuma esclusivamente le API di query locali della PROBE (sezione BACKEND del
DOCUMENTO_API, "Endpoint sulla PROBE"). Nessun accesso diretto a OpenSearch.
"""
from __future__ import annotations

import os
from typing import Optional

from flask import Flask, flash, redirect, render_template, url_for

from pulse_fe_common.config import ProbeDashboardConfig
from pulse_fe_common.datetimes import DEFAULT_FORMAT, format_datetime
from pulse_fe_common.http_client import (ApiAuthError, ApiError,
                                         ApiUnavailableError, ApiClient)

import dt as dt_adapter
from probe_auth import clear_session, is_authenticated, register_template_helpers
from views import register_blueprints


def create_app(config: Optional[ProbeDashboardConfig] = None) -> Flask:
    cfg = config or ProbeDashboardConfig.from_env()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.secret_key
    # Nome cookie di sessione distinto dalla dashboard Server: su localhost i
    # cookie non distinguono la porta, un nome condiviso deautenticherebbe l'utente
    # aprendo entrambe le dashboard.
    app.config["SESSION_COOKIE_NAME"] = cfg.session_cookie_name
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = cfg.session_cookie_secure
    app.config["PULSE_CFG"] = cfg
    app.config["API_CLIENT"] = ApiClient(
        cfg.agent_base_url, timeout=cfg.request_timeout, verify=cfg.verify_tls
    )

    register_template_helpers(app)

    # Filtro Jinja ``localdt``: la dashboard Probe non ha accesso alla config del
    # Server, quindi usa il fuso orario configurato via env (PULSE_PROBE_TIMEZONE,
    # default Europe/Rome). Su fuso non valido si ripiega su Europe/Rome/UTC.
    @app.template_filter("localdt")
    def _localdt(value, fmt: str = DEFAULT_FORMAT):
        return format_datetime(value, cfg.timezone, fmt)

    register_blueprints(app)
    app.register_blueprint(dt_adapter.bp)
    dt_adapter.register_template_globals(app)
    _register_error_handlers(app)

    @app.route("/")
    def _root():
        if is_authenticated():
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    @app.route("/healthz")
    def _healthz():
        """Liveness della dashboard Probe (non verifica il probe-agent)."""
        return {"status": "ok"}, 200

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiAuthError)
    def _on_auth(exc: ApiAuthError):
        # 401 dal probe-agent: token dashboard→agent errato/scaduto (non la sessione locale).
        flash("Probe-agent: autenticazione non valida (verifica il token).", "danger")
        return render_template("error.html", code=401, message=exc.message), 401

    @app.errorhandler(ApiError)
    def _on_api(exc: ApiError):
        flash(f"Errore dal probe-agent: {exc.message}", "danger")
        return (
            render_template("error.html", code=exc.status_code, message=exc.message),
            exc.status_code,
        )

    @app.errorhandler(ApiUnavailableError)
    def _on_unavailable(exc: ApiUnavailableError):
        flash("Probe-agent non raggiungibile.", "danger")
        return render_template("error.html", code=503, message=exc.message), 503

    @app.errorhandler(404)
    def _on_404(_exc):
        return render_template("error.html", code=404,
                               message="Pagina non trovata."), 404


# Istanza WSGI per l'esecuzione in container / gunicorn.
app = create_app()


if __name__ == "__main__":  # pragma: no cover - avvio manuale
    app.run(host="0.0.0.0", port=int(os.environ.get("PULSE_PROBE_DASH_PORT", 5001)))
