"""P-02 Dashboard aggregata (Server).

REST: GET /dashboard/aggregate, GET /probes, GET /alarms?status=active.
"""
from __future__ import annotations

from flask import Blueprint, render_template, request

from pulse_fe_common.auth import permission_required

from sdk import api_get

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@permission_required("dashboard.read")
def index():
    window = request.args.get("window", "24h")
    aggregate = api_get("/dashboard/aggregate", params={"window": window})
    probes = api_get("/probes")
    alarms = api_get("/alarms", params={"status": "active"})
    return render_template(
        "dashboard/index.html",
        aggregate=aggregate,
        probes=probes,
        alarms=alarms,
        window=window,
    )
