"""Parsing e normalizzazione dello schema canonico heartbeat.

Riferimento: 01_specifica_funzionale.md §4 (schema canonico), §4.1 (valori status),
§4.2 (oggetto singolo o array), §4.3 (campi aggiunti dalla Probe).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

# Valori di status normalizzati (UI/notifiche). Tutto il resto -> "unknown".
NORMALIZED_STATUSES = {"ok", "warn", "error", "down", "unknown"}


def normalize_status(raw: Any) -> str:
    """Normalizza lo status a dominio aperto verso {ok,warn,error,down,unknown}."""
    if not isinstance(raw, str):
        return "unknown"
    value = raw.strip().lower()
    return value if value in NORMALIZED_STATUSES else "unknown"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _as_list(payload: Any) -> list[dict[str, Any]]:
    """GET /api/heartbeat puo' restituire un oggetto singolo o un array (§4.2)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def build_documents(
    payload: Any,
    *,
    system_id: str,
    system_name: str,
    probe_id: str | None,
    reachable: bool,
    http_status: int | None,
    latency_ms: int | None,
) -> list[dict[str, Any]]:
    """Costruisce i documenti OpenSearch (uno per check) dallo heartbeat grezzo.

    Ogni documento contiene i campi canonici (§4) + i campi aggiunti dalla
    Probe (§4.3): probe_id, ingested_at, reachable, http_status, latency_ms.
    """
    ingested_at = _now_iso()
    raws = _as_list(payload)
    docs: list[dict[str, Any]] = []
    for raw in raws:
        status_raw = raw.get("status")
        docs.append(
            {
                "@timestamp": raw.get("@timestamp") or ingested_at,
                "system_id": raw.get("system_id") or system_id,
                "system_name": raw.get("system_name") or system_name,
                "check_id": raw.get("check_id") or "default",
                "check_name": raw.get("check_name"),
                "status": normalize_status(status_raw),
                "status_raw": status_raw,
                "response_ms": raw.get("response_ms"),
                "message": raw.get("message"),
                "details": raw.get("details"),
                "probe_id": probe_id,
                "reachable": reachable,
                "http_status": http_status,
                "latency_ms": latency_ms,
                "ingested_at": ingested_at,
            }
        )
    return docs


def tcp_document(
    *,
    system_id: str,
    system_name: str,
    probe_id: str | None,
    reachable: bool,
    response_ms: int | None,
    message: str,
) -> dict[str, Any]:
    """Documento canonico per un controllo di connettivita' TCP (check_id='tcp').

    status='ok' se la connessione riesce, 'down' altrimenti. Include i campi
    aggiunti dalla Probe (§4.3): probe_id, ingested_at, reachable, latency_ms.
    """
    ts = _now_iso()
    return {
        "@timestamp": ts,
        "system_id": system_id,
        "system_name": system_name,
        "check_id": "tcp",
        "check_name": "Connettivita' TCP",
        "status": "ok" if reachable else "down",
        "status_raw": None,
        "response_ms": response_ms,
        "message": message,
        "details": None,
        "probe_id": probe_id,
        "reachable": reachable,
        "http_status": None,
        "latency_ms": response_ms,
        "ingested_at": ts,
    }


def unreachable_document(
    *,
    system_id: str,
    system_name: str,
    probe_id: str | None,
    http_status: int | None,
    latency_ms: int | None,
    message: str,
) -> dict[str, Any]:
    """Documento sintetico per sistema irraggiungibile (§4.3): status 'down'."""
    ts = _now_iso()
    return {
        "@timestamp": ts,
        "system_id": system_id,
        "system_name": system_name,
        "check_id": "connectivity",
        "check_name": "Connettivita'",
        "status": "down",
        "status_raw": None,
        "response_ms": None,
        "message": message,
        "details": None,
        "probe_id": probe_id,
        "reachable": False,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "ingested_at": ts,
    }
