"""P-18 Configurazione. REST: GET /config, PUT /config."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from pulse_fe_common.auth import permission_required

from sdk import api_get, api_put

bp = Blueprint("config_bp", __name__)


@bp.route("/config")
@permission_required("config.read")
def show_config():
    data = api_get("/config")
    return render_template("config/list.html", data=data)


@bp.route("/config", methods=["POST"])
@permission_required("config.update")
def update_config():
    items = []
    # I campi del form sono nominati "value:<key>".
    for field, value in request.form.items():
        if field.startswith("value:"):
            items.append({"key": field[len("value:"):], "value": value})
    result = api_put("/config", json={"items": items})
    updated = ", ".join(result.get("updated", [])) or "nessuno"
    flash(f"Parametri aggiornati: {updated}.", "success")
    if result.get("requires_restart"):
        flash("Alcuni parametri richiedono il riavvio del servizio.", "warning")
    return redirect(url_for("config_bp.show_config"))
