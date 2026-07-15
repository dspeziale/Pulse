"""P-16 Audit Log. REST: GET /audit, GET /audit/{id}."""
from __future__ import annotations

from flask import Blueprint, render_template

from pulse_fe_common.auth import permission_required

from sdk import api_get, page_args, query_args

bp = Blueprint("audit", __name__)


@bp.route("/audit")
@permission_required("audit.read")
def list_audit():
    params = {**page_args(),
              **query_args("actor", "action", "entity_type", "entity_id",
                           "outcome", "from", "to")}
    data = api_get("/audit", params=params)
    return render_template("audit/list.html", data=data)


@bp.route("/audit/<entry_id>")
@permission_required("audit.read")
def detail(entry_id: str):
    entry = api_get(f"/audit/{entry_id}")
    return render_template("audit/detail.html", entry=entry)
