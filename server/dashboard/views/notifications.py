"""P-11 Canali Notifica e P-13 Storico Notifiche.

REST: GET/POST /notification-channels, GET/PUT/DELETE
/notification-channels/{id}, POST /notification-channels/{id}/test,
GET /notifications/history.
"""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import (api_delete, api_get, api_post, api_put, page_args, query_args)

bp = Blueprint("notifications", __name__)


def _build_config(ch_type: str) -> dict:
    """Costruisce il blocco config in base al tipo di canale."""
    f = request.form
    if ch_type == "email":
        return {
            "smtp_host": f.get("smtp_host", ""),
            "smtp_port": int(f.get("smtp_port") or 0),
            "use_tls": f.get("use_tls") == "on",
            "username": f.get("username", ""),
            "password": f.get("password", ""),
            "from_address": f.get("from_address", ""),
            "imap_host": f.get("imap_host", ""),
            "imap_port": int(f.get("imap_port") or 0),
        }
    if ch_type == "telegram":
        return {
            "bot_token": f.get("bot_token", ""),
            "webhook_secret": f.get("webhook_secret", ""),
        }
    # whatsapp
    return {
        "provider": f.get("provider", ""),
        "api_base": f.get("api_base", ""),
        "api_token": f.get("api_token", ""),
        "phone_number_id": f.get("phone_number_id", ""),
        "webhook_secret": f.get("webhook_secret", ""),
    }


def _build_payload() -> dict:
    ch_type = request.form.get("type", "email")
    return {
        "name": request.form.get("name", ""),
        "type": ch_type,
        "enabled": request.form.get("enabled") == "on",
        "inbound_enabled": request.form.get("inbound_enabled") == "on",
        "config": _build_config(ch_type),
    }


@bp.route("/notification-channels")
@permission_required("notifications.read")
def list_channels():
    params = {**page_args(), **query_args("type", "enabled")}
    data = api_get("/notification-channels", params=params)
    return render_template("notifications/list.html", data=data)


@bp.route("/notification-channels/new", methods=["GET"])
@permission_required("notifications.create")
def new_channel():
    return render_template("notifications/form.html", channel=None)


@bp.route("/notification-channels/new", methods=["POST"])
@permission_required("notifications.create")
def create_channel():
    api_post("/notification-channels", json=_build_payload())
    flash("Canale creato.", "success")
    return redirect(url_for("notifications.list_channels"))


@bp.route("/notification-channels/<channel_id>")
@permission_required("notifications.read")
def detail(channel_id: str):
    channel = api_get(f"/notification-channels/{channel_id}")
    return render_template("notifications/detail.html", channel=channel)


@bp.route("/notification-channels/<channel_id>/edit", methods=["GET"])
@permission_required("notifications.update")
def edit_channel(channel_id: str):
    channel = api_get(f"/notification-channels/{channel_id}")
    return render_template("notifications/form.html", channel=channel)


@bp.route("/notification-channels/<channel_id>/edit", methods=["POST"])
@permission_required("notifications.update")
def update_channel(channel_id: str):
    api_put(f"/notification-channels/{channel_id}", json=_build_payload())
    flash("Canale aggiornato.", "success")
    return redirect(url_for("notifications.detail", channel_id=channel_id))


@bp.route("/notification-channels/<channel_id>/delete", methods=["POST"])
@permission_required("notifications.delete")
def delete_channel(channel_id: str):
    api_delete(f"/notification-channels/{channel_id}")
    flash("Canale eliminato.", "success")
    return redirect(url_for("notifications.list_channels"))


@bp.route("/notification-channels/<channel_id>/test", methods=["POST"])
@permission_required("notifications.test")
def test_channel(channel_id: str):
    payload = {
        "recipient": request.form.get("recipient", ""),
        "message": request.form.get("message", ""),
    }
    result = api_post(f"/notification-channels/{channel_id}/test", json=payload)
    if result.get("delivered"):
        flash(f"Test inviato: {result.get('detail', '')}", "success")
    else:
        flash(f"Test non riuscito: {result.get('detail', '')}", "danger")
    return redirect(url_for("notifications.detail", channel_id=channel_id))


@bp.route("/notifications/history")
@permission_required("notifications.read")
def history():
    params = {**page_args(),
              **query_args("channel_id", "workflow_id", "status", "from", "to")}
    data = api_get("/notifications/history", params=params)
    return render_template("notifications/history.html", data=data)
