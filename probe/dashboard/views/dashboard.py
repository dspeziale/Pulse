"""PP-02 Dashboard Probe completa e PP-03 Dettaglio sistema/check.

REST (PROBE): GET /status, GET /systems, GET /query/heartbeats, POST /query.
"""
from __future__ import annotations

from flask import Blueprint, render_template, request

from probe_auth import login_required
from sdk import api_get, api_post, page_args, query_args

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def index():
    status = api_get("/status")
    systems = api_get("/systems")
    hb_params = {**page_args(), **query_args("system_id", "check_id", "status",
                                             "from", "to", "sort")}
    heartbeats = api_get("/query/heartbeats", params=hb_params)
    return render_template("dashboard/index.html", status=status,
                           systems=systems, heartbeats=heartbeats)


@bp.route("/systems/<system_id>")
@login_required
def system_detail(system_id: str):
    time_from = request.args.get("from", "")
    time_to = request.args.get("to", "")
    heartbeats = api_get("/query/heartbeats",
                         params={"system_id": system_id, "from": time_from,
                                 "to": time_to})
    body = {
        "filters": [{"field": "system_id", "op": "eq", "value": system_id}],
        "from": time_from,
        "to": time_to,
        "aggregations": [
            {"type": "avg", "field": "response_ms", "interval": "1h"},
            {"type": "uptime"},
        ],
    }
    analysis = api_post("/query", json=body)
    return render_template("dashboard/system.html", system_id=system_id,
                           heartbeats=heartbeats, analysis=analysis,
                           time_from=time_from, time_to=time_to)
