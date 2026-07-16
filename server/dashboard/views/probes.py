"""P-03 Dettaglio/Selezione Probe (drill-down) e P-09 Gestione Sonde.

REST: GET/POST /probes, GET/PUT/DELETE /probes/{id},
POST /probes/{id}/rotate-credentials, GET /probes/{id}/status,
GET /dashboard/probe/{id}, GET /probes/{id}/heartbeats.
"""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from pulse_fe_common.auth import permission_required

from sdk import (api_delete, api_get, api_post, api_put, page_args, paging,
                 query_args)

bp = Blueprint("probes", __name__)


def _tags(raw: str) -> list:
    return [t.strip() for t in raw.split(",") if t.strip()]


def _optional(raw: str):
    """Normalizza un campo anagrafico opzionale.

    Stringa vuota/spazi -> None (null) così da NON far scattare le validazioni
    del backend sui campi opzionali (es. contact_email vuota non deve dare 422).
    Il valore, se presente, viene inviato ripulito dagli spazi.
    """
    value = (raw or "").strip()
    return value or None


def _profile_fields() -> dict:
    """Campi anagrafici opzionali della Sonda (location + referente)."""
    return {
        "location": _optional(request.form.get("location", "")),
        "contact_name": _optional(request.form.get("contact_name", "")),
        "contact_email": _optional(request.form.get("contact_email", "")),
        "contact_phone": _optional(request.form.get("contact_phone", "")),
    }


# -- P-09 elenco / selettore ---------------------------------------------------
@bp.route("/probes")
@permission_required("probes.read")
def list_probes():
    params = {**page_args(), **query_args("q", "status")}
    data = api_get("/probes", params=params)
    filters = {k: v for k, v in params.items() if k != "page"}
    page, page_size = paging()
    return render_template("probes/list.html", data=data, filters=filters,
                           page=page, page_size=page_size)


@bp.route("/probes/new", methods=["GET"])
@permission_required("probes.create")
def new_probe():
    return render_template("probes/form.html", probe=None)


@bp.route("/probes/new", methods=["POST"])
@permission_required("probes.create")
def create_probe():
    payload = {
        "name": request.form.get("name", ""),
        "description": request.form.get("description", ""),
        "query_endpoint": request.form.get("query_endpoint", ""),
        "tags": _tags(request.form.get("tags", "")),
        "enabled": request.form.get("enabled") == "on",
        **_profile_fields(),
    }
    result = api_post("/probes", json=payload)
    flash("Probe creata. Copiare subito il token di enrollment.", "success")
    return render_template("probes/enrollment.html", result=result)


# -- P-03 drill-down -----------------------------------------------------------
@bp.route("/probes/<probe_id>")
@permission_required("probes.read")
def detail(probe_id: str):
    window = request.args.get("window", "24h")
    probe = api_get(f"/probes/{probe_id}")
    status = api_get(f"/probes/{probe_id}/status")
    overview = api_get(f"/dashboard/probe/{probe_id}", params={"window": window})
    hb_params = {**page_args(), **query_args("system_id", "check_id", "status",
                                             "from", "to", "sort")}
    heartbeats = api_get(f"/probes/{probe_id}/heartbeats", params=hb_params)
    # Il proxy /probes/{id}/heartbeats usa page_size di default 50 e ritorna
    # solo {items, total}: page/page_size effettivi vanno ricostruiti dalla view.
    page, page_size = paging(default_size=50)
    # Argomenti per i link di paginazione: probe_id (rotta), window e i filtri hb
    # correnti (+ page_size se custom), così la navigazione conserva tutto.
    hb_filters = {k: v for k, v in hb_params.items() if k != "page"}
    hb_filters["probe_id"] = probe_id
    hb_filters["window"] = window
    return render_template(
        "probes/detail.html",
        probe=probe,
        status=status,
        overview=overview,
        heartbeats=heartbeats,
        window=window,
        page=page,
        page_size=page_size,
        hb_filters=hb_filters,
    )


@bp.route("/probes/<probe_id>/edit", methods=["GET"])
@permission_required("probes.update")
def edit_probe(probe_id: str):
    probe = api_get(f"/probes/{probe_id}")
    return render_template("probes/form.html", probe=probe)


@bp.route("/probes/<probe_id>/edit", methods=["POST"])
@permission_required("probes.update")
def update_probe(probe_id: str):
    payload = {
        "name": request.form.get("name", ""),
        "description": request.form.get("description", ""),
        "query_endpoint": request.form.get("query_endpoint", ""),
        "tags": _tags(request.form.get("tags", "")),
        "enabled": request.form.get("enabled") == "on",
        **_profile_fields(),
    }
    api_put(f"/probes/{probe_id}", json=payload)
    flash("Probe aggiornata.", "success")
    return redirect(url_for("probes.detail", probe_id=probe_id))


@bp.route("/probes/<probe_id>/delete", methods=["POST"])
@permission_required("probes.delete")
def delete_probe(probe_id: str):
    api_delete(f"/probes/{probe_id}")
    flash("Probe eliminata.", "success")
    return redirect(url_for("probes.list_probes"))


@bp.route("/probes/<probe_id>/rotate", methods=["POST"])
@permission_required("probes.rotate_key")
def rotate_probe(probe_id: str):
    result = api_post(f"/probes/{probe_id}/rotate-credentials")
    flash("Credenziali ruotate. Copiare il nuovo token di enrollment.", "success")
    return render_template("probes/enrollment.html", result=result)
