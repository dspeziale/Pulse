"""P-nuova — Compendio sistema + export PDF.

Pagina di riepilogo per un SISTEMA nel PERIODO selezionato (default: "Oggi") con
KPI, tabella per-check, allarmi del periodo e un grafico del tempo di risposta,
piu' l'export di un report PDF professionale (font PT Sans Narrow).

REST consumati (solo endpoint esistenti):
- GET  /systems/{id}                    dettagli sistema (kind, probe_id, ...)
- GET  /systems/{id}/checks             check scoperti (ultimo stato/contatto)
- POST /probes/{probe_id}/query         aggregazioni avg/min/max/count/uptime
- GET  /probes/{probe_id}/heartbeats    campioni per il grafico response_ms
- GET  /alarms                          incidenti del periodo (best-effort)

Il periodo e' calcolato nel fuso configurato (coerente con ``localdt``) e
convertito in UTC per le query, riusando ``time_presets`` della pagina P-04.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, render_template, request

from pulse_fe_common.auth import permission_required
from pulse_fe_common.datetimes import DEFAULT_TIMEZONE, format_datetime
from pulse_fe_common.http_client import ApiError, ApiUnavailableError

from report_pdf import build_report_pdf
from sdk import api_get, api_post

from .query import _current_timezone, time_presets

bp = Blueprint("report", __name__)

#: Ordine canonico degli stati e severita' crescente (per lo "stato peggiore").
_STATUSES = ["ok", "warn", "error", "down", "unknown"]
_SEVERITY = {"ok": 0, "unknown": 1, "warn": 2, "error": 3, "down": 4}

#: Aggregazioni sul response_ms + uptime + conteggio campioni.
_RESP_AGGS = [
    {"type": "uptime"},
    {"type": "count"},
    {"type": "avg", "field": "response_ms"},
    {"type": "min", "field": "response_ms"},
    {"type": "max", "field": "response_ms"},
]


def _local_to_utc(value: str, tz_name: str) -> str | None:
    """Converte un ``datetime-local`` (naive, nel fuso ``tz_name``) in UTC ISO 'Z'.

    Ritorna ``None`` se il valore e' vuoto o non interpretabile.
    """
    text = (value or "").strip().replace("T", " ")
    if not text:
        return None
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        return None
    try:
        zone = ZoneInfo(tz_name)
    except Exception:  # tz sconosciuto -> default
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return (parsed.replace(tzinfo=zone).astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def _resolve_period(tz_name: str) -> dict:
    """Risolve il periodo selezionato in (from, to) UTC + etichette locali.

    Preset supportati come in P-04: ``today`` (DEFAULT), ``last_hour``,
    ``last_24h``, ``last_7d``, ``last_30d`` e ``custom`` (from/to locali). Un
    intervallo personalizzato incompleto/non valido ripiega su "Oggi".
    """
    presets, tz_offset_min = time_presets(tz_name)
    preset = (request.args.get("preset") or "today").strip() or "today"
    frm = to = None
    if preset == "custom":
        frm = _local_to_utc(request.args.get("from", ""), tz_name)
        to = _local_to_utc(request.args.get("to", ""), tz_name)
    if frm is None or to is None:
        if preset not in presets:
            preset = "today"
        window = presets[preset]
        frm, to = window["from"], window["to"]
    return {
        "preset": preset,
        "from": frm,
        "to": to,
        "from_local": format_datetime(frm, tz_name),
        "to_local": format_datetime(to, tz_name),
        "from_raw": request.args.get("from", ""),
        "to_raw": request.args.get("to", ""),
        "tz_name": tz_name,
        "tz_offset_min": tz_offset_min,
        "presets": presets,
    }


def _aggs(probe_id: str, filters: list, frm: str, to: str) -> dict:
    body = {"filters": filters, "from": frm, "to": to, "aggregations": _RESP_AGGS}
    res = api_post(f"/probes/{probe_id}/query", json=body)
    return res.get("aggregations") or {}


def _distribution(probe_id: str, base: list, frm: str, to: str) -> list:
    """Distribuzione dei campioni per stato (conteggio) nel periodo."""
    out = []
    for st in _STATUSES:
        body = {
            "filters": base + [{"field": "status", "op": "eq", "value": st}],
            "from": frm, "to": to, "aggregations": [{"type": "count"}],
        }
        res = api_post(f"/probes/{probe_id}/query", json=body)
        cnt = int((res.get("aggregations") or {}).get("count") or 0)
        if cnt:
            out.append({"status": st, "count": cnt})
    return out


def _worst_status(distribution: list) -> str:
    worst, rank = "unknown", -1
    for d in distribution:
        r = _SEVERITY.get(d["status"], 1)
        if r > rank:
            rank, worst = r, d["status"]
    return worst


def _alarms(system_uuid, frm: str, to: str) -> dict:
    """Allarmi del periodo per il sistema (best-effort: senza workflows.read
    l'utente vede comunque il resto del compendio)."""
    try:
        data = api_get("/alarms",
                       params={"system_id": system_uuid, "from": frm, "to": to})
    except (ApiError, ApiUnavailableError):
        return {"items": [], "total": 0}
    return data if isinstance(data, dict) else {"items": [], "total": 0}


def _gather(system: dict, checks: dict, frm: str, to: str) -> dict:
    """Raccoglie tutte le metriche del periodo dagli endpoint esistenti."""
    biz_id = system.get("system_id")
    probe_id = system.get("probe_id")
    overall: dict = {}
    distribution: list = []
    per_check: list = []
    samples: list = []
    alarms: dict = {"items": [], "total": 0}
    if probe_id and biz_id:
        base = [{"field": "system_id", "op": "eq", "value": biz_id}]
        overall = _aggs(probe_id, base, frm, to)
        distribution = _distribution(probe_id, base, frm, to)
        for c in (checks.get("items") or []):
            cf = base + [{"field": "check_id", "op": "eq",
                          "value": c.get("check_id")}]
            per_check.append({**c, "aggs": _aggs(probe_id, cf, frm, to)})
        hb = api_get(
            f"/probes/{probe_id}/heartbeats",
            params={"system_id": biz_id, "from": frm, "to": to,
                    "sort": "@timestamp", "page_size": 500},
        )
        samples = (hb.get("items") if isinstance(hb, dict) else None) or []
        alarms = _alarms(system.get("id"), frm, to)
    return {
        "overall": overall,
        "distribution": distribution,
        "per_check": per_check,
        "samples": samples,
        "alarms": alarms,
        "worst": _worst_status(distribution),
    }


def _pdf_args(period: dict) -> dict:
    """Parametri di periodo da propagare al link 'Scarica PDF'."""
    args = {"preset": period["preset"]}
    if period["preset"] == "custom":
        args["from"] = period["from_raw"]
        args["to"] = period["to_raw"]
    return args


def _filename(system: dict, period: dict) -> str:
    def _day(iso: str) -> str:
        return format_datetime(iso, period["tz_name"], "%Y%m%d")

    biz = system.get("system_id") or "sistema"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", str(biz)).strip("-") or "sistema"
    return f"compendio_{safe}_{_day(period['from'])}_{_day(period['to'])}.pdf"


@bp.route("/systems/<system_id>/report")
@permission_required("systems.read")
def compendio(system_id: str):
    system = api_get(f"/systems/{system_id}")
    checks = api_get(f"/systems/{system_id}/checks")
    period = _resolve_period(_current_timezone())
    data = _gather(system, checks, period["from"], period["to"])
    return render_template(
        "systems/report.html",
        system=system, checks=checks, period=period,
        pdf_args=_pdf_args(period), **data,
    )


@bp.route("/systems/<system_id>/report.pdf")
@permission_required("systems.read")
def compendio_pdf(system_id: str):
    system = api_get(f"/systems/{system_id}")
    checks = api_get(f"/systems/{system_id}/checks")
    period = _resolve_period(_current_timezone())
    data = _gather(system, checks, period["from"], period["to"])
    pdf_bytes = build_report_pdf(system, checks, period, data)
    # Default: apertura INLINE nel browser (via http) -> nessuna origine file://
    # e nessun warning del visualizzatore. Con ?download=1 si forza il download.
    disposition = "attachment" if request.args.get("download") else "inline"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition":
                f'{disposition}; filename="{_filename(system, period)}"',
        },
    )
