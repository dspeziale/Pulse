"""P-07 Gestione Ruoli.

REST: GET/POST /roles, GET/PUT/DELETE /roles/{id},
PUT /roles/{id}/permissions, GET /permissions.
"""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import (api_delete, api_get, api_post, api_put, page_args, paging,
                 query_args)

bp = Blueprint("roles", __name__)


@bp.route("/roles")
@permission_required("roles.read")
def list_roles():
    params = {**page_args(), **query_args("q")}
    data = api_get("/roles", params=params)
    filters = {k: v for k, v in params.items() if k != "page"}
    page, page_size = paging()
    return render_template("roles/list.html", data=data, filters=filters,
                           page=page, page_size=page_size)


@bp.route("/roles/new", methods=["GET"])
@permission_required("roles.create")
def new_role():
    permissions = api_get("/permissions")
    return render_template("roles/form.html", role=None, permissions=permissions)


@bp.route("/roles/new", methods=["POST"])
@permission_required("roles.create")
def create_role():
    payload = {
        "name": request.form.get("name", ""),
        "description": request.form.get("description", ""),
        "permission_codes": request.form.getlist("permission_codes"),
    }
    api_post("/roles", json=payload)
    flash("Ruolo creato.", "success")
    return redirect(url_for("roles.list_roles"))


@bp.route("/roles/<role_id>")
@permission_required("roles.read")
def detail(role_id: str):
    role = api_get(f"/roles/{role_id}")
    return render_template("roles/detail.html", role=role)


@bp.route("/roles/<role_id>/edit", methods=["GET"])
@permission_required("roles.update")
def edit_role(role_id: str):
    role = api_get(f"/roles/{role_id}")
    permissions = api_get("/permissions")
    return render_template("roles/form.html", role=role, permissions=permissions)


@bp.route("/roles/<role_id>/edit", methods=["POST"])
@permission_required("roles.update")
def update_role(role_id: str):
    payload = {
        "name": request.form.get("name", ""),
        "description": request.form.get("description", ""),
    }
    api_put(f"/roles/{role_id}", json=payload)
    flash("Ruolo aggiornato.", "success")
    return redirect(url_for("roles.detail", role_id=role_id))


@bp.route("/roles/<role_id>/permissions", methods=["POST"])
@permission_required("roles.assign_permissions")
def assign_permissions(role_id: str):
    payload = {"permission_codes": request.form.getlist("permission_codes")}
    api_put(f"/roles/{role_id}/permissions", json=payload)
    flash("Permessi del ruolo aggiornati.", "success")
    return redirect(url_for("roles.detail", role_id=role_id))


@bp.route("/roles/<role_id>/delete", methods=["POST"])
@permission_required("roles.delete")
def delete_role(role_id: str):
    api_delete(f"/roles/{role_id}")
    flash("Ruolo eliminato.", "success")
    return redirect(url_for("roles.list_roles"))
