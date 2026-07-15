"""Dashboard del SERVER Pulse — factory dell'app Flask.

Consuma esclusivamente le API REST della sezione BACKEND del DOCUMENTO_API.
Nessun accesso diretto a DB/OpenSearch.
"""
from __future__ import annotations

import os
from typing import Optional

from flask import Flask, flash, redirect, render_template, url_for

from pulse_fe_common.auth import clear_session, register_template_helpers
from pulse_fe_common.config import ServerDashboardConfig
from pulse_fe_common.http_client import (ApiAuthError, ApiError,
                                         ApiUnavailableError, ApiClient)

from views import register_blueprints


def create_app(config: Optional[ServerDashboardConfig] = None) -> Flask:
    cfg = config or ServerDashboardConfig.from_env()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["PULSE_CFG"] = cfg
    app.config["API_CLIENT"] = ApiClient(
        cfg.api_base_url, timeout=cfg.request_timeout, verify=cfg.verify_tls
    )

    register_template_helpers(app)
    register_blueprints(app)
    _register_error_handlers(app)

    @app.route("/")
    def _root():
        from pulse_fe_common.auth import is_authenticated

        if is_authenticated():
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    return app


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
