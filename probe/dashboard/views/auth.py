"""PP-01 Login (Probe) — autenticazione locale dell'operatore."""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from probe_auth import (clear_session, is_authenticated, login_required,
                        store_session, verify_credentials)

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_credentials(username, password):
            store_session(username)
            flash("Accesso effettuato.", "success")
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Credenziali locali non valide.", "danger")
        return render_template("auth/login.html"), 401
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    clear_session()
    flash("Disconnesso.", "success")
    return redirect(url_for("auth.login"))
