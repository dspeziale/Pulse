"""PP-02 Dashboard Probe completa e PP-03 Dettaglio sistema/check.

REST (PROBE): GET /status, GET /systems, GET /query/heartbeats, POST /query.
"""
from __future__ import annotations

from flask import Blueprint, render_template, request

from probe_auth import login_required
from sdk import api_get, api_post, page_args, paging, query_args

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def index():
    status = api_get("/status")
    systems = api_get("/systems")
    hb_params = {**page_args(), **query_args("system_id", "check_id", "status",
                                             "from", "to", "sort")}
    heartbeats = api_get("/query/heartbeats", params=hb_params)
    # Il proxy /query/heartbeats usa page_size di default 50 e ritorna solo
    # {items, total}: page/page_size effettivi vanno ricostruiti dalla view.
    page, page_size = paging(default_size=50)
    # Filtri per i link di paginazione e il selettore page size (page escluso:
    # il selettore riparte da page=1; page_size custom conservato).
    hb_filters = {k: v for k, v in hb_params.items() if k != "page"}
    return render_template("dashboard/index.html", status=status,
                           systems=systems, heartbeats=heartbeats,
                           page=page, page_size=page_size,
                           hb_filters=hb_filters)


@bp.route("/systems/<system_id>")
@login_required
def system_detail(system_id: str):
    time_from = request.args.get("from", "")
    time_to = request.args.get("to", "")
    hb_params = {**page_args(),
                 **query_args("check_id", "status", "sort"),
                 "system_id": system_id, "from": time_from, "to": time_to}
    heartbeats = api_get("/query/heartbeats", params=hb_params)
    # page/page_size effettivi + filtri per paginazione/selettore (vedi index()).
    page, page_size = paging(default_size=50)
    hb_filters = {k: v for k, v in hb_params.items() if k != "page"}
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
                           time_from=time_from, time_to=time_to,
                           page=page, page_size=page_size,
                           hb_filters=hb_filters)
