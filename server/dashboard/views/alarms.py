"""P-14 Allarmi. REST: GET /alarms, POST /alarms/{id}/ack."""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import api_get, api_post, page_args, query_args

bp = Blueprint("alarms", __name__)


@bp.route("/alarms")
@permission_required("workflows.read")
def list_alarms():
    params = {**page_args(),
              **query_args("status", "system_id", "probe_id", "from", "to")}
    data = api_get("/alarms", params=params)
    return render_template("alarms/list.html", data=data)


@bp.route("/alarms/<alarm_id>/ack", methods=["POST"])
@permission_required("commands.execute")
def ack_alarm(alarm_id: str):
    payload = {"note": request.form.get("note", "")}
    api_post(f"/alarms/{alarm_id}/ack", json=payload)
    flash("Allarme riconosciuto.", "success")
    return redirect(url_for("alarms.list_alarms"))
