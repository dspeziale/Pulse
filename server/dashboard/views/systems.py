"""P-10 Gestione Sistemi Monitorati.

REST: GET/POST /systems, GET/PUT/DELETE /systems/{id},
GET /systems/{id}/checks, GET /probes (selezione).
"""
from __future__ import annotations

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)

from pulse_fe_common.auth import permission_required
from pulse_fe_common.http_client import (ApiAuthError, ApiError,
                                         ApiUnavailableError)

from sdk import (api_delete, api_get, api_post, api_put, page_args, query_args)

bp = Blueprint("systems", __name__)


def _int_or_none(raw: str):
    raw = (raw or "").strip()
    return int(raw) if raw else None


def _build_payload() -> dict:
    return {
        "system_id": request.form.get("system_id", ""),
        "system_name": request.form.get("system_name", ""),
        "heartbeat_url": request.form.get("heartbeat_url", ""),
        "probe_id": request.form.get("probe_id", ""),
        "poll_interval_seconds": _int_or_none(
            request.form.get("poll_interval_seconds", "")),
        "timeout_seconds": _int_or_none(request.form.get("timeout_seconds", "")),
        "enabled": request.form.get("enabled") == "on",
        "thresholds": {
            "response_ms_warn": _int_or_none(
                request.form.get("response_ms_warn", "")),
            "response_ms_error": _int_or_none(
                request.form.get("response_ms_error", "")),
        },
    }


@bp.route("/systems")
@permission_required("systems.read")
def list_systems():
    params = {**page_args(), **query_args("q", "probe_id", "enabled")}
    data = api_get("/systems", params=params)
    probes = api_get("/probes")
    return render_template("systems/list.html", data=data, probes=probes)


@bp.route("/systems/test-heartbeat", methods=["POST"])
@permission_required("systems.create", "systems.update")
def test_heartbeat():
    """Testa l'endpoint heartbeat prima del salvataggio.

    Consuma il valore corrente del campo URL (creazione o modifica), delega al
    backend POST /systems/test col token di sessione e restituisce l'esito come
    JSON al browser. Gli errori del backend diventano messaggi comprensibili;
    l'irraggiungibilità del target NON è un errore (200 con reachable=false).
    """
    payload = request.get_json(silent=True) or request.form
    heartbeat_url = (payload.get("heartbeat_url") or "").strip()
    if not heartbeat_url:
        return jsonify({"ok": False,
                        "error": "Inserisci un URL heartbeat da testare."}), 422
    body: dict = {"heartbeat_url": heartbeat_url}
    timeout = _int_or_none(str(payload.get("timeout_seconds") or ""))
    if timeout is not None:
        body["timeout_seconds"] = timeout
    try:
        result = api_post("/systems/test", json=body)
    except ApiAuthError:
        return jsonify({"ok": False,
                        "error": "Sessione scaduta: effettua di nuovo "
                                 "l'accesso ed esegui di nuovo il test."}), 401
    except ApiError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code
    except ApiUnavailableError as exc:
        return jsonify({"ok": False,
                        "error": "Backend non raggiungibile: "
                                 f"{exc.message}"}), 503
    return jsonify({"ok": True, "result": result}), 200


@bp.route("/systems/new", methods=["GET"])
@permission_required("systems.create")
def new_system():
    probes = api_get("/probes")
    return render_template("systems/form.html", system=None, probes=probes)


@bp.route("/systems/new", methods=["POST"])
@permission_required("systems.create")
def create_system():
    api_post("/systems", json=_build_payload())
    flash("Sistema creato.", "success")
    return redirect(url_for("systems.list_systems"))


@bp.route("/systems/<system_id>")
@permission_required("systems.read")
def detail(system_id: str):
    system = api_get(f"/systems/{system_id}")
    checks = api_get(f"/systems/{system_id}/checks")
    return render_template("systems/detail.html", system=system, checks=checks)


@bp.route("/systems/<system_id>/edit", methods=["GET"])
@permission_required("systems.update")
def edit_system(system_id: str):
    system = api_get(f"/systems/{system_id}")
    probes = api_get("/probes")
    return render_template("systems/form.html", system=system, probes=probes)


@bp.route("/systems/<system_id>/edit", methods=["POST"])
@permission_required("systems.update")
def update_system(system_id: str):
    api_put(f"/systems/{system_id}", json=_build_payload())
    flash("Sistema aggiornato.", "success")
    return redirect(url_for("systems.detail", system_id=system_id))


@bp.route("/systems/<system_id>/delete", methods=["POST"])
@permission_required("systems.delete")
def delete_system(system_id: str):
    api_delete(f"/systems/{system_id}")
    flash("Sistema eliminato.", "success")
    return redirect(url_for("systems.list_systems"))
