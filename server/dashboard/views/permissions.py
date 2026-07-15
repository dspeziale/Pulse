"""P-08 Catalogo Permessi (sola lettura). REST: GET /permissions."""
from __future__ import annotations

from flask import Blueprint, render_template

from pulse_fe_common.auth import permission_required

from sdk import api_get

bp = Blueprint("permissions", __name__)


@bp.route("/permissions")
@permission_required("permissions.read")
def list_permissions():
    data = api_get("/permissions")
    # Raggruppa per area per la visualizzazione.
    grouped: dict = {}
    for item in data.get("items", []):
        grouped.setdefault(item.get("area", "altro"), []).append(item)
    return render_template("permissions/list.html", grouped=grouped)
