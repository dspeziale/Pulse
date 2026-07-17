"""Scansioni NMAP (SICUREZZA).

Interfaccia FE per le scansioni NMAP eseguite dalle Sonde. Consuma solo gli
endpoint REST del backend (nessun accesso diretto):
- GET  /probes                                  selezione Sonda
- POST /probes/{probe_id}/scan   (scans.run)    avvia una scansione
- GET  /probes/{probe_id}/scans  (scans.read)   elenco scansioni (via /dt/scans)
- GET  /probes/{probe_id}/scan/{scan_id} (scans.read)  dettaglio scansione

Le rotte sono proxy sottili protette da permesso; il polling del dettaglio (per
le scansioni in corso) usa la variante JSON ``detail_json``.
"""
from __future__ import annotations

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)

from pulse_fe_common.auth import permission_required

from sdk import api_get, api_post

bp = Blueprint("scans", __name__)

#: Stati che indicano una scansione ancora in corso (per il polling).
RUNNING_STATES = ("running", "pending", "queued")

#: Categorie NSE offerte nella multi-select (le piu' comuni).
NSE_CATEGORIES = ["default", "safe", "discovery", "version", "vuln",
                  "auth", "brute", "exploit", "intrusive", "malware"]


def _int_or_none(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _clean(raw):
    value = (raw or "").strip()
    return value or None


def _build_options() -> dict:
    """Costruisce il body opzioni per POST /probes/{id}/scan dal form.

    Invia solo i campi valorizzati (gli altri restano ai default lato backend),
    cosi' da non forzare comportamenti indesiderati. I flag booleani sono inviati
    esplicitamente (checkbox).
    """
    f = request.form
    opts: dict = {"target": _clean(f.get("target"))}
    for key in ("timing", "technique", "ports", "script_args", "extra"):
        val = _clean(f.get(key))
        if val is not None:
            opts[key] = val
    for key in ("top_ports", "version_intensity", "min_rate", "max_rate",
                "max_retries"):
        num = _int_or_none(f.get(key))
        if num is not None:
            opts[key] = num
    opts["service_version"] = f.get("service_version") == "on"
    opts["os_detection"] = f.get("os_detection") == "on"
    opts["no_ping"] = f.get("no_ping") == "on"
    scripts = [s.strip() for s in request.form.getlist("scripts") if s.strip()]
    # Script specifici (campo testo, separati da virgola) uniti alle categorie.
    extra_scripts = _clean(f.get("scripts_extra"))
    if extra_scripts:
        scripts += [s.strip() for s in extra_scripts.split(",") if s.strip()]
    if scripts:
        opts["scripts"] = scripts
    return opts


@bp.route("/scans", methods=["GET"])
@permission_required("scans.read")
def index():
    probes = api_get("/probes", params={"page_size": 200})
    probe_id = (request.args.get("probe_id") or "").strip()
    return render_template("scans/index.html", probes=probes, probe_id=probe_id,
                           nse_categories=NSE_CATEGORIES)


@bp.route("/scans/run", methods=["POST"])
@permission_required("scans.run")
def run():
    probe_id = (request.form.get("probe_id") or "").strip()
    if not probe_id:
        flash("Selezionare una Sonda per avviare la scansione.", "danger")
        return redirect(url_for("scans.index"))
    options = _build_options()
    if not options.get("target"):
        flash("Indicare un target (IP, hostname o subnet CIDR).", "danger")
        return redirect(url_for("scans.index", probe_id=probe_id))
    result = api_post(f"/probes/{probe_id}/scan", json=options)
    scan_id = result.get("scan_id") if isinstance(result, dict) else None
    if scan_id:
        flash("Scansione avviata.", "success")
        return redirect(url_for("scans.detail", probe_id=probe_id,
                                scan_id=scan_id))
    flash("Scansione avviata.", "success")
    return redirect(url_for("scans.index", probe_id=probe_id))


@bp.route("/scans/<probe_id>/<scan_id>", methods=["GET"])
@permission_required("scans.read")
def detail(probe_id: str, scan_id: str):
    scan = api_get(f"/probes/{probe_id}/scan/{scan_id}")
    running = isinstance(scan, dict) and scan.get("status") in RUNNING_STATES
    return render_template("scans/detail.html", scan=scan, probe_id=probe_id,
                           scan_id=scan_id, running=running)


@bp.route("/scans/<probe_id>/<scan_id>.json", methods=["GET"])
@permission_required("scans.read")
def detail_json(probe_id: str, scan_id: str):
    """Stato/risultato della scansione in JSON (per il polling del dettaglio)."""
    scan = api_get(f"/probes/{probe_id}/scan/{scan_id}")
    status = scan.get("status") if isinstance(scan, dict) else None
    return jsonify({"status": status,
                    "running": status in RUNNING_STATES})
