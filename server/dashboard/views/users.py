"""P-06 Gestione Utenti.

REST: GET/POST /users, GET/PUT/DELETE /users/{id}, PUT /users/{id}/roles,
POST /users/{id}/reset-password, GET /roles (selezione).
"""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import (api_delete, api_get, api_post, api_put, page_args, query_args)

bp = Blueprint("users", __name__)


@bp.route("/users")
@permission_required("users.read")
def list_users():
    params = {**page_args(), **query_args("q", "status", "role")}
    data = api_get("/users", params=params)
    return render_template("users/list.html", data=data)


@bp.route("/users/new", methods=["GET"])
@permission_required("users.create")
def new_user():
    roles = api_get("/roles")
    return render_template("users/form.html", user=None, roles=roles)


@bp.route("/users/new", methods=["POST"])
@permission_required("users.create")
def create_user():
    payload = {
        "username": request.form.get("username", ""),
        "email": request.form.get("email", ""),
        "full_name": request.form.get("full_name", ""),
        "password": request.form.get("password", ""),
        "role_ids": request.form.getlist("role_ids"),
        "status": request.form.get("status", "active"),
    }
    api_post("/users", json=payload)
    flash("Utente creato.", "success")
    return redirect(url_for("users.list_users"))


@bp.route("/users/<user_id>")
@permission_required("users.read")
def detail(user_id: str):
    user = api_get(f"/users/{user_id}")
    return render_template("users/detail.html", user=user)


@bp.route("/users/<user_id>/edit", methods=["GET"])
@permission_required("users.update")
def edit_user(user_id: str):
    user = api_get(f"/users/{user_id}")
    roles = api_get("/roles")
    return render_template("users/form.html", user=user, roles=roles)


@bp.route("/users/<user_id>/edit", methods=["POST"])
@permission_required("users.update")
def update_user(user_id: str):
    payload = {
        "email": request.form.get("email", ""),
        "full_name": request.form.get("full_name", ""),
        "status": request.form.get("status", "active"),
    }
    api_put(f"/users/{user_id}", json=payload)
    flash("Utente aggiornato.", "success")
    return redirect(url_for("users.detail", user_id=user_id))


@bp.route("/users/<user_id>/roles", methods=["POST"])
@permission_required("users.assign_roles")
def assign_roles(user_id: str):
    payload = {"role_ids": request.form.getlist("role_ids")}
    api_put(f"/users/{user_id}/roles", json=payload)
    flash("Ruoli aggiornati.", "success")
    return redirect(url_for("users.detail", user_id=user_id))


@bp.route("/users/<user_id>/reset-password", methods=["POST"])
@permission_required("users.update")
def reset_password(user_id: str):
    payload = {"new_password": request.form.get("new_password", "")}
    api_post(f"/users/{user_id}/reset-password", json=payload)
    flash("Password reimpostata.", "success")
    return redirect(url_for("users.detail", user_id=user_id))


@bp.route("/users/<user_id>/delete", methods=["POST"])
@permission_required("users.delete")
def delete_user(user_id: str):
    api_delete(f"/users/{user_id}")
    flash("Utente eliminato/disabilitato.", "success")
    return redirect(url_for("users.list_users"))
