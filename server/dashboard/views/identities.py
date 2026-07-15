"""P-15 Le mie identità di canale.

REST: GET/POST /channel-identities, DELETE /channel-identities/{id}.
"""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import api_delete, api_get, api_post

bp = Blueprint("identities", __name__)


@bp.route("/channel-identities")
@permission_required("commands.execute")
def list_identities():
    data = api_get("/channel-identities")
    return render_template("identities/list.html", data=data)


@bp.route("/channel-identities", methods=["POST"])
@permission_required("commands.execute")
def create_identity():
    payload = {
        "channel_type": request.form.get("channel_type", ""),
        "external_id": request.form.get("external_id", ""),
        "verification_code": request.form.get("verification_code", ""),
    }
    api_post("/channel-identities", json=payload)
    flash("Identità associata.", "success")
    return redirect(url_for("identities.list_identities"))


@bp.route("/channel-identities/<identity_id>/delete", methods=["POST"])
@permission_required("commands.execute")
def delete_identity(identity_id: str):
    api_delete(f"/channel-identities/{identity_id}")
    flash("Identità rimossa.", "success")
    return redirect(url_for("identities.list_identities"))
