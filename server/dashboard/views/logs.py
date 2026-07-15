"""P-17 Log di Sistema. REST: GET /logs."""
from __future__ import annotations

from flask import Blueprint, render_template

from pulse_fe_common.auth import permission_required

from sdk import api_get, page_args, query_args

bp = Blueprint("logs", __name__)


@bp.route("/logs")
@permission_required("syslog.read")
def list_logs():
    params = {**page_args(),
              **query_args("component", "probe_id", "level", "from", "to", "q")}
    data = api_get("/logs", params=params)
    return render_template("logs/list.html", data=data)
