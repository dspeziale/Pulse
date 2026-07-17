"""P-02 Dashboard aggregata (Server).

REST (solo endpoint esistenti): GET /dashboard/aggregate (systems_summary +
riepilogo per-sonda), GET /probes (anagrafica sonde), GET /alarms?status=active.
La view calcola qui i KPI, lo stato complessivo e i LED per-sonda in modo che
siano testabili con backend simulato (nessun dato inventato: se un valore non e'
disponibile la relativa tile viene omessa nel template).
"""
from __future__ import annotations

from flask import Blueprint, render_template, request

from pulse_fe_common.auth import permission_required

from sdk import api_get

bp = Blueprint("dashboard", __name__)


def _int(value) -> int:
    """Coercizione difensiva a intero (None/'' -> 0)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _probe_led(status: str, systems_down: int) -> str:
    """Stato LED di una singola Sonda.

    - offline/down (o stato non 'online'/'ok') -> 'error' (rosso);
    - online ma con sistemi down -> 'warn' (giallo);
    - altrimenti -> 'ok' (verde).
    """
    st = (status or "").strip().lower()
    if st in ("offline", "down", "error", "disabled") or (st and st not in ("online", "ok")):
        return "error"
    if systems_down > 0:
        return "warn"
    return "ok"


def _build_context(aggregate, probes, alarms):
    """Aggrega i dati dei tre endpoint in un contesto pronto per il template."""
    summary = (aggregate or {}).get("systems_summary") or {}
    ok = _int(summary.get("ok"))
    warn = _int(summary.get("warn"))
    error = _int(summary.get("error"))
    down = _int(summary.get("down"))
    unknown = _int(summary.get("unknown"))
    systems_total = ok + warn + error + down + unknown
    active_alarms = _int((aggregate or {}).get("active_alarms"))

    agg_probes = (aggregate or {}).get("probes") or []
    probe_rows = []
    probes_online = 0
    for p in agg_probes:
        st = (p.get("status") or "").strip().lower()
        s_down = _int(p.get("systems_down"))
        led = _probe_led(st, s_down)
        if led != "error":
            probes_online += 1
        # Stato di drill-down per la singola Sonda: se ha sistemi down si punta
        # ai check 'down'; per una Sonda offline (led error) si apre comunque il
        # suo dettaglio (nessun filtro), dove sara' evidente l'assenza di dati.
        row_drill = "down" if s_down > 0 else ""
        probe_rows.append({
            "probe_id": p.get("probe_id"),
            "status": p.get("status"),
            "systems_total": _int(p.get("systems_total")),
            "systems_down": s_down,
            "led": led,
            "drill": row_drill,
        })
    probes_total = len(agg_probes)
    probes_offline = probes_total - probes_online

    # Stato complessivo: dipende SOLO dallo stato dei check (systems_summary),
    # NON dagli allarmi (che sono incidenti generati dai workflow di notifica e
    # restano una voce separata). Rosso se error/down; giallo se warn; verde
    # altrimenti. La label esplicita il MOTIVO con i conteggi.
    if error > 0 or down > 0:
        overall = "error"
        overall_label = f"{error} in errore, {down} non raggiungibili"
        overall_target_status = "error" if error > 0 else "down"
    elif warn > 0:
        overall = "warn"
        overall_label = f"{warn} in warning"
        overall_target_status = "warn"
    else:
        overall = "ok"
        overall_label = "Tutto regolare"
        overall_target_status = None

    # Target del drill-down (clic su LED/tile):
    #  - una sola Sonda: si punta direttamente a quella;
    #  - piu' Sonde: il LED complessivo punta alla prima Sonda "interessata"
    #    (led != ok); le tile globali non sono link (si usano i link per-Sonda).
    single_probe_id = probe_rows[0]["probe_id"] if probes_total == 1 else None
    if single_probe_id is not None:
        drill_probe_id = single_probe_id
    else:
        drill_probe_id = None
        for p in probe_rows:
            if p["led"] != "ok":
                drill_probe_id = p["probe_id"]
                break

    kpis = {
        "systems_total": systems_total,
        "ok": ok, "warn": warn, "error": error, "down": down, "unknown": unknown,
        "active_alarms": active_alarms,
        "probes_total": probes_total,
        "probes_online": probes_online,
        "probes_offline": probes_offline,
    }
    return {
        "kpis": kpis,
        "overall": overall,
        "overall_label": overall_label,
        "overall_target_status": overall_target_status,
        "single_probe_id": single_probe_id,
        "drill_probe_id": drill_probe_id,
        "probe_rows": probe_rows,
        "summary": {"ok": ok, "warn": warn, "error": error,
                    "down": down, "unknown": unknown},
    }


@bp.route("/dashboard")
@permission_required("dashboard.read")
def index():
    window = request.args.get("window", "24h")
    aggregate = api_get("/dashboard/aggregate", params={"window": window})
    probes = api_get("/probes")
    alarms = api_get("/alarms", params={"status": "active"})
    ctx = _build_context(aggregate, probes, alarms)
    return render_template(
        "dashboard/index.html",
        aggregate=aggregate,
        probes=probes,
        alarms=alarms,
        window=window,
        **ctx,
    )
