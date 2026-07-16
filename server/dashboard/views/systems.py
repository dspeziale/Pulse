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

from sdk import (api_delete, api_get, api_post, api_put, page_args, paging,
                 query_args)

bp = Blueprint("systems", __name__)


def _int_or_none(raw: str):
    raw = (raw or "").strip()
    return int(raw) if raw else None


def _normalized_kind(raw: str) -> str:
    """Normalizza il tipo di controllo a "http" o "tcp" (default http)."""
    kind = (raw or "").strip().lower()
    return kind if kind in ("http", "tcp") else "http"


def _build_payload() -> dict:
    kind = _normalized_kind(request.form.get("kind", ""))
    payload = {
        "system_id": request.form.get("system_id", ""),
        "system_name": request.form.get("system_name", ""),
        "kind": kind,
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
    # Invia solo i campi pertinenti al tipo; gli altri a None per non far
    # scattare i CHECK di coerenza del backend/DB (kind vs campi target).
    if kind == "tcp":
        payload["heartbeat_url"] = None
        payload["tcp_host"] = request.form.get("tcp_host", "").strip()
        payload["tcp_port"] = _int_or_none(request.form.get("tcp_port", ""))
    else:
        payload["heartbeat_url"] = request.form.get("heartbeat_url", "").strip()
        payload["tcp_host"] = None
        payload["tcp_port"] = None
    return payload


@bp.route("/systems")
@permission_required("systems.read")
def list_systems():
    # Il tipo di sistema pilota le due TAB: "Applicazioni" (http, default) e
    # "Connettività" (tcp). Il filtro effettivo lo applica il backend.
    kind = _normalized_kind(request.args.get("kind", ""))
    params = {**page_args(), **query_args("q", "probe_id", "enabled"),
              "kind": kind}
    data = api_get("/systems", params=params)
    probes = api_get("/probes")
    # I filtri (kind incluso, page escluso) alimentano i link di paginazione,
    # così la navigazione tra pagine conserva la TAB attiva e gli altri filtri.
    filters = {k: v for k, v in params.items() if k != "page"}
    page, page_size = paging()
    return render_template("systems/list.html", data=data, probes=probes,
                           filters=filters, page=page, page_size=page_size,
                           kind=kind)


@bp.route("/systems-by-probe", methods=["GET"])
@permission_required("systems.read")
def systems_by_probe():
    """Proxy JSON: elenca i sistemi appartenenti a una Sonda.

    Alimenta l'auto-popolamento AJAX dei selettori di Sistema quando l'utente
    cambia la Sonda. Delega al backend GET /systems?probe_id=... col token di
    sessione. Senza ``probe_id`` restituisce una lista vuota (nessuna Sonda
    selezionata). La risposta è la lista minimale [{id, system_id, system_name}].
    """
    probe_id = (request.args.get("probe_id") or "").strip()
    if not probe_id:
        return jsonify({"items": []}), 200
    data = api_get("/systems", params={"probe_id": probe_id})
    items = data.get("items", []) if isinstance(data, dict) else []
    out = [
        {
            "id": s.get("id"),
            "system_id": s.get("system_id"),
            "system_name": s.get("system_name"),
        }
        for s in items
    ]
    return jsonify({"items": out}), 200


@bp.route("/systems/test-heartbeat", methods=["POST"])
@permission_required("systems.create", "systems.update")
def test_heartbeat():
    """Testa la raggiungibilità del target prima del salvataggio.

    Consuma i valori correnti del form (HTTP heartbeat oppure connettività TCP),
    delega al backend POST /systems/test col token di sessione e restituisce
    l'esito come JSON al browser. Gli errori del backend diventano messaggi
    comprensibili; l'irraggiungibilità del target NON è un errore (200 con
    reachable=false).
    """
    payload = request.get_json(silent=True) or request.form
    kind = _normalized_kind(payload.get("kind", ""))
    body: dict = {"kind": kind}
    if kind == "tcp":
        tcp_host = (payload.get("tcp_host") or "").strip()
        tcp_port = _int_or_none(str(payload.get("tcp_port") or ""))
        if not tcp_host or tcp_port is None:
            return jsonify({"ok": False,
                            "error": "Inserisci host e porta TCP da testare."}), 422
        body["tcp_host"] = tcp_host
        body["tcp_port"] = tcp_port
    else:
        heartbeat_url = (payload.get("heartbeat_url") or "").strip()
        if not heartbeat_url:
            return jsonify({"ok": False,
                            "error": "Inserisci un URL heartbeat da testare."}), 422
        body["heartbeat_url"] = heartbeat_url
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
    # Preselezione del tipo coerente con la TAB da cui si arriva (?kind=tcp).
    initial_kind = _normalized_kind(request.args.get("kind", ""))
    return render_template("systems/form.html", system=None, probes=probes,
                           initial_kind=initial_kind)


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
