"""Poller degli heartbeat: interroga i sistemi, indicizza, rileva eventi, invia.

Il polling di un singolo sistema e la rilevazione eventi sono funzioni isolate e
testabili (client HTTP iniettabile). Il loop periodico e' orchestrato in `main`.
"""

from __future__ import annotations

import datetime as dt
import logging
import socket
import time
from typing import Any

import httpx

from . import canonical
from .state import RuntimeState

logger = logging.getLogger("pulse_probe.poller")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _open_tcp_connection(host: str, port: int, timeout: float) -> None:
    """Apre e chiude subito una connessione TCP verso host:port (isolabile nei test).

    Solleva OSError (inclusi timeout/ConnectionError) se la connessione fallisce.
    """
    with socket.create_connection((host, port), timeout=timeout):
        pass


def poll_tcp_system(system: dict[str, Any], probe_id: str | None) -> list[dict[str, Any]]:
    """Controlla la connettivita' TCP di un sistema (kind='tcp').

    Apre una connessione a `tcp_host:tcp_port` col timeout del sistema, misura il
    tempo di connessione e ritorna UN documento canonico check_id='tcp'.
    """
    system_id = system["system_id"]
    system_name = system.get("system_name", system_id)
    host = str(system.get("tcp_host") or "")
    port = int(system.get("tcp_port") or 0)
    timeout = float(system.get("timeout_seconds", 5))
    started = time.monotonic()
    try:
        _open_tcp_connection(host, port, timeout)
    except OSError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return [
            canonical.tcp_document(
                system_id=system_id,
                system_name=system_name,
                probe_id=probe_id,
                reachable=False,
                response_ms=elapsed,
                message=f"Connessione TCP fallita verso {host}:{port}: {exc}",
            )
        ]
    elapsed = int((time.monotonic() - started) * 1000)
    return [
        canonical.tcp_document(
            system_id=system_id,
            system_name=system_name,
            probe_id=probe_id,
            reachable=True,
            response_ms=elapsed,
            message=f"Connessione TCP riuscita verso {host}:{port}.",
        )
    ]


def poll_system(
    client: httpx.Client, system: dict[str, Any], probe_id: str | None
) -> list[dict[str, Any]]:
    """Interroga un sistema e ritorna i documenti canonici.

    Per kind='tcp' esegue un controllo di connettivita' TCP; per kind='http'
    (default) esegue la GET /api/heartbeat.
    """
    if system.get("kind") == "tcp":
        return poll_tcp_system(system, probe_id)
    url = system["heartbeat_url"]
    timeout = float(system.get("timeout_seconds", 5))
    started = time.monotonic()
    try:
        resp = client.get(url, timeout=timeout)
        latency_ms = int((time.monotonic() - started) * 1000)
    except httpx.HTTPError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return [
            canonical.unreachable_document(
                system_id=system["system_id"],
                system_name=system.get("system_name", system["system_id"]),
                probe_id=probe_id,
                http_status=None,
                latency_ms=latency_ms,
                message=f"Sistema irraggiungibile: {exc}",
            )
        ]
    if resp.status_code >= 400:
        return [
            canonical.unreachable_document(
                system_id=system["system_id"],
                system_name=system.get("system_name", system["system_id"]),
                probe_id=probe_id,
                http_status=resp.status_code,
                latency_ms=latency_ms,
                message=f"HTTP {resp.status_code} dal sistema.",
            )
        ]
    try:
        payload = resp.json()
    except ValueError:
        return [
            canonical.unreachable_document(
                system_id=system["system_id"],
                system_name=system.get("system_name", system["system_id"]),
                probe_id=probe_id,
                http_status=resp.status_code,
                latency_ms=latency_ms,
                message="Risposta non JSON.",
            )
        ]
    return canonical.build_documents(
        payload,
        system_id=system["system_id"],
        system_name=system.get("system_name", system["system_id"]),
        probe_id=probe_id,
        reachable=True,
        http_status=resp.status_code,
        latency_ms=latency_ms,
    )


def detect_events(
    docs: list[dict[str, Any]],
    last_statuses: dict[tuple[str, str], str],
    thresholds: dict[str, Any],
    probe_id: str | None,
) -> list[dict[str, Any]]:
    """Confronta i documenti col precedente stato e genera eventi per il Server."""
    events: list[dict[str, Any]] = []
    error_threshold = thresholds.get("response_ms_error")
    for doc in docs:
        key = (doc["system_id"], doc["check_id"])
        prev = last_statuses.get(key)
        current = doc["status"]
        ts = doc["@timestamp"]

        if not doc["reachable"]:
            if prev != "down":
                events.append(
                    _event("system_unreachable", doc, prev, probe_id, ts)
                )
        else:
            if prev in ("down", "error") and current == "ok":
                events.append(_event("system_recovered", doc, prev, probe_id, ts))
            elif prev is not None and prev != current:
                events.append(_event("status_changed", doc, prev, probe_id, ts))

        rms = doc.get("response_ms")
        if (
            error_threshold is not None
            and isinstance(rms, (int, float))
            and rms > float(error_threshold)
        ):
            events.append(_event("response_time_exceeded", doc, prev, probe_id, ts))

        last_statuses[key] = current
    return events


def _event(
    etype: str, doc: dict[str, Any], prev: str | None, probe_id: str | None, ts: str
) -> dict[str, Any]:
    return {
        "type": etype,
        "system_id": doc["system_id"],
        "check_id": doc["check_id"],
        "status": doc["status"],
        "previous_status": prev,
        "response_ms": doc.get("response_ms"),
        "reachable": doc["reachable"],
        "message": doc.get("message"),
        "timestamp": ts,
    }


def build_rollup(docs_by_system: dict[str, list[dict[str, Any]]], window: str) -> dict[str, Any]:
    """Costruisce il rollup aggregato per la dashboard del Server."""
    systems = []
    for system_id, docs in docs_by_system.items():
        if not docs:
            continue
        response_values = [d["response_ms"] for d in docs if isinstance(d.get("response_ms"), (int, float))]
        avg = round(sum(response_values) / len(response_values), 2) if response_values else 0.0
        up = sum(1 for d in docs if d["status"] == "ok")
        uptime = round(100.0 * up / len(docs), 2) if docs else 0.0
        # stato peggiore osservato come stato del sistema
        worst = _worst_status(docs)
        checks = [
            {"check_id": d["check_id"], "check_name": d.get("check_name"), "status": d["status"]}
            for d in docs
        ]
        systems.append(
            {
                "system_id": system_id,
                "status": worst,
                "avg_response_ms": avg,
                "uptime_pct": uptime,
                "checks": checks,
            }
        )
    return {"window": window, "generated_at": _now_iso(), "systems": systems}


_SEVERITY = {"ok": 0, "unknown": 1, "warn": 2, "error": 3, "down": 4}


def _worst_status(docs: list[dict[str, Any]]) -> str:
    worst = "ok"
    for d in docs:
        if _SEVERITY.get(d["status"], 1) > _SEVERITY.get(worst, 0):
            worst = d["status"]
    return worst


def poll_once(state: RuntimeState, client: httpx.Client) -> dict[str, Any]:
    """Un ciclo completo: polling di tutti i sistemi abilitati, storage, eventi, rollup."""
    all_events: list[dict[str, Any]] = []
    docs_by_system: dict[str, list[dict[str, Any]]] = {}
    polled = 0
    for system in state.systems:
        if not system.get("enabled", True):
            continue
        polled += 1
        docs = poll_system(client, system, state.probe_id)
        state.store.index_heartbeats(docs)
        docs_by_system[system["system_id"]] = docs
        thresholds = system.get("thresholds") or {}
        events = detect_events(docs, state.last_statuses, thresholds, state.probe_id)
        if events:
            state.store.index_events(events)
            all_events.extend(events)

    state.systems_polled = polled
    state.last_poll_at = _now_iso()

    # invio eventi al Server (best-effort)
    if all_events and state.probe_token:
        try:
            state.server.send_events(state.probe_token, all_events)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invio eventi fallito: %s", exc)
            state.pending_events += len(all_events)
        else:
            state.pending_events = 0

    # invio rollup al Server (best-effort)
    if state.probe_token:
        rollup = build_rollup(docs_by_system, state.settings.rollup_window)
        try:
            state.server.send_rollup(state.probe_token, rollup)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invio rollup fallito: %s", exc)

    return {"polled": polled, "events": len(all_events)}
