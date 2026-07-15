"""PP-04 Interrogazione diretta (Probe). REST (PROBE): POST /query."""
from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from probe_auth import login_required
from sdk import api_post

bp = Blueprint("query", __name__)


def _json_or(default, raw: str):
    raw = (raw or "").strip()
    if not raw:
        return default
    return json.loads(raw)


@bp.route("/query", methods=["GET"])
@login_required
def builder():
    return render_template("query/builder.html", result=None)


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
    return render_template("query/builder.html", result=result)
