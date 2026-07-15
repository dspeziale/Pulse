"""P-19 Profilo utente. REST: GET /auth/me, POST /auth/change-password."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from pulse_fe_common.auth import permission_required

from sdk import api_get, api_post

bp = Blueprint("profile", __name__)


@bp.route("/profile")
@permission_required("profile.read")
def show_profile():
    me = api_get("/auth/me")
    return render_template("profile/index.html", me=me)


@bp.route("/profile/change-password", methods=["POST"])
@permission_required("profile.update")
def change_password():
    payload = {
        "current_password": request.form.get("current_password", ""),
        "new_password": request.form.get("new_password", ""),
    }
    api_post("/auth/change-password", json=payload)
    flash("Password aggiornata.", "success")
    return redirect(url_for("profile.show_profile"))
