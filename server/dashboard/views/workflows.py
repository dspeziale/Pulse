"""P-12 Gestione Workflow Notifiche.

REST: GET/POST /notification-workflows, GET/PUT/DELETE
/notification-workflows/{id}, PUT /notification-workflows/{id}/enabled,
POST /notification-workflows/{id}/simulate, GET /notification-channels.

I blocchi complessi (scope, conditions, actions, suppression) sono editati come
JSON in textarea: rispecchiano 1:1 lo schema Workflow del DOCUMENTO_API.
"""
from __future__ import annotations

import json

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import (api_delete, api_get, api_post, api_put, page_args, paging,
                 query_args)

bp = Blueprint("workflows", __name__)


class _JsonFieldError(Exception):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def _json_field(name: str, default):
    raw = request.form.get(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise _JsonFieldError(name) from exc


def _build_payload() -> dict:
    return {
        "name": request.form.get("name", ""),
        "description": request.form.get("description", ""),
        "enabled": request.form.get("enabled") == "on",
        "trigger": request.form.get("trigger", ""),
        "scope": _json_field("scope", {}),
        "conditions": _json_field("conditions", []),
        "suppression": _json_field("suppression", {}),
        "actions": _json_field("actions", []),
    }


@bp.route("/notification-workflows")
@permission_required("workflows.read")
def list_workflows():
    params = {**page_args(), **query_args("q", "enabled")}
    data = api_get("/notification-workflows", params=params)
    filters = {k: v for k, v in params.items() if k != "page"}
    page, page_size = paging()
    return render_template("workflows/list.html", data=data, filters=filters,
                           page=page, page_size=page_size)


@bp.route("/notification-workflows/new", methods=["GET"])
@permission_required("workflows.create")
def new_workflow():
    channels = api_get("/notification-channels")
    return render_template("workflows/form.html", workflow=None, channels=channels)


@bp.route("/notification-workflows/new", methods=["POST"])
@permission_required("workflows.create")
def create_workflow():
    try:
        payload = _build_payload()
    except _JsonFieldError as exc:
        flash(f"Campo JSON non valido: {exc.field}.", "danger")
        return redirect(url_for("workflows.new_workflow"))
    api_post("/notification-workflows", json=payload)
    flash("Workflow creato.", "success")
    return redirect(url_for("workflows.list_workflows"))


@bp.route("/notification-workflows/<workflow_id>")
@permission_required("workflows.read")
def detail(workflow_id: str):
    workflow = api_get(f"/notification-workflows/{workflow_id}")
    return render_template("workflows/detail.html", workflow=workflow)


@bp.route("/notification-workflows/<workflow_id>/edit", methods=["GET"])
@permission_required("workflows.update")
def edit_workflow(workflow_id: str):
    workflow = api_get(f"/notification-workflows/{workflow_id}")
    channels = api_get("/notification-channels")
    return render_template("workflows/form.html", workflow=workflow,
                           channels=channels)


@bp.route("/notification-workflows/<workflow_id>/edit", methods=["POST"])
@permission_required("workflows.update")
def update_workflow(workflow_id: str):
    try:
        payload = _build_payload()
    except _JsonFieldError as exc:
        flash(f"Campo JSON non valido: {exc.field}.", "danger")
        return redirect(url_for("workflows.edit_workflow",
                                workflow_id=workflow_id))
    api_put(f"/notification-workflows/{workflow_id}", json=payload)
    flash("Workflow aggiornato.", "success")
    return redirect(url_for("workflows.detail", workflow_id=workflow_id))


@bp.route("/notification-workflows/<workflow_id>/enabled", methods=["POST"])
@permission_required("workflows.update")
def toggle_enabled(workflow_id: str):
    enabled = request.form.get("enabled") == "on"
    api_put(f"/notification-workflows/{workflow_id}/enabled",
            json={"enabled": enabled})
    flash("Stato workflow aggiornato.", "success")
    return redirect(url_for("workflows.detail", workflow_id=workflow_id))


@bp.route("/notification-workflows/<workflow_id>/simulate", methods=["POST"])
@permission_required("workflows.update")
def simulate(workflow_id: str):
    try:
        event = _json_field("event", {})
    except _JsonFieldError as exc:
        flash(f"Campo JSON non valido: {exc.field}.", "danger")
        return redirect(url_for("workflows.detail", workflow_id=workflow_id))
    result = api_post(f"/notification-workflows/{workflow_id}/simulate",
                      json={"event": event})
    return render_template("workflows/simulate.html", workflow_id=workflow_id,
                           result=result)


@bp.route("/notification-workflows/<workflow_id>/delete", methods=["POST"])
@permission_required("workflows.delete")
def delete_workflow(workflow_id: str):
    api_delete(f"/notification-workflows/{workflow_id}")
    flash("Workflow eliminato.", "success")
    return redirect(url_for("workflows.list_workflows"))
