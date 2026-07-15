"""P-04 Interrogazione OpenSearch (query builder) e P-05 Grafici/Analisi.

REST: POST /probes/{id}/query, GET /probes/{id}/heartbeats,
GET /systems?probe_id=..., GET /systems/{id}/checks, GET /probes.
"""
from __future__ import annotations

import json

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import api_get, api_post

bp = Blueprint("query", __name__)


def _json_or(default, raw: str):
    raw = (raw or "").strip()
    if not raw:
        return default
    return json.loads(raw)


# -- P-04 query builder --------------------------------------------------------
@bp.route("/query", methods=["GET"])
@permission_required("heartbeats.query")
def builder():
    probes = api_get("/probes")
    probe_id = request.args.get("probe_id", "")
    systems = None
    checks = None
    if probe_id:
        systems = api_get("/systems", params={"probe_id": probe_id})
    system_id = request.args.get("system_id", "")
    if system_id:
        checks = api_get(f"/systems/{system_id}/checks")
    return render_template("query/builder.html", probes=probes, systems=systems,
                           checks=checks, probe_id=probe_id, system_id=system_id,
                           result=None)


@bp.route("/query", methods=["POST"])
@permission_required("heartbeats.query")
def run_query():
    probe_id = request.form.get("probe_id", "")
    if not probe_id:
        flash("Selezionare una Probe.", "danger")
        return redirect(url_for("query.builder"))
    try:
        body = {
            "filters": _json_or([], request.form.get("filters", "")),
            "from": request.form.get("from", ""),
            "to": request.form.get("to", ""),
            "aggregations": _json_or([], request.form.get("aggregations", "")),
        }
    except ValueError:
        flash("JSON di filtri/aggregazioni non valido.", "danger")
        return redirect(url_for("query.builder", probe_id=probe_id))
    result = api_post(f"/probes/{probe_id}/query", json=body)
    probes = api_get("/probes")
    return render_template("query/builder.html", probes=probes, systems=None,
                           checks=None, probe_id=probe_id, system_id="",
                           result=result)


# -- P-05 grafici / analisi ----------------------------------------------------
@bp.route("/charts", methods=["GET"])
@permission_required("heartbeats.read")
def charts():
    probes = api_get("/probes")
    probe_id = request.args.get("probe_id", "")
    system_id = request.args.get("system_id", "")
    time_from = request.args.get("from", "")
    time_to = request.args.get("to", "")
    heartbeats = None
    aggregations = None
    if probe_id and system_id:
        filters = [{"field": "system_id", "op": "eq", "value": system_id}]
        body = {
            "filters": filters,
            "from": time_from,
            "to": time_to,
            "aggregations": [
                {"type": "avg", "field": "response_ms", "interval": "1h"},
                {"type": "uptime"},
            ],
        }
        agg_result = api_post(f"/probes/{probe_id}/query", json=body)
        aggregations = agg_result.get("aggregations")
        heartbeats = api_get(
            f"/probes/{probe_id}/heartbeats",
            params={"system_id": system_id, "from": time_from, "to": time_to},
        )
    return render_template("query/charts.html", probes=probes, probe_id=probe_id,
                           system_id=system_id, heartbeats=heartbeats,
                           aggregations=aggregations, time_from=time_from,
                           time_to=time_to)
