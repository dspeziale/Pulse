"""Accesso al probe-agent (API di query locale) dalla dashboard Probe.

Le chiamate usano il token del probe-agent configurato via env (decisione FE-03):
la dashboard Probe è un client locale che interroga gli endpoint della PROBE
(`/api/v1/*`, sezione BACKEND del DOCUMENTO_API — "Endpoint sulla PROBE").
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from flask import current_app, request

from pulse_fe_common.http_client import ApiClient


def client() -> ApiClient:
    return current_app.config["API_CLIENT"]


def _token() -> str:
    return current_app.config["PULSE_CFG"].agent_token


def api_get(path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
    return client().get(path, token=_token(), params=params)


def api_post(path: str, json: Any = None) -> Any:
    return client().post(path, token=_token(), json=json)


def query_args(*names: str) -> dict:
    out: dict = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def page_args() -> dict:
    out: dict = {}
    for name in ("page", "page_size"):
        value = request.args.get(name)
        if value:
            out[name] = value
    return out


def paging(default_size: int = 50) -> tuple[int, int]:
    """Valori EFFETTIVI di paginazione usati per la richiesta.

    Le risposte di ``/query/heartbeats`` contengono solo ``items`` e ``total``
    (non ``page``/``page_size``): questi valori vanno ricostruiti dalla query
    string, usando gli stessi default del backend (proxy Sonda: ``page_size`` =
    50), così che il template possa decidere se/come mostrare la paginazione.
    Ritorna ``(page, page_size)`` con ``page >= 1`` e ``page_size >= 1``.
    Coerente con ``server/dashboard/sdk.py:paging``.
    """
    def _int(name: str, default: int) -> int:
        try:
            return int(request.args.get(name, default))
        except (TypeError, ValueError):
            return default

    return max(1, _int("page", 1)), max(1, _int("page_size", default_size))
