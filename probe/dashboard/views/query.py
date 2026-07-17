"""PP-04 Interrogazione diretta (Probe).

REST (PROBE): GET /systems, POST /query. La ricerca guidata mostra i risultati
come tabella DataTables server-side (adattatore /dt/heartbeats della Sonda) coi
filtri passati via ajax.data.
"""
from __future__ import annotations

import json

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)

from pulse_fe_common.datetimes import time_presets

from probe_auth import login_required
from sdk import api_get, api_post

bp = Blueprint("query", __name__)

#: Finestra di ricerca per ricavare i check distinti di un sistema (scan doc).
_CHECK_SCAN_PRESET = "last_30d"
#: Limite di documenti scansionati per estrarre i check distinti.
_CHECK_SCAN_SIZE = 1000


def _json_or(default, raw: str):
    raw = (raw or "").strip()
    if not raw:
        return default
    return json.loads(raw)


def _timezone() -> str:
    """Fuso della dashboard Sonda (env PULSE_PROBE_TIMEZONE, come ``localdt``)."""
    return current_app.config["PULSE_CFG"].timezone


@bp.route("/query", methods=["GET"])
@login_required
def builder():
    systems = api_get("/systems")
    presets, tz_offset_min = time_presets(_timezone())
    return render_template("query/builder.html", result=None, systems=systems,
                           presets=presets, tz_offset_min=tz_offset_min)


@bp.route("/checks-by-system", methods=["GET"])
@login_required
def checks_by_system():
    """Proxy JSON: check distinti di un sistema (per i suggerimenti del Check).

    Il probe-agent NON espone un endpoint /systems/{id}/checks ne' l'aggregazione
    ``terms``; i check distinti vengono quindi ricavati da una scansione limitata
    dei documenti recenti (POST /query filtrato per ``system_id`` sull'ultimo
    periodo) deduplicando ``check_id``/``check_name``. Il controllo Check nella UI
    resta comunque a testo libero (datalist): questi sono solo suggerimenti.
    Senza ``system_id`` o su errore -> lista vuota (mai bloccante).
    Risposta minimale [{check_id, check_name}].
    """
    system_id = (request.args.get("system_id") or "").strip()
    if not system_id:
        return jsonify({"items": []}), 200
    presets, _ = time_presets(_timezone())
    window = presets[_CHECK_SCAN_PRESET]
    body = {
        "filters": [{"field": "system_id", "op": "eq", "value": system_id}],
        "from": window["from"],
        "to": window["to"],
        "aggregations": [],
        "page": 1,
        "page_size": _CHECK_SCAN_SIZE,
    }
    try:
        data = api_post("/query", json=body)
    except Exception:  # noqa: BLE001 - suggerimenti best-effort, mai bloccante
        return jsonify({"items": []}), 200
    items = data.get("items", []) if isinstance(data, dict) else []
    seen: dict[str, str] = {}
    for doc in items:
        cid = doc.get("check_id")
        if cid and cid not in seen:
            seen[cid] = doc.get("check_name") or ""
    out = [{"check_id": cid, "check_name": name} for cid, name in seen.items()]
    return jsonify({"items": out}), 200


@bp.route("/query", methods=["POST"])
@login_required
def run_query():
    try:
        body = {
            "filters": _json_or([], request.form.get("filters", "")),
            "from": request.form.get("from", ""),
            "to": request.form.get("to", ""),
            "aggregations": _json_or([], request.form.get("aggregations", "")),
        }
    except ValueError:
        flash("JSON di filtri/aggregazioni non valido.", "danger")
        return redirect(url_for("query.builder"))
    result = api_post("/query", json=body)
    systems = api_get("/systems")
    presets, tz_offset_min = time_presets(_timezone())
    return render_template("query/builder.html", result=result, systems=systems,
                           presets=presets, tz_offset_min=tz_offset_min)
