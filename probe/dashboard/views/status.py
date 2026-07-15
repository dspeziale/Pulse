"""PP-05 Stato Probe / Salute.

REST (PROBE): GET /status, GET /health/ready.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from probe_auth import login_required
from pulse_fe_common.http_client import ApiError, ApiUnavailableError
from sdk import api_get

bp = Blueprint("status", __name__)


@bp.route("/status")
@login_required
def show_status():
    status = api_get("/status")
    # /health/ready può rispondere 503: mostriamo comunque lo stato interno.
    try:
        ready = api_get("/health/ready")
    except (ApiError, ApiUnavailableError) as exc:
        ready = {"status": "not-ready", "error": getattr(exc, "message", str(exc))}
    return render_template("status/index.html", status=status, ready=ready)
