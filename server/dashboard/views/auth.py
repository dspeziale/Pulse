"""P-01 Login / Logout — POST /auth/login, GET /auth/me, POST /auth/logout."""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)

from pulse_fe_common.auth import (SESSION_REFRESH, access_token, clear_session,
                                   is_authenticated, login_required,
                                   store_session)
from pulse_fe_common.http_client import ApiError, ApiUnavailableError

from sdk import client

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        try:
            data = client().post(
                "/auth/login",
                json={"username": username, "password": password},
            )
            access = data["access_token"]
            refresh = data.get("refresh_token")
            me = client().get("/auth/me", token=access)
            store_session(access, refresh, me)
        except (ApiError, ApiUnavailableError):
            flash("Credenziali non valide o accesso negato.", "danger")
            return render_template("auth/login.html"), 401
        flash("Accesso effettuato.", "success")
        nxt = request.args.get("next") or url_for("dashboard.index")
        return redirect(nxt)
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    refresh = session.get(SESSION_REFRESH)
    try:
        client().post(
            "/auth/logout",
            token=access_token(),
            json={"refresh_token": refresh},
        )
    except (ApiError, ApiUnavailableError):
        pass
    clear_session()
    flash("Disconnesso.", "success")
    return redirect(url_for("auth.login"))
